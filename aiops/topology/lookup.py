"""Small MySQL topology lookup service."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

try:
    import pymysql
except ImportError:  # pragma: no cover
    pymysql = None


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\t", " ").split())


def normalize_device_name(name: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean_text(name).upper())


def normalize_interface_name(name: Any) -> str:
    text = clean_text(name).upper()
    text = text.replace("ROUTE-AGGREGATION", "RAGG").replace("ROUTEAGGREGATION", "RAGG")
    return re.sub(r"[\s_/-]+", "", text)


def normalize_link_name(name: Any) -> str:
    text = re.sub(r"\bIPV[46]\b", "", clean_text(name).upper())
    return re.sub(r"[^A-Z0-9]", "", text)


def compact_device(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    return {
        "device_name": clean_text(row.get("device_name")),
        "ip_address": clean_text(row.get("ip_address")),
        "status": clean_text(row.get("status")),
        "role": clean_text(row.get("role")),
        "hierarchy": clean_text(row.get("hierarchy")),
        "model": clean_text(row.get("model")),
        "manufacturer": clean_text(row.get("manufacturer")),
        "software_version": clean_text(row.get("software_version")),
    }


def compact_link(row: Optional[dict], match_source: str = "") -> Optional[dict]:
    if not row:
        return None
    result = {
        "link_id": row.get("link_id"),
        "link_name": clean_text(row.get("link_name")),
        "link_state": clean_text(row.get("link_state")),
        "source_device": clean_text(row.get("source_device")),
        "source_interface": clean_text(row.get("source_interface")),
        "source_ip": clean_text(row.get("source_ip")),
        "target_device": clean_text(row.get("target_device")),
        "target_interface": clean_text(row.get("target_interface")),
        "target_ip": clean_text(row.get("target_ip")),
        "update_time": str(row.get("update_time") or ""),
    }
    if match_source:
        result["match_source"] = match_source
    return result


@dataclass
class TopologyLookupService:
    enabled: bool = True
    requested: int = 0
    link_hits: int = 0
    link_misses: int = 0
    device_hits: int = 0
    device_misses: int = 0
    error: Optional[str] = None

    def __post_init__(self) -> None:
        self.enabled = self.enabled and pymysql is not None and os.getenv("MYSQL_PASSWORD", "") != ""
        self._devices: Optional[List[dict]] = None
        self._links: Optional[List[dict]] = None

    def _connect(self):
        if not self.enabled:
            return None
        return pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "13306")),
            user=os.getenv("MYSQL_USER", "aiops"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "jscn_aiops"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=20,
        )

    def _load_devices(self) -> List[dict]:
        if self._devices is not None:
            return self._devices
        conn = self._connect()
        if conn is None:
            self._devices = []
            return self._devices
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, device_name, ip_address, status, role, hierarchy,
                           model, manufacturer, software_version
                    FROM networkDevice
                    """
                )
                self._devices = list(cursor.fetchall())
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            self.enabled = False
            self._devices = []
        finally:
            conn.close()
        return self._devices

    def _load_links(self) -> List[dict]:
        if self._links is not None:
            return self._links
        conn = self._connect()
        if conn is None:
            self._links = []
            return self._links
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT link_id, link_name, link_state, source_device, source_interface,
                           source_ip, target_device, target_interface, target_ip, update_time
                    FROM networkLinks
                    """
                )
                self._links = list(cursor.fetchall())
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            self.enabled = False
            self._links = []
        finally:
            conn.close()
        return self._links

    def lookup_device_by_name(self, device_name: Any) -> Optional[dict]:
        self.requested += 1
        name = clean_text(device_name)
        normalized = normalize_device_name(name)
        if not normalized:
            self.device_misses += 1
            return None
        for row in self._load_devices():
            if clean_text(row.get("device_name")) == name or normalize_device_name(row.get("device_name")) == normalized:
                self.device_hits += 1
                return compact_device(row)
        self.device_misses += 1
        return None

    def lookup_link_by_name(self, link_name: Any) -> Optional[dict]:
        self.requested += 1
        name = clean_text(link_name)
        normalized = normalize_link_name(name)
        if not normalized:
            self.link_misses += 1
            return None
        for row in self._load_links():
            if clean_text(row.get("link_name")) == name:
                self.link_hits += 1
                return compact_link(row, "link_name_exact")
        for row in self._load_links():
            if normalize_link_name(row.get("link_name")) == normalized:
                self.link_hits += 1
                return compact_link(row, "link_name_normalized")
        self.link_misses += 1
        return None

    def lookup_link_by_endpoints(
        self,
        source_device: Any,
        target_device: Any,
        source_interface: Any = None,
        target_interface: Any = None,
    ) -> Optional[dict]:
        self.requested += 1
        src = normalize_device_name(source_device)
        dst = normalize_device_name(target_device)
        if not src or not dst:
            self.link_misses += 1
            return None
        src_if = normalize_interface_name(source_interface)
        dst_if = normalize_interface_name(target_interface)
        matches: List[Tuple[int, dict]] = []
        for row in self._load_links():
            row_src = normalize_device_name(row.get("source_device"))
            row_dst = normalize_device_name(row.get("target_device"))
            forward = row_src == src and row_dst == dst
            reverse = row_src == dst and row_dst == src
            if not forward and not reverse:
                continue
            score = 10
            row_src_if = normalize_interface_name(row.get("source_interface"))
            row_dst_if = normalize_interface_name(row.get("target_interface"))
            if forward and src_if and row_src_if == src_if:
                score += 5
            if forward and dst_if and row_dst_if == dst_if:
                score += 5
            if reverse and src_if and row_dst_if == src_if:
                score += 5
            if reverse and dst_if and row_src_if == dst_if:
                score += 5
            matches.append((score, row))
        if not matches:
            self.link_misses += 1
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        self.link_hits += 1
        return compact_link(matches[0][1], "endpoints_interfaces" if matches[0][0] > 10 else "endpoints")

    def metrics(self) -> dict:
        return {
            "topology_lookup_available": self.enabled,
            "topology_lookup_requested": self.requested,
            "topology_lookup_error": self.error,
            "topology_link_hits": self.link_hits,
            "topology_link_misses": self.link_misses,
            "topology_device_hits": self.device_hits,
            "topology_device_misses": self.device_misses,
        }


_DEFAULT_SERVICE: Optional[TopologyLookupService] = None


def default_service() -> TopologyLookupService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = TopologyLookupService()
    return _DEFAULT_SERVICE


def lookup_device_by_name(device_name: Any) -> Optional[dict]:
    return default_service().lookup_device_by_name(device_name)


def lookup_link_by_name(link_name: Any) -> Optional[dict]:
    return default_service().lookup_link_by_name(link_name)


def lookup_link_by_endpoints(source_device: Any, target_device: Any, source_interface: Any = None, target_interface: Any = None) -> Optional[dict]:
    return default_service().lookup_link_by_endpoints(source_device, target_device, source_interface, target_interface)
