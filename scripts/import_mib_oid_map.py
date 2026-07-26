#!/usr/bin/env python3
"""Import expanded MIB OID descriptions into MySQL."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
from typing import Dict, Iterable, List, Optional

from dotenv import load_dotenv
from sqlalchemy.dialects.mysql import insert as mysql_insert

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base, create_db_engine  # noqa: E402
from app.models import MibOidMapping  # noqa: E402


OID_RE = re.compile(r"^\.(?:\d+\.)*\d+$")
HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s+([A-Z][A-Z0-9-]+)")


def load_env(path: Optional[str]) -> None:
    if path:
        load_dotenv(path, override=True)
        return
    for candidate in (ROOT / ".env", ROOT / "deploy" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_quotes(value: str) -> str:
    text = clean_text(value)
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.strip()


def shorten(value: str, limit: int) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def parse_description(lines: List[str], start: int) -> str:
    first = lines[start].split("DESCRIPTION", 1)[1].strip()
    parts = [first]
    quote_count = first.count('"')
    index = start + 1
    while index < len(lines) and quote_count % 2 == 1:
        line = lines[index].strip()
        parts.append(line)
        quote_count += line.count('"')
        index += 1
    return strip_quotes(" ".join(parts))


def parse_mib_file(path: pathlib.Path, description_limit: int) -> Iterable[Dict[str, object]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not OID_RE.match(line):
            index += 1
            continue

        oid = line[1:]
        source_line = index + 1
        header_index = index + 1
        while header_index < len(lines) and not lines[header_index].strip():
            header_index += 1
        if header_index >= len(lines):
            break

        header = lines[header_index].strip()
        match = HEADER_RE.match(header)
        if not match:
            index = header_index + 1
            continue

        name, object_type = match.group(1), match.group(2)
        module = None
        syntax = None
        max_access = None
        status = None
        description = ""

        block_index = header_index + 1
        while block_index < len(lines):
            item = lines[block_index].strip()
            if OID_RE.match(item):
                break
            if item.startswith("-- FROM"):
                module = clean_text(item.split("FROM", 1)[1])
            elif item.startswith("SYNTAX"):
                syntax = clean_text(item.split("SYNTAX", 1)[1])
            elif item.startswith("MAX-ACCESS"):
                max_access = clean_text(item.split("MAX-ACCESS", 1)[1])
            elif item.startswith("ACCESS") and not max_access:
                max_access = clean_text(item.split("ACCESS", 1)[1])
            elif item.startswith("STATUS"):
                status = clean_text(item.split("STATUS", 1)[1])
            elif item.startswith("DESCRIPTION"):
                description = parse_description(lines, block_index)
            block_index += 1

        yield {
            "oid": oid,
            "name": name,
            "module": module,
            "object_type": object_type,
            "syntax": shorten(syntax or "", 255) or None,
            "max_access": max_access,
            "status": status,
            "description_short": shorten(description, description_limit) or None,
            "source_file": str(path.name),
            "source_line": source_line,
            "is_notification": object_type == "NOTIFICATION-TYPE",
        }
        index = block_index


def upsert_rows(engine, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    now = dt.datetime.now(dt.timezone.utc)
    payload = []
    for row in rows:
        item = dict(row)
        item["created_at"] = now
        item["updated_at"] = now
        payload.append(item)
    stmt = mysql_insert(MibOidMapping.__table__).values(payload)
    update_columns = {
        "name": stmt.inserted.name,
        "module": stmt.inserted.module,
        "object_type": stmt.inserted.object_type,
        "syntax": stmt.inserted.syntax,
        "max_access": stmt.inserted.max_access,
        "status": stmt.inserted.status,
        "description_short": stmt.inserted.description_short,
        "source_file": stmt.inserted.source_file,
        "source_line": stmt.inserted.source_line,
        "is_notification": stmt.inserted.is_notification,
        "updated_at": now,
    }
    with engine.begin() as conn:
        conn.execute(stmt.on_duplicate_key_update(**update_columns))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Expanded MIB text file")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--description-limit", type=int, default=240)
    args = parser.parse_args()

    load_env(args.env_file)
    input_path = pathlib.Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))

    engine = create_db_engine()
    Base.metadata.create_all(engine)

    total = 0
    notifications = 0
    batch: List[Dict[str, object]] = []
    for row in parse_mib_file(input_path, args.description_limit):
        batch.append(row)
        total += 1
        notifications += 1 if row.get("is_notification") else 0
        if len(batch) >= args.batch_size:
            upsert_rows(engine, batch)
            batch.clear()
    upsert_rows(engine, batch)

    print(json.dumps({"input": str(input_path), "imported_or_updated": total, "notifications": notifications}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
