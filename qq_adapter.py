"""OneBot/NapCat adapter for QQ group access to AIOps fault KB chat."""

from __future__ import annotations

import http.cookiejar
import base64
import json
import logging
import os
import queue
import re
import smtplib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request


LOGGER = logging.getLogger(__name__)


def load_runtime_env() -> None:
    for candidate in (".env", "deploy/.env"):
        if os.path.exists(candidate):
            load_dotenv(candidate, override=False)


def csv_values(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def csv_list(value: str | None, default: list[str]) -> list[str]:
    items = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return items or default


def trigger_prefixes_from_env(value: str | None) -> list[str]:
    defaults = ["/故障", "/报修", "/kb", "#故障", "#报修"]
    configured = csv_list(value, [])
    result: list[str] = []
    for item in defaults + configured:
        if item and item not in result:
            result.append(item)
    return result


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class AdapterConfig:
    onebot_api_base: str
    onebot_access_token: str
    onebot_token_in_query: bool
    event_token: str
    aiops_api_base: str
    aiops_username: str
    aiops_password: str
    allowed_groups: set[str]
    trigger_prefixes: list[str]
    bot_self_id: str
    reply_timeout_seconds: int
    max_reply_chars: int
    startup_notice: bool
    global_concurrency: int = 6
    group_concurrency: int = 3
    queue_size: int = 20
    user_rate_limit: int = 3
    group_rate_limit: int = 5
    rate_window_seconds: int = 60
    max_question_chars: int = 300
    audit_log_path: str = "/data/jscn-aiops/qq-audit/qq_adapter_audit.jsonl"
    audit_question_chars: int = 300
    audit_answer_preview_chars: int = 300
    bot_status_path: str = "/data/jscn-aiops/qq-audit/qq_bot_status.json"
    bot_monitor_enabled: bool = True
    bot_monitor_interval_seconds: int = 60
    bot_offline_email_enabled: bool = False
    bot_offline_email_cooldown_seconds: int = 3600
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    mail_from: str = ""
    mail_to: list[str] | None = None
    napcat_webui_base: str = "http://127.0.0.1:6099"
    napcat_webui_public_url: str = ""
    napcat_webui_token: str = ""

    @classmethod
    def from_env(cls) -> "AdapterConfig":
        return cls(
            onebot_api_base=os.getenv("ONEBOT_API_BASE", "http://127.0.0.1:3000").rstrip("/"),
            onebot_access_token=os.getenv("ONEBOT_ACCESS_TOKEN", ""),
            onebot_token_in_query=str(os.getenv("ONEBOT_TOKEN_IN_QUERY", "false")).lower() in {"1", "true", "yes", "on"},
            event_token=os.getenv("QQ_ADAPTER_EVENT_TOKEN", ""),
            aiops_api_base=os.getenv("AIOPS_API_BASE", "http://127.0.0.1:8080").rstrip("/"),
            aiops_username=os.getenv("AIOPS_BOT_USERNAME", ""),
            aiops_password=os.getenv("AIOPS_BOT_PASSWORD", ""),
            allowed_groups=csv_values(os.getenv("QQ_GROUP_ALLOWLIST")),
            trigger_prefixes=trigger_prefixes_from_env(os.getenv("QQ_TRIGGER_PREFIX")),
            bot_self_id=str(os.getenv("QQ_BOT_SELF_ID", "")).strip(),
            reply_timeout_seconds=env_int("QQ_REPLY_TIMEOUT_SECONDS", 90, 5, 300),
            max_reply_chars=env_int("QQ_MAX_REPLY_CHARS", 1600, 200, 4000),
            startup_notice=str(os.getenv("QQ_ADAPTER_STARTUP_NOTICE", "false")).lower() in {"1", "true", "yes", "on"},
            global_concurrency=env_int("QQ_GLOBAL_CONCURRENCY", 6, 1, 20),
            group_concurrency=env_int("QQ_GROUP_CONCURRENCY", 3, 1, 10),
            queue_size=env_int("QQ_QUEUE_SIZE", 20, 1, 200),
            user_rate_limit=env_int("QQ_USER_RATE_LIMIT", 3, 1, 60),
            group_rate_limit=env_int("QQ_GROUP_RATE_LIMIT", 5, 1, 120),
            rate_window_seconds=env_int("QQ_RATE_WINDOW_SECONDS", 60, 10, 3600),
            max_question_chars=env_int("QQ_MAX_QUESTION_CHARS", 300, 20, 2000),
            audit_log_path=os.getenv("QQ_AUDIT_LOG_PATH", "/data/jscn-aiops/qq-audit/qq_adapter_audit.jsonl"),
            audit_question_chars=env_int("QQ_AUDIT_QUESTION_CHARS", 300, 20, 2000),
            audit_answer_preview_chars=env_int("QQ_AUDIT_ANSWER_PREVIEW_CHARS", 300, 0, 2000),
            bot_status_path=os.getenv("QQ_BOT_STATUS_PATH", "/data/jscn-aiops/qq-audit/qq_bot_status.json"),
            bot_monitor_enabled=str(os.getenv("QQ_BOT_MONITOR_ENABLED", "true")).lower() in {"1", "true", "yes", "on"},
            bot_monitor_interval_seconds=env_int("QQ_BOT_MONITOR_INTERVAL_SECONDS", 60, 10, 3600),
            bot_offline_email_enabled=str(os.getenv("QQ_BOT_OFFLINE_EMAIL_ENABLED", "false")).lower() in {"1", "true", "yes", "on"},
            bot_offline_email_cooldown_seconds=env_int("QQ_BOT_OFFLINE_EMAIL_COOLDOWN_SECONDS", 3600, 300, 86400),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=env_int("SMTP_PORT", 465, 1, 65535),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_use_tls=str(os.getenv("SMTP_USE_TLS", "true")).lower() in {"1", "true", "yes", "on"},
            mail_from=os.getenv("MAIL_FROM", "") or os.getenv("SMTP_USER", ""),
            mail_to=csv_list(os.getenv("QQ_BOT_OFFLINE_EMAIL_TO"), []),
            napcat_webui_base=os.getenv("NAPCAT_WEBUI_BASE", "http://127.0.0.1:6099").rstrip("/"),
            napcat_webui_public_url=os.getenv("NAPCAT_WEBUI_PUBLIC_URL", "").rstrip("/"),
            napcat_webui_token=os.getenv("NAPCAT_WEBUI_TOKEN", ""),
        )


class JsonHttpClient:
    def __init__(self, timeout: int):
        self.timeout = timeout

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


class AiopsSessionClient:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.lock = threading.Lock()

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.aiops_username or not self.config.aiops_password:
            raise RuntimeError("AIOPS_BOT_USERNAME and AIOPS_BOT_PASSWORD are required")
        with self.lock:
            return self._post_with_login(path, payload)

    def _post_with_login(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._post(path, payload)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
        self._login()
        return self._post(path, payload)

    def _login(self) -> None:
        self._post(
            "/api/auth/login",
            {"username": self.config.aiops_username, "password": self.config.aiops_password},
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.config.aiops_api_base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=self.config.reply_timeout_seconds) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


class OneBotClient:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.http = JsonHttpClient(timeout=15)

    def send_group_msg(self, group_id: str | int, message: Any, reply_to: Any = None) -> None:
        url = self.config.onebot_api_base + "/send_group_msg"
        if self.config.onebot_access_token and self.config.onebot_token_in_query:
            url += "?" + urllib.parse.urlencode({"access_token": self.config.onebot_access_token})
        headers = {}
        if self.config.onebot_access_token and not self.config.onebot_token_in_query:
            headers["Authorization"] = f"Bearer {self.config.onebot_access_token}"
        outbound_message = message
        if reply_to is not None and isinstance(message, str):
            outbound_message = [
                {"type": "reply", "data": {"id": str(reply_to)}},
                {"type": "text", "data": {"text": message}},
            ]
        payload = {"group_id": int(group_id), "message": outbound_message, "auto_escape": False}
        result = self.http.post_json(url, payload, headers=headers)
        if result.get("status") not in {None, "ok"} and result.get("retcode") not in {0, None}:
            raise RuntimeError(f"OneBot send_group_msg failed: {result}")

    def get_status(self) -> dict[str, Any]:
        url = self.config.onebot_api_base + "/get_status"
        headers = {}
        if self.config.onebot_access_token and self.config.onebot_token_in_query:
            url += "?" + urllib.parse.urlencode({"access_token": self.config.onebot_access_token})
        elif self.config.onebot_access_token:
            headers["Authorization"] = f"Bearer {self.config.onebot_access_token}"
        return self.http.get_json(url, headers=headers)


class NapCatWebUiClient:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.http = JsonHttpClient(timeout=20)

    def login_url(self) -> str:
        base = self.config.napcat_webui_public_url or self.config.napcat_webui_base
        return base.rstrip("/") + "/webui/QQLogin.html"

    def _credential(self) -> str:
        if not self.config.napcat_webui_token:
            return ""
        result = self.http.post_json(
            self.config.napcat_webui_base + "/api/auth/login",
            {"token": self.config.napcat_webui_token},
        )
        if result.get("code") != 0:
            return ""
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return str(data.get("Credential") or "")

    def check_login_status(self) -> dict[str, Any]:
        credential = self._credential()
        if not credential:
            return {"available": False}
        result = self.http.post_json(
            self.config.napcat_webui_base + "/api/QQLogin/CheckLoginStatus",
            {},
            headers={"Authorization": f"Bearer {credential}"},
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {"available": True, "is_login": bool(data.get("isLogin")), "raw": result}

    def get_login_qrcode(self) -> str:
        credential = self._credential()
        if not credential:
            return ""
        result = self.http.post_json(
            self.config.napcat_webui_base + "/api/QQLogin/GetQQLoginQrcode",
            {},
            headers={"Authorization": f"Bearer {credential}"},
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return str(data.get("qrcode") or "")


class OfflineEmailNotifier:
    def __init__(self, config: AdapterConfig):
        self.config = config

    def enabled(self) -> bool:
        return bool(
            self.config.bot_offline_email_enabled
            and self.config.smtp_host
            and self.config.mail_from
            and self.config.mail_to
        )

    def _qrcode_png(self, qrcode_text: str) -> bytes | None:
        if not qrcode_text:
            return None
        try:
            import qrcode  # type: ignore
        except Exception:
            return None
        from io import BytesIO

        buffer = BytesIO()
        image = qrcode.make(qrcode_text)
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def send_offline(self, status: dict[str, Any], qrcode_text: str, login_url: str) -> None:
        if not self.enabled():
            return
        message = EmailMessage()
        message["Subject"] = "AIOps QQ机器人离线告警"
        message["From"] = self.config.mail_from
        message["To"] = ", ".join(self.config.mail_to or [])
        status_text = json.dumps(status, ensure_ascii=False, indent=2)
        body = (
            "QQ机器人 OneBot 状态已离线，请尽快重新登录。\n\n"
            f"登录入口：{login_url}\n"
            f"检测时间：{datetime.now().astimezone().isoformat(timespec='seconds')}\n\n"
            "状态摘要：\n"
            f"{status_text}\n"
        )
        if qrcode_text:
            body += "\n如果邮件客户端不显示附件二维码，可打开登录入口后扫码。"
        else:
            body += "\n本次没有从 NapCat 取到二维码，请打开登录入口扫码。"
        message.set_content(body)
        png = self._qrcode_png(qrcode_text)
        if png:
            message.add_attachment(png, maintype="image", subtype="png", filename="napcat-login-qrcode.png")
        if self.config.smtp_use_tls:
            with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                if self.config.smtp_user:
                    smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                if self.config.smtp_user:
                    smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(message)


class BotStatusMonitor:
    def __init__(self, config: AdapterConfig, onebot: OneBotClient, audit: "AuditLogger"):
        self.config = config
        self.onebot = onebot
        self.audit = audit
        self.napcat = NapCatWebUiClient(config)
        self.notifier = OfflineEmailNotifier(config)
        self.started = False
        self.lock = threading.Lock()
        self.last_online: bool | None = None
        self.last_email_at = 0.0

    def start(self) -> None:
        if not self.config.bot_monitor_enabled:
            return
        with self.lock:
            if self.started:
                return
            self.started = True
            thread = threading.Thread(target=self._run, name="qq-bot-status-monitor", daemon=True)
            thread.start()

    def _run(self) -> None:
        while True:
            try:
                self.check_once()
            except Exception:
                LOGGER.exception("QQ bot status monitor failed")
            time.sleep(self.config.bot_monitor_interval_seconds)

    def check_once(self) -> dict[str, Any]:
        status = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "online": False,
            "good": False,
            "onebot_ok": False,
            "login_url": self.napcat.login_url(),
            "email_enabled": self.notifier.enabled(),
        }
        try:
            onebot_status = self.onebot.get_status()
            data = onebot_status.get("data") if isinstance(onebot_status.get("data"), dict) else {}
            status.update(
                {
                    "onebot_ok": onebot_status.get("status") == "ok" or onebot_status.get("retcode") == 0,
                    "online": bool(data.get("online")),
                    "good": bool(data.get("good")),
                    "onebot": onebot_status,
                }
            )
        except Exception as exc:
            status.update({"error": compact_question(mask_sensitive_text(str(exc)), 300)})
        try:
            status["napcat_login"] = self.napcat.check_login_status()
        except Exception as exc:
            status["napcat_login_error"] = compact_question(mask_sensitive_text(str(exc)), 300)
        self._write_status(status)
        if status.get("online"):
            if self.last_online is False:
                self.audit.write("qq_bot_online_recovered", None, status="online")
            self.last_online = True
            return status
        should_notify = self.last_online is not False or time.time() - self.last_email_at >= self.config.bot_offline_email_cooldown_seconds
        self.last_online = False
        self.audit.write("qq_bot_offline", None, status="offline", error=status.get("error", ""))
        if should_notify:
            self._send_offline_email(status)
        return status

    def _write_status(self, status: dict[str, Any]) -> None:
        if not self.config.bot_status_path:
            return
        directory = os.path.dirname(self.config.bot_status_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.config.bot_status_path, "w", encoding="utf-8") as handle:
            json.dump(status, handle, ensure_ascii=False, indent=2, sort_keys=True)

    def _send_offline_email(self, status: dict[str, Any]) -> None:
        try:
            qrcode_text = ""
            try:
                qrcode_text = self.napcat.get_login_qrcode()
            except Exception as exc:
                status["qrcode_error"] = compact_question(mask_sensitive_text(str(exc)), 300)
            self.notifier.send_offline(status, qrcode_text, self.napcat.login_url())
            self.last_email_at = time.time()
            self.audit.write("qq_bot_offline_email_sent", None, status="sent")
        except Exception as exc:
            self.audit.write("qq_bot_offline_email_failed", None, status="failed", error=exc)
            LOGGER.exception("Failed to send QQ bot offline email")


class RecentMessageCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self.items: dict[str, float] = {}
        self.lock = threading.Lock()

    def seen_or_add(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            expired = [item for item, created_at in self.items.items() if now - created_at > self.ttl_seconds]
            for item in expired:
                self.items.pop(item, None)
            if key in self.items:
                return True
            self.items[key] = now
            return False



class SlidingWindowRateLimiter:
    def __init__(self, window_seconds: int, user_limit: int, group_limit: int):
        self.window_seconds = window_seconds
        self.user_limit = user_limit
        self.group_limit = group_limit
        self.user_hits: dict[str, deque[float]] = {}
        self.group_hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def _allow(self, bucket: dict[str, deque[float]], key: str, limit: int, now: float) -> bool:
        hits = bucket.setdefault(key, deque())
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def allow(self, group_id: str, user_id: str) -> tuple[bool, str]:
        now = time.time()
        with self.lock:
            if not self._allow(self.group_hits, group_id, self.group_limit, now):
                return False, "group_rate_limited"
            if not self._allow(self.user_hits, f"{group_id}:{user_id}", self.user_limit, now):
                group_hits = self.group_hits.get(group_id)
                if group_hits:
                    group_hits.pop()
                return False, "user_rate_limited"
        return True, "ok"


class GroupSemaphorePool:
    def __init__(self, limit: int):
        self.limit = limit
        self.items: dict[str, threading.BoundedSemaphore] = {}
        self.lock = threading.Lock()

    def get(self, group_id: str) -> threading.BoundedSemaphore:
        with self.lock:
            item = self.items.get(group_id)
            if item is None:
                item = threading.BoundedSemaphore(self.limit)
                self.items[group_id] = item
            return item


class AuditLogger:
    def __init__(self, path: str, question_chars: int, answer_preview_chars: int):
        self.path = path
        self.question_chars = question_chars
        self.answer_preview_chars = answer_preview_chars
        self.lock = threading.Lock()

    def write(self, event_name: str, event: dict[str, Any] | None = None, **fields: Any) -> None:
        if not self.path:
            return
        source = event or {}
        sender = source.get("sender") if isinstance(source.get("sender"), dict) else {}
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event_name,
            "group_id": str(source.get("group_id") or fields.pop("group_id", "")),
            "user_id": str(source.get("user_id") or fields.pop("user_id", "")),
            "message_id": str(source.get("message_id") or fields.pop("message_id", "")),
            "self_id": str(source.get("self_id") or fields.pop("self_id", "")),
            "sender_nickname": str(sender.get("nickname") or ""),
            "sender_card": str(sender.get("card") or ""),
        }
        record.update(fields)
        question = record.get("question")
        if question is not None:
            record["question"] = compact_question(mask_sensitive_text(str(question)), self.question_chars)
        answer_preview = record.get("answer_preview")
        if answer_preview is not None:
            record["answer_preview"] = compact_question(mask_sensitive_text(str(answer_preview)), self.answer_preview_chars)
        error = record.get("error")
        if error is not None:
            record["error"] = compact_question(mask_sensitive_text(str(error)), 500)
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            with self.lock:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            LOGGER.exception("Failed to write QQ audit log")

@dataclass(frozen=True)
class QueueItem:
    event: dict[str, Any]
    question: str


class WorkDispatcher:
    def __init__(self, config: AdapterConfig, onebot: OneBotClient, aiops: AiopsSessionClient, sessions: "ConversationSessionStore", audit: AuditLogger):
        self.config = config
        self.onebot = onebot
        self.aiops = aiops
        self.sessions = sessions
        self.audit = audit
        self.queue: queue.Queue[QueueItem] = queue.Queue(maxsize=config.queue_size)
        self.group_semaphores = GroupSemaphorePool(config.group_concurrency)
        self.started = False
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
            for index in range(self.config.global_concurrency):
                thread = threading.Thread(target=self._worker, name=f"qq-adapter-worker-{index + 1}", daemon=True)
                thread.start()

    def submit(self, item: QueueItem) -> bool:
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def _worker(self) -> None:
        while True:
            item = self.queue.get()
            group_id = str(item.event.get("group_id") or "")
            semaphore = self.group_semaphores.get(group_id)
            semaphore.acquire()
            try:
                process_group_message(item.event, self.config, self.onebot, self.aiops, self.sessions, item.question, self.audit)
            finally:
                semaphore.release()
                self.queue.task_done()


class ConversationSessionStore:
    def __init__(self, ttl_seconds: int = 6 * 3600):
        self.ttl_seconds = ttl_seconds
        self.items: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()

    def get(self, key: str) -> int | None:
        now = time.time()
        with self.lock:
            value = self.items.get(key)
            if not value:
                return None
            session_id, updated_at = value
            if now - updated_at > self.ttl_seconds:
                self.items.pop(key, None)
                return None
            return session_id

    def set(self, key: str, session_id: Any) -> None:
        try:
            parsed = int(session_id)
        except (TypeError, ValueError):
            return
        with self.lock:
            self.items[key] = (parsed, time.time())


CQ_AT_RE = re.compile(r"\[CQ:at,qq=([^\],]+)[^\]]*\]")
CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]")


def strip_cq_codes(text: str) -> str:
    return CQ_CODE_RE.sub("", text or "").strip()


def text_from_message_segments(message: Any, config: AdapterConfig, event_self_id: Any = None) -> tuple[bool, str]:
    if not isinstance(message, list):
        return False, ""
    self_id = config.bot_self_id or str(event_self_id or "").strip()
    mentioned = False
    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type") or "")
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        if segment_type == "at":
            qq = str(data.get("qq") or "").strip()
            if self_id and qq == self_id:
                mentioned = True
            continue
        if segment_type == "text":
            parts.append(str(data.get("text") or ""))
    return mentioned, "".join(parts).strip()


def extract_question(raw_message: str, config: AdapterConfig, event_self_id: Any = None, message: Any = None) -> tuple[bool, str]:
    segment_mentioned, segment_text = text_from_message_segments(message, config, event_self_id)
    if segment_mentioned and segment_text:
        return True, segment_text

    text = str(raw_message or "").strip()
    if not text:
        return False, ""

    self_id = config.bot_self_id or str(event_self_id or "").strip()
    mentioned = False

    def replace_at(match: re.Match[str]) -> str:
        nonlocal mentioned
        qq = match.group(1)
        if self_id and qq == self_id:
            mentioned = True
        return ""

    without_at = CQ_AT_RE.sub(replace_at, text).strip()
    plain = strip_cq_codes(without_at)

    for prefix in config.trigger_prefixes:
        if plain.lower().startswith(prefix.lower()):
            return True, plain[len(prefix) :].strip()

    if mentioned or segment_mentioned:
        return True, plain.strip()

    return False, ""


def is_event_authorized(config: AdapterConfig) -> bool:
    if not config.event_token:
        return True
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {config.event_token}":
        return True
    if request.headers.get("X-OneBot-Access-Token") == config.event_token:
        return True
    if request.args.get("token") == config.event_token:
        return True
    return False


def split_reply(text: str, max_chars: int) -> list[str]:
    clean = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if len(clean) <= max_chars:
        return [clean] if clean else []
    chunks: list[str] = []
    current = ""
    for part in re.split(r"(\n\n|\n)", clean):
        if len(current) + len(part) <= max_chars:
            current += part
            continue
        if current.strip():
            chunks.append(current.strip())
        current = part
        while len(current) > max_chars:
            chunks.append(current[:max_chars].strip())
            current = current[max_chars:]
    if current.strip():
        chunks.append(current.strip())
    return chunks[:4]



SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{12,}", re.I),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}", re.I),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|token|secret|password|passwd)(\s*[:=]\s*)([^\s,;]{6,})"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{40,}(?![A-Za-z0-9])"),
]


def compact_question(question: str, max_chars: int = 120) -> str:
    text = " ".join(str(question or "").split())
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


def mask_sensitive_text(text: str) -> str:
    clean = str(text or "")
    clean = SECRET_PATTERNS[0].sub("Bearer [REDACTED]", clean)
    clean = SECRET_PATTERNS[1].sub("sk-[REDACTED]", clean)
    clean = SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", clean)
    clean = SECRET_PATTERNS[3].sub("[REDACTED]", clean)
    return clean


def safe_reply_text(text: str, max_chars: int) -> str:
    clean = mask_sensitive_text(text)
    if len(clean) > max_chars:
        return clean[:max_chars].rstrip() + "\n\n[TRUNCATED]"
    return clean


def limit_question(question: str, max_chars: int) -> str:
    text = " ".join(str(question or "").split())
    return text[:max_chars]


def build_session_id(group_id: str, user_id: str) -> str:
    return f"qq-group:{group_id}:user:{user_id}"


def process_group_message(
    event: dict[str, Any],
    config: AdapterConfig,
    onebot: OneBotClient,
    aiops: AiopsSessionClient,
    sessions: ConversationSessionStore,
    question: str | None = None,
    audit: AuditLogger | None = None,
) -> None:
    group_id = str(event.get("group_id") or "")
    user_id = str(event.get("user_id") or "")
    reply_to = event.get("message_id")
    if question is None:
        raw_message = str(event.get("raw_message") or event.get("message") or "")
        triggered, question = extract_question(raw_message, config, event.get("self_id"), event.get("message"))
        if not triggered or not question:
            return
        question = limit_question(question, config.max_question_chars)

    started = time.time()
    if audit:
        audit.write("processing_started", event, question=question)

    try:
        onebot.send_group_msg(group_id, "已接收，正在AI分析中", reply_to=reply_to)
        conversation_key = build_session_id(group_id, user_id)
        payload: dict[str, Any] = {"message": question, "limit": 8}
        session_id = sessions.get(conversation_key)
        if session_id:
            payload["session_id"] = session_id
        result = aiops.post_json(
            "/api/fault-kb/chat",
            payload,
        )
        sessions.set(conversation_key, result.get("session_id"))
        answer = str(result.get("answer") or "").strip()
        if not answer:
            answer = "No valid answer was returned. Please try again later."
        answer = safe_reply_text(answer, config.max_reply_chars * 4)
        chunks = split_reply(answer, config.max_reply_chars)
        for index, chunk in enumerate(chunks):
            onebot.send_group_msg(group_id, safe_reply_text(chunk, config.max_reply_chars), reply_to=reply_to if index == 0 else None)
        if audit:
            audit.write(
                "processing_completed",
                event,
                question=question,
                status="success",
                duration_ms=int((time.time() - started) * 1000),
                answer_chars=len(answer),
                reply_chunks=len(chunks),
                answer_preview=answer,
                session_id=result.get("session_id"),
            )
    except Exception as exc:
        LOGGER.exception("Failed to process QQ group message")
        if audit:
            audit.write(
                "processing_failed",
                event,
                question=question,
                status="failed",
                duration_ms=int((time.time() - started) * 1000),
                error=exc,
            )
        try:
            onebot.send_group_msg(group_id, f"Query failed: {exc}", reply_to=reply_to)
        except Exception:
            LOGGER.exception("Failed to send QQ error reply")


def should_accept_event(event: dict[str, Any], config: AdapterConfig) -> tuple[bool, str]:
    if event.get("post_type") != "message" or event.get("message_type") != "group":
        return False, "not_group_message"
    group_id = str(event.get("group_id") or "")
    if not group_id:
        return False, "missing_group_id"
    if not config.allowed_groups:
        return False, "empty_group_allowlist"
    if group_id not in config.allowed_groups:
        return False, "group_not_allowed"
    self_id = str(event.get("self_id") or config.bot_self_id or "")
    if self_id and str(event.get("user_id") or "") == self_id:
        return False, "self_message"
    triggered, question = extract_question(str(event.get("raw_message") or event.get("message") or ""), config, event.get("self_id"), event.get("message"))
    if not triggered or not question:
        return False, "not_triggered"
    return True, "accepted"


def create_adapter_app(config: AdapterConfig | None = None) -> Flask:
    load_runtime_env()
    config = config or AdapterConfig.from_env()
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    onebot = OneBotClient(config)
    aiops = AiopsSessionClient(config)
    recent = RecentMessageCache()
    sessions = ConversationSessionStore()
    rate_limiter = SlidingWindowRateLimiter(config.rate_window_seconds, config.user_rate_limit, config.group_rate_limit)
    audit = AuditLogger(config.audit_log_path, config.audit_question_chars, config.audit_answer_preview_chars)
    dispatcher = WorkDispatcher(config, onebot, aiops, sessions, audit)
    monitor = BotStatusMonitor(config, onebot, audit)
    dispatcher.start()
    monitor.start()

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "aiops-qq-adapter"})

    @app.get("/bot/status")
    def bot_status():
        return jsonify(monitor.check_once())

    @app.post("/onebot/event")
    def onebot_event():
        if not is_event_authorized(config):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        event = request.get_json(silent=True) or {}
        if not isinstance(event, dict):
            return jsonify({"ok": False, "error": "invalid_json"}), 400
        accepted, reason = should_accept_event(event, config)
        if not accepted:
            audit.write("message_ignored", event, reason=reason)
            return jsonify({"ok": True, "ignored": reason})
        key = str(event.get("message_id") or f"{event.get('group_id')}:{event.get('user_id')}:{event.get('time')}:{event.get('raw_message')}")
        if recent.seen_or_add(key):
            audit.write("message_ignored", event, reason="duplicate")
            return jsonify({"ok": True, "ignored": "duplicate"})
        _, question = extract_question(str(event.get("raw_message") or event.get("message") or ""), config, event.get("self_id"), event.get("message"))
        question = limit_question(question, config.max_question_chars)
        group_id = str(event.get("group_id") or "")
        user_id = str(event.get("user_id") or "")
        allowed, limit_reason = rate_limiter.allow(group_id, user_id)
        if not allowed:
            audit.write("message_rejected", event, question=question, reason=limit_reason)
            message = "Rate limited. Please try again later. Limits: per user 3/min, per group 5/min."
            try:
                onebot.send_group_msg(group_id, message, reply_to=event.get("message_id"))
            except Exception:
                LOGGER.exception("Failed to send rate-limit reply")
            return jsonify({"ok": True, "ignored": limit_reason})
        if not dispatcher.submit(QueueItem(event=event, question=question)):
            audit.write("message_rejected", event, question=question, reason="queue_full")
            message = "Queue is full. Please try again later."
            try:
                onebot.send_group_msg(group_id, message, reply_to=event.get("message_id"))
            except Exception:
                LOGGER.exception("Failed to send queue-full reply")
            return jsonify({"ok": True, "ignored": "queue_full"})
        audit.write("message_queued", event, question=question, queue_size=dispatcher.queue.qsize())
        return jsonify({"ok": True, "status": "queued"})

    return app
