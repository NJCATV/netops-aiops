"""Lookup MIB OID mappings from MySQL with a small in-process cache."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

try:
    from sqlalchemy import select
except Exception:  # pragma: no cover
    select = None  # type: ignore

from app.db import create_db_engine
from app.models import MibOidMapping


def normalize_oid(value: object) -> str:
    text = str(value or "").strip()
    return text[1:] if text.startswith(".") else text


@dataclass
class MibLookupStats:
    available: bool = False
    requested: int = 0
    hits: int = 0
    misses: int = 0
    error: Optional[str] = None


@dataclass
class MibLookupService:
    enabled: bool = True
    cache: Dict[str, Optional[dict]] = field(default_factory=dict)
    stats: MibLookupStats = field(default_factory=MibLookupStats)

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

    def lookup_oid(self, oid: object) -> Optional[dict]:
        normalized = normalize_oid(oid)
        if not normalized:
            return None
        self.stats.requested += 1
        if normalized in self.cache:
            cached = self.cache[normalized]
            if cached:
                self.stats.hits += 1
            else:
                self.stats.misses += 1
            return cached
        if not self.enabled:
            self.stats.misses += 1
            self.cache[normalized] = None
            return None
        try:
            stmt = (
                select(
                    MibOidMapping.oid,
                    MibOidMapping.name,
                    MibOidMapping.module,
                    MibOidMapping.object_type,
                    MibOidMapping.description_short,
                    MibOidMapping.is_notification,
                )
                .where(MibOidMapping.oid == normalized)
                .limit(1)
            )
            with self.engine.connect() as conn:
                row = conn.execute(stmt).mappings().first()
        except Exception as exc:  # pragma: no cover
            self.stats.error = str(exc)
            self.stats.available = False
            self.stats.misses += 1
            self.cache[normalized] = None
            return None
        if not row:
            self.stats.misses += 1
            self.cache[normalized] = None
            return None
        result = {
            "oid": row["oid"],
            "name": row["name"],
            "module": row["module"],
            "object_type": row["object_type"],
            "description_short": row["description_short"],
            "is_notification": bool(row["is_notification"]),
        }
        self.stats.hits += 1
        self.cache[normalized] = result
        return result

    def lookup_many(self, oids: Iterable[object]) -> Dict[str, dict]:
        result = {}
        for oid in oids:
            normalized = normalize_oid(oid)
            item = self.lookup_oid(normalized)
            if item:
                result[normalized] = item
        return result

    def metrics(self) -> dict:
        return {
            "available": self.stats.available,
            "requested": self.stats.requested,
            "hits": self.stats.hits,
            "misses": self.stats.misses,
            "error": self.stats.error,
        }
