"""Lookup private NMS Trap alarm definitions from MySQL."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

try:
    from sqlalchemy import select
except Exception:  # pragma: no cover
    select = None  # type: ignore

from app.db import create_db_engine
from app.models import TrapAlarmDefinition, TrapAlarmOidAlias
from aiops.mib.lookup import normalize_oid


RECOVERED_KEYWORDS = ("恢复", "clear", "up", "resume", "recovered")
ACTIVE_KEYWORDS = ("告警", "down", "failure", "error", "err", "occur", "fault")


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\t", " ").split())


def truncate_text(value: Any, limit: int = 240) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def infer_lifecycle_status(fault_type: Any = None, fault_name: Any = None) -> str:
    fault_type_text = clean_text(fault_type)
    if fault_type_text == "0":
        return "active"
    if fault_type_text == "1":
        return "recovered"
    name = clean_text(fault_name).lower()
    if any(keyword.lower() in name for keyword in RECOVERED_KEYWORDS):
        return "recovered"
    if any(keyword.lower() in name for keyword in ACTIVE_KEYWORDS):
        return "active"
    return "unknown"


@dataclass
class TrapAlarmLookupStats:
    available: bool = False
    requested: int = 0
    hits: int = 0
    misses: int = 0
    error: Optional[str] = None


@dataclass
class TrapAlarmDefinitionLookupService:
    enabled: bool = True
    cache: Dict[str, Optional[dict]] = field(default_factory=dict)
    stats: TrapAlarmLookupStats = field(default_factory=TrapAlarmLookupStats)

    def __post_init__(self) -> None:
        self.enabled = self.enabled and os.getenv("MYSQL_PASSWORD", "") != "" and select is not None
        self.stats.available = self.enabled
        self._engine = None

    @property
    def engine(self):
        if not self.enabled:
            return None
        if self._engine is None:
            self._engine = create_db_engine()
        return self._engine

    def lookup_trap_alarm_definition(self, trap_oid: Any) -> Optional[dict]:
        oid = normalize_oid(trap_oid)
        if not oid:
            return None
        self.stats.requested += 1
        if oid in self.cache:
            cached = self.cache[oid]
            if cached:
                self.stats.hits += 1
            else:
                self.stats.misses += 1
            return cached
        if not self.enabled:
            self.stats.misses += 1
            self.cache[oid] = None
            return None
        try:
            stmt = (
                select(
                    TrapAlarmOidAlias.oid,
                    TrapAlarmOidAlias.oid_type,
                    TrapAlarmDefinition.vendor,
                    TrapAlarmDefinition.enterprise_id,
                    TrapAlarmDefinition.enterprise_name,
                    TrapAlarmDefinition.fault_name,
                    TrapAlarmDefinition.severity,
                    TrapAlarmDefinition.custom_severity,
                    TrapAlarmDefinition.fault_type,
                    TrapAlarmDefinition.lifecycle_status,
                    TrapAlarmDefinition.fault_reason,
                    TrapAlarmDefinition.suggestion,
                    TrapAlarmDefinition.desc_info,
                )
                .join(TrapAlarmDefinition, TrapAlarmDefinition.id == TrapAlarmOidAlias.definition_id)
                .where(TrapAlarmOidAlias.oid == oid)
                .limit(1)
            )
            with self.engine.connect() as conn:
                row = conn.execute(stmt).mappings().first()
        except Exception as exc:  # pragma: no cover
            self.stats.error = str(exc)
            self.stats.available = False
            self.stats.misses += 1
            self.cache[oid] = None
            return None
        if not row:
            self.stats.misses += 1
            self.cache[oid] = None
            return None
        lifecycle = row["lifecycle_status"] or infer_lifecycle_status(row["fault_type"], row["fault_name"])
        result = {
            "alarm_matched_oid": row["oid"],
            "alarm_oid_type": row["oid_type"],
            "alarm_name": row["fault_name"],
            "alarm_severity": row["custom_severity"] or row["severity"],
            "alarm_lifecycle_status": lifecycle,
            "alarm_vendor": row["vendor"],
            "alarm_enterprise_id": row["enterprise_id"],
            "alarm_enterprise_name": row["enterprise_name"],
            "alarm_fault_reason": truncate_text(row["fault_reason"], 240),
            "alarm_suggestion": truncate_text(row["suggestion"], 240),
            "alarm_desc_info": truncate_text(row["desc_info"], 240),
            "alarm_definition_matched": True,
            "alarm_lookup_source": "mysql",
        }
        self.stats.hits += 1
        self.cache[oid] = result
        return result

    def enrich_trap_alarm_definition(self, trap_doc: dict) -> dict:
        row = dict(trap_doc)
        if row.get("alarm_definition_matched") and row.get("alarm_name"):
            row.setdefault("alarm_lookup_source", "elasticsearch")
            return row
        mapping = self.lookup_trap_alarm_definition(row.get("trap_oid"))
        if mapping:
            row.update(mapping)
        else:
            row.setdefault("alarm_definition_matched", False)
            row.setdefault("alarm_lookup_source", "miss")
        return row

    def metrics(self) -> dict:
        return {
            "alarm_lookup_available": self.stats.available,
            "alarm_lookup_requested": self.stats.requested,
            "alarm_lookup_hits": self.stats.hits,
            "alarm_lookup_misses": self.stats.misses,
            "alarm_lookup_error": self.stats.error,
        }


def lookup_trap_alarm_definition(trap_oid: Any) -> Optional[dict]:
    return TrapAlarmDefinitionLookupService().lookup_trap_alarm_definition(trap_oid)


def enrich_trap_alarm_definition(trap_doc: dict) -> dict:
    return TrapAlarmDefinitionLookupService().enrich_trap_alarm_definition(trap_doc)
