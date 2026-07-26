# Pre-Frontend Readiness Report

Generated at: 2026-05-19 12:35 CST

Scope: readiness check before starting Flask API and Web UI work. This check did not implement new features, did not delete files, and did not write test data to MySQL. It generated validation artifacts under `outputs/pre_frontend/`.

## 1. Overall Conclusion

Status: `partially_ready_after_trap_alarm_definition_enrichment`

Recommendation: it is now reasonable to start a small Flask/Vue read-only workflow that consumes backend-enriched summary/investigation DTOs. Do not expose raw Trap sender identity as device identity. Broad operational pages should still wait for a compact frontend/API summary profile because the 24h Agent context remains too large.

The core backend chain is alive:

- Docker services are running: Elasticsearch, Logstash, Kibana, MySQL, and `aiops-event-worker`.
- `alarm_events` are being generated continuously by the worker.
- `current_window_summary` can combine alarm events, Trap, MIB, topology, and data-quality fields.
- `light_agent` returns valid JSON and uses `investigate_candidates`.
- Task 17 tables exist, saved findings exist, and investigation memory can be read.

Task 16.6 update:

- Imported the private NMS/vendor Trap alarm definition export. This is not a standard MIB; it is an alarm definition library containing names, severity, lifecycle type, reasons, and suggestions.
- Added MySQL `trap_alarm_definitions` and `trap_alarm_oid_aliases`.
- Imported `8928` definitions and `26689` unique OID aliases.
- Vendor distribution: `unknown=5476`, `h3c=2285`, `huawei=1167`.
- Backfilled recent 7d Trap enrichment: `7055` scanned, `7055` updated, `6921` matched alarm definitions.
- Recent 7d `device_ip=172.25.131.3` after backfill: `0`.
- Recent 7d invalid `snmp_agent_addr` after backfill: `0`.

Main readiness risks:

- The latest Task 16.6 24h `light_agent` run consumed `308725` tokens because the compacted 24h summary was still about `207992` bytes plus tool results. This is too expensive/slow for an interactive Web workflow.
- MIB translation coverage for recent Trap is still incomplete, but alarm definition coverage is now much higher.
- Current syslog unknown-family ratio is high in the 24h check (`0.5195`), so frontend severity labels should show data-quality caveats.

## 2. Blocking Issues

1. 24h Agent context is too large for routine UI/API use.

   Evidence: Task 16.6 `run_light_agent.py --max-tool-rounds 2` succeeded, but took `389357 ms` and used `308725` tokens.

   Recommended fix: add a frontend/API-oriented summary profile. Lower candidate limits, trim evidence samples further, and avoid passing large 24h Trap candidate payloads by default.

2. Frontend must not read raw Trap sender fields directly.

   Evidence: Trap sender `172.25.131.3` is still present as `trap_sender_ip`, correctly, but must never be displayed as the faulty device. Backend summary and investigation now keep `trap_sender_as_device_ip_count=0`.

   Recommended fix: Flask API should call backend summary/investigation builders or a dedicated DTO layer that explicitly separates `trap_sender_ip`, `managed_device_ip`, `managed_object_name`, and `matched_link`.

## 3. Non-Blocking Issues

1. Server `/opt/jscn-aiops` is not itself a Git repository.

   `git status` on the server returns `fatal: not a git repository`. Local Git HEAD was compared against server files and all tracked files match, but deployment synchronization is file-copy based. This is acceptable for the current check, but the workflow should be documented before more frontend/API work starts.

2. `AGENT.md`, `agent.md`, and `README.md` are missing from `/opt/jscn-aiops`.

   The requested files were checked and not found on the server. Current operational docs under `docs/` exist. If these top-level docs are still required, restore them in a separate documentation cleanup task.

3. MIB translation gaps remain.

   Task 16.6 24h Trap MIB untranslated count in summary: `191/334`. However, private alarm definition coverage is now much higher: `316/334` in the same summary window. OIDs such as `1.3.6.1.4.1.25506.4.2.59.2.0.4` now have alarm names even when MIB translation is absent.

4. SMTP config is absent.

   SMTP env keys are not present. This does not block Flask/Web read-only development unless email delivery is in the first frontend scope.

5. Saved AI memory includes test-looking feedback text.

   `ai_finding_feedback` has 1 row and memory returned `actual_root_cause=test_confirmed_root_cause`, `action_taken=test_action_taken`. This is not harmful to runtime, but it should be marked as validation/test feedback before operator-facing UI shows it.

## 4. Check Details

### Git Status

Server:

- Path: `/opt/jscn-aiops`
- `git status`: failed because the server directory has no `.git`.

Local/source-of-truth comparison:

- Local Git HEAD before this report: tracked file count `62`.
- Server tracked-file hash comparison: `diff_count=0`, `missing_count=0`.
- Server extra non-runtime files: `0`.
- Ignored/runtime server files include `deploy/.env`, `outputs/`, `reports/`, and `__pycache__/`.

Docs:

- Existing tracked docs match server files before this report.
- This report updates `docs/pre_frontend_readiness_report.md`.

### Docker Services

`docker-compose ps` under `/opt/jscn-aiops/deploy`:

| Service | Status |
| --- | --- |
| `jscn-aiops-elasticsearch` | Up, healthy, port `9200` |
| `jscn-aiops-kibana` | Up, port `5601` |
| `jscn-aiops-logstash` | Up, UDP `10086/10087` |
| `jscn-aiops-mysql` | Up, healthy, port `13306` |
| `jscn-aiops-event-worker` | Up |

`aiops-event-worker` is included in `deploy/docker-compose.yml` and is running.

Logstash summary:

- Pipeline `main` loads `syslog.conf` and `trap.conf`.
- SNMP Trap input listens on UDP `10086`.
- Syslog UDP input listens on UDP `10087`.
- Recent logs show Logstash restarted around 2026-05-19 11:12 CST and then started cleanly.
- Warnings observed are Elasticsearch 7.x template/data-stream compatibility messages and are not current blockers.

Event worker summary:

- Worker runs every 300 seconds with 30-minute lookback.
- Recent rounds show `error_count=0`.
- Latest observed round: window `2026-05-19T03:49:23Z` to `2026-05-19T04:19:23Z`, generated `99`, written `99`.

### alarm_events

Counts at 2026-05-19T04:23:46Z:

| Window | syslog-parsed | trap-raw | alarm-events |
| --- | ---: | ---: | ---: |
| 1h | 471 | 16 | 168 |
| 3h | 1313 | 37 | 498 |
| 24h | 11804 | 292 | 4182 |

Latest parsed syslog:

- `@timestamp=2026-05-19T04:23:45.180Z`
- `device_name=CB-CR16K-M-A`
- `event_code=PPP_CHASTEN`

Latest alarm event:

- `last_seen=2026-05-19T04:19:16.845Z`
- `event_type=PPP_AUTH_FAILURE`
- `device_name=CB-CR16K-M-A`
- `object_key=domain-1`

Lag:

- Latest syslog minus latest alarm event: `268.335` seconds.
- This matches the worker interval/lookback behavior and is not a current断档.

Conclusion: alarm aggregation is continuously running. No 1h/3h/24h alarm_events断档 was found.

### Trap Device Identity

Raw ES state:

- Recent 7d Trap `device_ip=172.25.131.3` after Task 16.6 backfill: `0`.
- Recent 7d invalid `snmp_agent_addr`: `0`.
- Recent 7d `alarm_definition_matched=true`: `6921`.
- Recent 7d `alarm_definition_matched=false`: `134`.

Summary/enrichment state:

- 24h `current_window_summary` reports `trap_sender_as_device_ip_count=0`.
- Topology object extraction: `334`.
- Topology link matched: `161`.
- Topology link unmatched: `173`.
- Alarm definition matched: `316`.
- Alarm definition unmatched: `18`.

Conclusion: backend summary/investigation and the recent 7d backfilled raw Trap window no longer treat `172.25.131.3` as the failed device. API/UI should still consume enriched DTOs rather than raw sender fields.

### MIB Translation

MySQL:

- `mib_oid_mappings` exists.
- Record count: `43504`.

Logstash dictionary files:

| File | Exists | Size |
| --- | --- | ---: |
| `/data/jscn-aiops/logstash/mib/h3c_oid_name.json` | yes | 149790 |
| `/data/jscn-aiops/logstash/mib/h3c_oid_module.json` | yes | 126754 |
| `/data/jscn-aiops/logstash/mib/h3c_oid_type.json` | yes | 129952 |

Trap pipeline:

- `trap.conf` references all three dictionary files.
- `translate` filters and `mib_lookup_source` are present.

Recent 24h summary:

- `trap_mib_translated_count=125`.
- `trap_mib_untranslated_count=175`.

Top untranslated enterprise OIDs in 24h raw scan:

| enterprise_oid | Count |
| --- | ---: |
| `1.3.6.1.4.1.25506.4.2.59.2` | 127 |
| `1.3.6.1.4.1.25506.2.13.3` | 71 |
| `1.3.6.1.4.1.25506.2.6.2` | 27 |
| `0.0` | 2 |
| `1.3.6.1.4.1.25506.2.40.3` | 2 |

Top untranslated Trap OIDs:

| trap_oid | Count |
| --- | ---: |
| `1.3.6.1.4.1.25506.2.13.3.0.2` | 67 |
| `1.3.6.1.4.1.25506.4.2.59.2.0.4` | 64 |
| `1.3.6.1.4.1.25506.4.2.59.2.0.6` | 58 |
| `1.3.6.1.4.1.25506.2.6.2.0.11` | 27 |
| `1.3.6.1.4.1.25506.2.13.3.0.3` | 4 |

Conclusion: MIB dictionary path is deployed, but coverage is incomplete for current critical/important private H3C Trap families.

### AI Agent

24h summary command:

```bash
python3 scripts/build_current_window_summary.py \
  --hours 24 \
  --env-file deploy/.env \
  --output outputs/pre_frontend/current_window_summary_24h.json \
  --trap-scan-size 1000 \
  --important-traps-limit 50 \
  --critical-traps-limit 50 \
  --critical-alarm-candidates-limit 80
```

24h summary result:

- `syslog_total=11814`
- `trap_total=300`
- `alarm_event_total=4180`
- `open_event_total=89`
- `critical_alarm_candidates=51`
- `important_traps=50`
- `flapping_event_total=1684`
- `baseline_data_sufficient=true`
- `topology_context_available=true`

Data quality from summary:

- `unknown_event_family_ratio=0.5195`
- `trap_object_extracted_count=300`
- `trap_topology_link_matched_count=157`
- `trap_topology_link_unmatched_count=143`
- `trap_device_identity_unresolved_count=160`
- `trap_sender_as_device_ip_count=0`
- `trap_mib_translated_count=125`
- `trap_mib_untranslated_count=175`

Agent command:

```bash
python3 scripts/run_light_agent.py \
  --summary-json outputs/pre_frontend/current_window_summary_24h.json \
  --output outputs/pre_frontend/light_agent_24h.json \
  --max-tool-rounds 2 \
  --env-file deploy/.env
```

Agent result:

- Valid JSON: yes.
- `ok=true`.
- Model: `deepseek-v4-pro`.
- Tool calls: `2`.
- Tools used: `investigate_candidates`, then one bounded `get_related_events`.
- Final finding count: `3`.
- Duration: `389357 ms`.
- Total tokens: `308725`.
- The output mentions `172.25.131.3` only as a Trap relay/source data-quality note, not as a faulty device.

Agent combined evidence:

- Output included alarm events such as optical/interface/RADIUS/BFD issues.
- Output included Trap data-quality notes and topology-matched Trap handling.
- The result was not Trap-only.

Concern:

- Token and runtime are too high for frontend interaction. The default frontend endpoint should use much smaller summary and candidate limits.

### AI Memory And Feedback

Tables:

| Table | Exists | Count |
| --- | --- | ---: |
| `ai_analysis_runs` | yes | 1 |
| `ai_findings` | yes | 26 |
| `ai_finding_feedback` | yes | 1 |

`run_light_agent.py --help` confirms `--save-to-db` is available.

This check did not run `--save-to-db` and did not write test records.

`investigate_candidates` memory check:

- Generated `outputs/pre_frontend/investigation_24h.json`.
- `candidate_count=3`.
- `ai_memory.enabled=true` for all 3 investigations.
- Memory record counts: `[1, 0, 0]`.

One existing memory record includes validation-looking feedback text (`test_confirmed_root_cause`, `test_action_taken`). Mark this before exposing memory/feedback in UI.

### Configuration And Paths

`.env`:

- `deploy/.env` exists and services can read it.
- Secret values were not printed.

Config key presence:

| Key | Present |
| --- | --- |
| `DEEPSEEK_API_KEY` | yes |
| `AI_API_KEY` | no |
| `DEEPSEEK_BASE_URL` | no |
| `DEEPSEEK_MODEL` | no |
| `ELASTICSEARCH_URL` | no |
| `MYSQL_HOST` | yes |
| `MYSQL_PORT` | yes |
| `MYSQL_USER` | yes |
| `MYSQL_PASSWORD` | yes |
| `MYSQL_DATABASE` | yes |
| `SMTP_HOST` | no |
| `SMTP_PORT` | no |
| `SMTP_USER` | no |
| `SMTP_PASSWORD` | no |

Missing `ELASTICSEARCH_URL` is acceptable for current scripts because they default to `http://127.0.0.1:9200` on host and `http://elasticsearch:9200` in worker compose. For Flask API, set an explicit value to avoid environment ambiguity.

Path checks:

| Path | Exists | Writable |
| --- | --- | --- |
| `/data/jscn-aiops` | yes | yes |
| `/data/jscn-aiops/reports` | yes | yes |
| `/data/jscn-aiops/logstash/mib` | yes | yes |
| `/opt/jscn-aiops/outputs` | yes | yes |
| `/opt/jscn-aiops/outputs/debug` | yes | yes |

## 5. Recommended Next Steps

Recommended order before full Flask API/Web development:

1. Add a frontend-safe backend DTO/profile.

   The API should expose fields from enriched summary/investigation only, with explicit identity semantics:

   - `trap_sender_ip`
   - `managed_device_ip`
   - `managed_device_name`
   - `managed_object_name`
   - `matched_link`
   - `topology_correlation_status`

2. Reduce Agent context size for UI paths.

   Create smaller defaults for Web-triggered Agent runs, for example lower `critical_alarm_candidates`, `important_traps`, and evidence sample limits. Target a routine run below 60k tokens.

3. Improve or document current MIB gaps.

   Prioritize H3C `25506.4.2.59.2.*` Trap families because they dominate current untranslated important Trap volume.

4. Clean up AI feedback seed data before operator UI.

   Either mark the existing feedback row as validation data or replace it with a real operator feedback example.

5. After the above, start Flask API / Web page Task.

   Suggested first API scope:

   - Health/status endpoint.
   - Current summary endpoint using enriched summary, not raw ES.
   - Candidate investigation endpoint with strict limits.
   - Data-quality endpoint to surface the caveats above.
