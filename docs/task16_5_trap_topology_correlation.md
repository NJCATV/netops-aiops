# Task 16.5 Trap Topology Correlation
## Goal

Some H3C Trap records do not carry a reliable managed-device IP. The UDP sender can be a relay, and SNMPv1 `agent_addr` may be `255.255.255.255` or `\xFF\xFF\xFF\xFF`. Task 16.5 adds topology-object parsing so these Trap candidates can still be analyzed by managed object, link name, endpoint devices, and interfaces.

## Identity Model

| Field | Meaning |
| --- | --- |
| `trap_sender_ip` | UDP sender or relay observed by Logstash. It is not the failing device identity. |
| `managed_device_ip` | Resolved device IP when a valid SNMP agent address, explicit device varbind, or `networkDevice` lookup is available. It may be null. |
| `managed_object_name` | H3C object or link name parsed from varbinds or raw Trap text, such as `GZL-16K-M-B To GZL-16K-M-A Link2 IPv4`. |
| `managed_object_address` | Object address parsed from H3C varbind `25506.4.2.2.1.103` when present and valid. |
| `topology_object_key` | Normalized object key used for grouping and history correlation. |
| `matched_link` | Compact `networkLinks` row when topology matching succeeds. |

Invalid agent addresses such as `255.255.255.255`, `0.0.0.0`, and `\xFF\xFF\xFF\xFF` are ignored. When no valid managed-device IP exists, `managed_device_ip` remains null instead of falling back to `trap_sender_ip`.

## Parsing Sources

Trap enrichment now extracts object evidence from:

- H3C varbind suffix `25506.4.2.2.1.102` for object or device name.
- H3C varbind suffix `25506.4.2.2.1.103` for object address.
- H3C varbind suffix `25506.4.2.59.1.2` for full link description.
- Raw message text matching `A To B LinkX IPv4/IPv6:InterfaceA To InterfaceB`.

The parser fills:

- `managed_object_name`
- `managed_object_address`
- `endpoint_device_names`
- `endpoint_interfaces`
- `topology_object_key`
- `object_identity_source`
- `object_identity_confidence`

## Topology Lookup

New module:

- `aiops/topology/lookup.py`

Lookup order:

1. `networkLinks.link_name` exact match.
2. Normalized `link_name` match.
3. `source_device + target_device` match.
4. `source_device + target_device + interface` match.
5. `networkDevice.device_name` lookup for endpoint role/status metadata.

Normalization removes case and separator differences, for example `CN16K-F-HeXinA` versus `CN-16K-M-B`, but avoids broad fuzzy matching.

## Summary And Investigation

`current_window_summary` now includes topology fields in `important_traps` and `critical_alarm_candidates` and groups Trap candidates by `topology_object_key`, `managed_object_name`, or matched link before falling back to managed-device identity.

When a Trap has `matched_link`, `investigate_candidates` queries compact alarm-event evidence for both endpoints and related objects over the candidate time range plus/minus 30 minutes. It focuses on:

- `INTERFACE_LINK`
- `OPTICAL_FAULT`
- `BFD_FLAP`
- `RADIUS_SERVER_ABNORMAL`
- `PTP_CLOCK_JITTER`

The tool returns compact `related_alarm_events` and avoids bulk raw logs.

## Data Quality

New quality counters:

- `trap_object_extracted_count`
- `trap_topology_link_matched_count`
- `trap_topology_link_unmatched_count`
- `trap_device_identity_unresolved_count`
- `trap_sender_as_device_ip_count`

## Limits

- Historical ES Trap documents are not rewritten.
- AI still cannot query ES or MySQL directly.
- Link matching is conservative and may leave partially named objects unmatched.
- If only `managed_object_name` is known, AI must not invent device IPs.
- If topology matching fails, AI should put the Trap in `insufficient` or `watch`.
