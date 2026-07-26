# Task 16.3 Trap Device Identity Fix

## Current Fault Chain

The current Trap ingestion path conflates the UDP sender with the managed device:

```text
Logstash snmptrap input
  -> host/source address
  -> source_ip
  -> device_ip
  -> key_signals
  -> current_window_summary important_traps
  -> investigate_candidates identity/topology/history
  -> light_agent final JSON and ai_memory
```

In `deploy/logstash/pipeline/trap.conf`, the Ruby filter reads `source_ip` from the SNMP Trap object or Logstash host metadata and then executes:

```ruby
src = event.get('source_ip')
event.set('device_ip', src) if src && !event.get('device_ip')
```

For Trap documents relayed by `172.25.131.3`, this writes the relay/source address into `device_ip`. The same field is then used in `key_signals`, summary grouping, investigation identity, topology lookup, history lookup, and AI memory fingerprints.

## Field Evidence

Remote validation on `/opt/jscn-aiops` found recent `jscn-aiops-trap-raw-*` documents such as:

```json
{
  "source_ip": "172.25.131.3",
  "device_ip": "172.25.131.3",
  "device_name": "CHL-16K-M-B",
  "trap_oid_name": "hh3cRadiusAccServerUpTrap"
}
```

The raw SNMPv1 Trap contains:

```text
@source_ip="172.25.131.3"
@agent_addr=... @value="\xFF\xFF\xFF\xFF"
varbind 1.3.6.1.4.1.25506.4.2.2.1.102 = "CHL-16K-M-B"
```

No separate `agent_addr` or `snmp_agent_addr` field was stored in Elasticsearch. The SNMPv1 PDU `agent_addr` is present only inside `raw_message`, and the observed value decodes to `255.255.255.255`, so it is not a valid managed-device IP.

The same ES aggregation showed `source_ip` and `device_ip` have matching top buckets because the pipeline copied sender into device identity. `device_name` has many distinct managed devices behind `172.25.131.3`, proving that `172.25.131.3` is a relay/source, not a single failing managed device.

## MySQL Lookup

The runtime MySQL inventory tables are:

- `networkDevice`
  - `device_name`
  - `ip_address`
  - `status`
  - `role`
  - `hierarchy`
  - model/manufacturer/version metadata
- `networkLinks`
  - `source_device`, `source_ip`
  - `target_device`, `target_ip`
  - interface and link state metadata

Lookup by `device_name=CHL-16K-M-B` succeeds:

```text
CHL-16K-M-B -> 240A:4006:8140:4500::1
```

This gives a reliable fallback for historical Trap documents that contain only `source_ip=172.25.131.3` and `device_name=CHL-16K-M-B`.

## Fix Design

Trap fields now use these meanings:

| Field | Meaning |
| --- | --- |
| `source_ip` | Preserved existing field for UDP sender/source compatibility. |
| `trap_sender_ip` / `collector_source_ip` | UDP sender seen by Logstash. May be a relay. |
| `snmp_agent_addr` | Valid SNMPv1 PDU agent address when available and not `0.0.0.0` or `255.255.255.255`. |
| `managed_device_name` | Managed device name parsed from existing `device_name` or H3C varbind suffix `25506.4.2.2.1.102`. |
| `managed_device_ip` | Resolved managed device IP from valid agent address, explicit device-IP varbind, or MySQL `networkDevice`. |
| `device_ip` / `device_name` | Compatibility aliases for managed device identity only. |
| `device_identity_source` | `snmp_agent_addr`, `varbind_device_ip`, `device_name_lookup`, `sender_fallback`, or `unknown`. |
| `device_identity_confidence` | Numeric confidence from 0 to 1. |

`sender_fallback` is intentionally low confidence and should only be used when no managed name, agent address, or explicit device IP is available. For relayed Trap with a device name but no resolvable IP, `managed_device_ip` remains null and the identity source is `unknown`.

## Implemented Changes

### Logstash

`deploy/logstash/pipeline/trap.conf` now:

- writes `trap_sender_ip` and `collector_source_ip`;
- extracts valid `snmp_agent_addr` from raw SNMPv1 Trap text when possible;
- writes `managed_device_name` from parsed `device_name`;
- writes `device_ip` only when `managed_device_ip` is available;
- builds `key_signals` from managed identity plus Trap OID, not from relay IP alone.

Logstash does not query MySQL. If only `managed_device_name` is available, backend enrichment resolves IP later.

### Backend Enrichment

`aiops/mib/trap_enrichment.py` now provides:

```python
resolve_trap_device_identity(trap_doc) -> dict
```

Resolution order:

1. valid `snmp_agent_addr`;
2. explicit H3C device-IP varbind suffix `25506.4.2.2.1.103`;
3. MySQL `networkDevice` lookup by `managed_device_name`;
4. low-confidence `sender_fallback` only when no managed identity exists;
5. otherwise `unknown`.

Historical documents are supported because the resolver accepts old fields (`source_ip`, `device_name`, `device_ip`) and refuses to treat `source_ip` as device IP when a managed device name exists but lookup fails.

### Current Window Summary

Trap candidates are now grouped by:

```text
managed_device_ip + managed_device_name + trap_oid + specific_trap
```

Trap outputs include:

- `trap_sender_ip`
- `snmp_agent_addr`
- `managed_device_ip`
- `managed_device_name`
- `device_identity_source`
- `device_identity_confidence`

`data_quality` now includes:

- `trap_sender_ip_count`
- `trap_managed_device_resolved_count`
- `trap_managed_device_unresolved_count`
- `trap_sender_as_device_ip_count`
- `trap_identity_source_counts`
- `trap_identity_resolution_notes`

When one sender has multiple managed device names, the summary explicitly notes that the sender is a Trap relay/source, not the managed device.

### Investigation Tools

`investigate_candidates` now:

- uses `managed_device_ip` / `managed_device_name` as candidate identity;
- avoids using `trap_sender_ip` for topology or device-history lookups;
- falls back to `managed_device_name` when managed IP is missing;
- returns full Trap identity fields in `related_traps`;
- prevents `ai_memory` from using sender fallback as the device identity.

The controlled `get_device_history` tool now accepts either `device_ip` or `device_name`.

### Light Agent Prompt

The prompt now explicitly forbids treating `trap_sender_ip`, `collector_source_ip`, or relay IP as the failing device. If `managed_device_ip` is missing, the model must describe the evidence by `managed_device_name` and place uncertain identity cases into `insufficient` with a data-quality note.

## Expected Impact

- `current_window_summary` should no longer produce conclusions based on “single device 172.25.131.3”.
- `important_traps` and `critical_alarm_candidates` should show `CHL-16K-M-B` and, when lookup succeeds, `240A:4006:8140:4500::1`.
- `get_device_history` and `get_topology_context` should query the managed device identity instead of the relay.
- RADIUS, interface, optical, OSPF, and private Trap evidence should be assigned to managed device name/IP where resolvable.
- If identity cannot be resolved, the Trap remains visible but should be treated as insufficient rather than misattributed.
