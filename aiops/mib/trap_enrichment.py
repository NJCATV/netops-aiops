"""Enrich compact Trap dictionaries with MIB and managed-device identity."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from aiops.mib.lookup import MibLookupService
from aiops.topology.lookup import TopologyLookupService, normalize_link_name
from aiops.trap.alarm_definition_lookup import TrapAlarmDefinitionLookupService

try:
    import pymysql
except ImportError:  # pragma: no cover - optional runtime enhancement
    pymysql = None


DEVICE_NAME_OID_SUFFIX = "25506.4.2.2.1.102"
DEVICE_IP_OID_SUFFIX = "25506.4.2.2.1.103"
LINK_DESCRIPTION_OID_SUFFIX = "25506.4.2.59.1.2"
INVALID_AGENT_ADDR_VALUES = {"255.255.255.255", "0.0.0.0", "\\xFF\\xFF\\xFF\\xFF", "\\xff\\xff\\xff\\xff"}


def has_translated_fields(trap: dict) -> bool:
    return bool(trap.get("trap_oid_name") or trap.get("trap_oid_module") or trap.get("mib_translated"))


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\t", " ").split())


def nested_get(row: dict, path: Iterable[str]) -> Any:
    current: Any = row
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_present(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text and not text.startswith("%{"):
            return text
    return ""


def normalize_ip(value: Any) -> str:
    text = clean_text(value).strip('"')
    if not text or text in INVALID_AGENT_ADDR_VALUES:
        return ""
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return ""
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast:
        return ""
    if ip.version == 4 and int(ip) == 0xFFFFFFFF:
        return ""
    return str(ip)


def extract_agent_addr_from_raw(raw_message: Any) -> str:
    raw = str(raw_message or "")
    match = re.search(r"@agent_addr=.*?@value=\\?\"([^\"<>]+)\\?\"", raw)
    if not match:
        return ""
    value = match.group(1)
    if "\\x" in value:
        bytes_hex = re.findall(r"\\x([0-9A-Fa-f]{2})", value)
        if len(bytes_hex) == 4:
            return ".".join(str(int(item, 16)) for item in bytes_hex)
        return ""
    return value


def find_varbind_value(varbinds: Any, suffix: str) -> str:
    if not isinstance(varbinds, dict):
        return ""
    for key, value in varbinds.items():
        normalized_key = str(key)
        if normalized_key.endswith(suffix):
            return clean_text(value)
    return ""


def looks_like_link_object(value: Any) -> bool:
    text = clean_text(value)
    return bool(re.search(r"\bTo\b", text, re.IGNORECASE) and (re.search(r"\bLink\d*\b", text, re.IGNORECASE) or ":" in text))


def parse_link_description(value: Any) -> dict:
    text = clean_text(value)
    if not text:
        return {}
    object_name = text
    interface_text = ""
    if ":" in text and " To " in text:
        object_name, interface_text = text.split(":", 1)
        object_name = clean_text(object_name)
        interface_text = clean_text(interface_text)
    endpoint_devices: List[str] = []
    endpoint_interfaces: List[str] = []
    device_match = re.match(r"(.+?)\s+To\s+(.+?)(?:\s+Link\d+\b.*|\s+IPv[46]\b.*|$)", object_name, re.IGNORECASE)
    if device_match:
        endpoint_devices = [clean_text(device_match.group(1)), clean_text(device_match.group(2))]
    if interface_text:
        iface_match = re.match(r"(.+?)\s+To\s+(.+)$", interface_text, re.IGNORECASE)
        if iface_match:
            endpoint_interfaces = [clean_text(iface_match.group(1)), clean_text(iface_match.group(2))]
    return {
        "managed_object_name": object_name,
        "endpoint_device_names": [item for item in endpoint_devices if item],
        "endpoint_interfaces": [item for item in endpoint_interfaces if item],
        "topology_object_key": normalize_link_name(object_name) or None,
    }


def extract_managed_object(row: dict) -> dict:
    varbinds = nested_get(row, ["trap", "varbinds"])
    object_name = first_present(
        row.get("managed_object_name"),
        find_varbind_value(varbinds, LINK_DESCRIPTION_OID_SUFFIX),
        find_varbind_value(varbinds, DEVICE_NAME_OID_SUFFIX),
    )
    object_address = first_present(row.get("managed_object_address"), find_varbind_value(varbinds, DEVICE_IP_OID_SUFFIX))
    raw_message = clean_text(row.get("raw_message"))
    if not object_name and raw_message:
        match = re.search(
            r"([A-Za-z0-9_.:-]+(?:-[A-Za-z0-9_.:-]+)*\s+To\s+[A-Za-z0-9_.:-]+(?:-[A-Za-z0-9_.:-]+)*(?:\s+Link\d+\s+IPv[46])?(?::[^,;]+?\s+To\s+[^,;]+)?)",
            raw_message,
            re.IGNORECASE,
        )
        if match:
            object_name = clean_text(match.group(1))
    parsed = parse_link_description(object_name)
    result = {
        "managed_object_name": parsed.get("managed_object_name") or object_name or None,
        "managed_object_address": normalize_ip(object_address) or (clean_text(object_address) or None),
        "endpoint_device_names": parsed.get("endpoint_device_names") or [],
        "endpoint_interfaces": parsed.get("endpoint_interfaces") or [],
        "topology_object_key": parsed.get("topology_object_key") or (normalize_link_name(object_name) if object_name else None),
        "object_identity_source": "none",
        "object_identity_confidence": 0.0,
    }
    if result["managed_object_name"]:
        result["object_identity_source"] = "h3c_varbind_or_raw"
        result["object_identity_confidence"] = 0.7 if result["endpoint_device_names"] else 0.5
    if result["managed_object_address"]:
        result["object_identity_confidence"] = max(result["object_identity_confidence"], 0.6)
    return result


def extract_managed_device_name(row: dict) -> str:
    name = first_present(
        row.get("managed_device_name"),
        row.get("device_name"),
        find_varbind_value(nested_get(row, ["trap", "varbinds"]), DEVICE_NAME_OID_SUFFIX),
    )
    return "" if looks_like_link_object(name) else name


def extract_varbind_device_ip(row: dict) -> str:
    return normalize_ip(find_varbind_value(nested_get(row, ["trap", "varbinds"]), DEVICE_IP_OID_SUFFIX))


@dataclass
class DeviceIdentityLookup:
    enabled: bool = True
    cache: Dict[str, Optional[dict]] = field(default_factory=dict)
    requested: int = 0
    hits: int = 0
    misses: int = 0
    error: Optional[str] = None

    def __post_init__(self) -> None:
        self.enabled = self.enabled and pymysql is not None and os.getenv("MYSQL_PASSWORD", "") != ""

    def lookup_device_name(self, device_name: Any) -> Optional[dict]:
        name = clean_text(device_name)
        if not name:
            return None
        self.requested += 1
        cache_key = name.lower()
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if cached:
                self.hits += 1
            else:
                self.misses += 1
            return cached
        if not self.enabled:
            self.misses += 1
            self.cache[cache_key] = None
            return None
        try:
            conn = pymysql.connect(
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
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT device_name, ip_address
                    FROM networkDevice
                    WHERE TRIM(REPLACE(device_name, '\t', '')) = %s
                    LIMIT 1
                    """,
                    (name,),
                )
                row = cursor.fetchone()
            conn.close()
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            self.enabled = False
            self.misses += 1
            self.cache[cache_key] = None
            return None
        ip_address = normalize_ip((row or {}).get("ip_address"))
        if not row or not ip_address:
            self.misses += 1
            self.cache[cache_key] = None
            return None
        result = {"device_name": clean_text(row.get("device_name")), "ip_address": ip_address}
        self.hits += 1
        self.cache[cache_key] = result
        return result

    def metrics(self) -> dict:
        return {
            "device_lookup_available": self.enabled,
            "device_lookup_requested": self.requested,
            "device_lookup_hits": self.hits,
            "device_lookup_misses": self.misses,
            "device_lookup_error": self.error,
        }


def resolve_trap_device_identity(trap_doc: dict, device_lookup: Optional[DeviceIdentityLookup] = None) -> dict:
    sender_ip = first_present(
        trap_doc.get("trap_sender_ip"),
        trap_doc.get("collector_source_ip"),
        trap_doc.get("source_ip"),
        nested_get(trap_doc, ["host", "ip"]),
    )
    agent_addr = first_present(
        trap_doc.get("snmp_agent_addr"),
        trap_doc.get("agent_addr"),
        nested_get(trap_doc, ["trap", "agent_addr"]),
        extract_agent_addr_from_raw(trap_doc.get("raw_message")),
    )
    valid_agent_addr = normalize_ip(agent_addr)
    managed_name = extract_managed_device_name(trap_doc)
    raw_name = first_present(
        trap_doc.get("managed_device_name"),
        trap_doc.get("device_name"),
        find_varbind_value(nested_get(trap_doc, ["trap", "varbinds"]), DEVICE_NAME_OID_SUFFIX),
    )
    object_like_name = looks_like_link_object(raw_name)
    existing_managed_ip = normalize_ip(trap_doc.get("managed_device_ip"))
    varbind_device_ip = extract_varbind_device_ip(trap_doc)

    managed_ip = ""
    identity_source = "unknown"
    confidence = 0.0
    if valid_agent_addr:
        managed_ip = valid_agent_addr
        identity_source = "snmp_agent_addr"
        confidence = 0.95
    elif existing_managed_ip:
        managed_ip = existing_managed_ip
        identity_source = clean_text(trap_doc.get("device_identity_source")) or "device_name_lookup"
        confidence = float(trap_doc.get("device_identity_confidence") or 0.9)
    elif varbind_device_ip and not object_like_name:
        managed_ip = varbind_device_ip
        identity_source = "varbind_device_ip"
        confidence = 0.75
    elif managed_name:
        lookup = device_lookup or DeviceIdentityLookup()
        matched = lookup.lookup_device_name(managed_name)
        if matched:
            managed_name = matched.get("device_name") or managed_name
            managed_ip = matched.get("ip_address") or ""
            identity_source = "device_name_lookup"
            confidence = 0.9
    return {
        "trap_sender_ip": sender_ip or None,
        "collector_source_ip": sender_ip or None,
        "snmp_agent_addr": valid_agent_addr or None,
        "managed_device_name": managed_name or None,
        "managed_device_ip": managed_ip or None,
        "device_identity_source": identity_source,
        "device_identity_confidence": confidence,
    }


def enrich_topology(row: dict, topology_lookup: Optional[TopologyLookupService] = None) -> dict:
    service = topology_lookup or TopologyLookupService()
    result = {
        "topology_match": False,
        "matched_link": None,
        "related_device_roles": [],
        "topology_correlation_status": "unmatched",
    }
    object_name = row.get("managed_object_name")
    endpoints = row.get("endpoint_device_names") or []
    interfaces = row.get("endpoint_interfaces") or []
    matched_link = service.lookup_link_by_name(object_name) if object_name else None
    if not matched_link and len(endpoints) >= 2:
        matched_link = service.lookup_link_by_endpoints(
            endpoints[0],
            endpoints[1],
            interfaces[0] if len(interfaces) > 0 else None,
            interfaces[1] if len(interfaces) > 1 else None,
        )
    if matched_link:
        result["topology_match"] = True
        result["matched_link"] = matched_link
        result["topology_correlation_status"] = "matched_link"
        roles = []
        for device_name in [matched_link.get("source_device"), matched_link.get("target_device")]:
            device = service.lookup_device_by_name(device_name)
            if device:
                roles.append(
                    {
                        "device_name": device.get("device_name"),
                        "ip_address": device.get("ip_address"),
                        "role": device.get("role"),
                        "hierarchy": device.get("hierarchy"),
                        "status": device.get("status"),
                    }
                )
        result["related_device_roles"] = roles
    elif object_name:
        result["topology_correlation_status"] = "object_extracted_unmatched"
    return result


def enrich_trap(
    trap: dict,
    lookup: Optional[MibLookupService] = None,
    device_lookup: Optional[DeviceIdentityLookup] = None,
    topology_lookup: Optional[TopologyLookupService] = None,
    alarm_lookup: Optional[TrapAlarmDefinitionLookupService] = None,
) -> dict:
    row = dict(trap)
    identity = resolve_trap_device_identity(row, device_lookup)
    row.update(identity)
    row.update(extract_managed_object(row))
    row.update(enrich_topology(row, topology_lookup))
    row["device_name"] = identity.get("managed_device_name")
    row["device_ip"] = identity.get("managed_device_ip")
    alarm_service = alarm_lookup or TrapAlarmDefinitionLookupService()
    row = alarm_service.enrich_trap_alarm_definition(row)
    if has_translated_fields(row):
        row["mib_translated"] = bool(row.get("mib_translated") is not False and row.get("trap_oid_name"))
        row.setdefault("mib_lookup_source", "elasticsearch")
        return row
    service = lookup or MibLookupService()
    mapping = service.lookup_oid(row.get("trap_oid"))
    if not mapping:
        row.setdefault("mib_translated", False)
        row.setdefault("mib_lookup_source", "miss")
        return row
    row.update(
        {
            "trap_oid_name": mapping.get("name"),
            "trap_oid_module": mapping.get("module"),
            "trap_oid_type": mapping.get("object_type"),
            "trap_oid_description": mapping.get("description_short"),
            "mib_translated": True,
            "mib_lookup_source": "mysql",
        }
    )
    return row


def enrich_traps(traps: Iterable[dict], lookup: Optional[MibLookupService] = None) -> Tuple[List[dict], dict]:
    service = lookup or MibLookupService()
    alarm_lookup = TrapAlarmDefinitionLookupService()
    device_lookup = DeviceIdentityLookup()
    topology_lookup = TopologyLookupService()
    enriched = []
    for trap in traps:
        row = dict(trap)
        identity = resolve_trap_device_identity(row, device_lookup)
        row.update(identity)
        row.update(extract_managed_object(row))
        row["device_name"] = identity.get("managed_device_name")
        row["device_ip"] = identity.get("managed_device_ip")
        enriched.append(enrich_trap(row, service, device_lookup, topology_lookup, alarm_lookup))
    es_hits = sum(1 for trap in enriched if trap.get("mib_lookup_source") in {"elasticsearch", "logstash_dictionary"} and trap.get("mib_translated"))
    mysql_metrics = service.metrics()
    identity_metrics = device_lookup.metrics()
    topology_metrics = topology_lookup.metrics()
    alarm_metrics = alarm_lookup.metrics()
    stats = {
        **alarm_metrics,
        "lookup_available": mysql_metrics.get("available"),
        "lookup_requested": mysql_metrics.get("requested"),
        "lookup_hits": mysql_metrics.get("hits"),
        "lookup_misses": mysql_metrics.get("misses"),
        "lookup_error": mysql_metrics.get("error"),
        **identity_metrics,
        **topology_metrics,
        "identity_source_counts": {
            source: sum(1 for trap in enriched if trap.get("device_identity_source") == source)
            for source in sorted({str(trap.get("device_identity_source") or "unknown") for trap in enriched})
        },
        "trap_sender_ip_count": len({trap.get("trap_sender_ip") for trap in enriched if trap.get("trap_sender_ip")}),
        "trap_managed_device_resolved_count": sum(1 for trap in enriched if trap.get("managed_device_ip")),
        "trap_managed_device_unresolved_count": sum(1 for trap in enriched if not trap.get("managed_device_ip")),
        "trap_sender_as_device_ip_count": sum(
            1
            for trap in enriched
            if trap.get("trap_sender_ip") and trap.get("managed_device_ip") and normalize_ip(trap.get("trap_sender_ip")) == normalize_ip(trap.get("managed_device_ip"))
        ),
        "trap_object_extracted_count": sum(1 for trap in enriched if trap.get("managed_object_name")),
        "trap_topology_link_matched_count": sum(1 for trap in enriched if trap.get("topology_match") and trap.get("matched_link")),
        "trap_topology_link_unmatched_count": sum(1 for trap in enriched if trap.get("managed_object_name") and not trap.get("matched_link")),
        "trap_device_identity_unresolved_count": sum(1 for trap in enriched if not trap.get("managed_device_ip")),
        "trap_alarm_definition_matched_count": sum(1 for trap in enriched if trap.get("alarm_definition_matched")),
        "trap_alarm_definition_unmatched_count": sum(1 for trap in enriched if not trap.get("alarm_definition_matched")),
        "es_translated_hits": es_hits,
        "translated_total": sum(1 for trap in enriched if trap.get("mib_translated")),
        "untranslated_total": sum(1 for trap in enriched if not trap.get("mib_translated")),
    }
    return enriched, stats
