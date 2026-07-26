# Troubleshooting

## Web Cannot Open

Check the Web container and Nginx response:

```bash
cd /opt/jscn-aiops/deploy
docker-compose ps aiops-web
docker-compose logs --tail=100 aiops-web
curl -I http://127.0.0.1:5772/
```

If `/api/health` fails through Web, check Nginx reverse proxy and API service:

```bash
curl -s http://127.0.0.1:5772/api/health
curl -s http://127.0.0.1:8080/api/health
docker-compose logs --tail=100 aiops-api
```

## API Login Fails

Check MySQL and API logs:

```bash
docker-compose ps mysql aiops-api
docker-compose logs --tail=100 mysql
docker-compose logs --tail=100 aiops-api
```

Passwords are stored as Werkzeug hashes in MySQL. They should never appear as plaintext.

## alarm_events Lag

Check event worker status and freshness:

```bash
docker-compose ps aiops-event-worker
docker-compose logs --tail=100 aiops-event-worker
curl -s http://127.0.0.1:8080/api/runtime/freshness
```

If lag grows, verify Elasticsearch is reachable and parsed Syslog is still arriving.

## Trap Sender Misidentified As Device

Trap sender IP is the collector or sender address, not necessarily the failed device. Review Trap records in the Web Trap page and check:

- `trap_sender_ip`
- `snmp_agent_addr`
- `managed_device_name`
- `managed_device_ip`
- `managed_object_name`
- `matched_link`

If `172.25.131.3` appears only as `trap_sender_ip`, that is expected. It must not be treated as the fault device.

## AI Run Stuck Running

Check API or scheduler logs depending on how the run was started:

```bash
docker-compose logs --tail=150 aiops-api
docker-compose logs --tail=150 aiops-scheduler
```

Also check whether the result files exist under:

```text
/data/jscn-aiops/reports/ai_runs/<run_uid>/
```

## Scheduler Not Running

```bash
docker-compose ps aiops-scheduler
docker-compose logs --tail=100 aiops-scheduler
```

The scheduler must run as a separate container. It should not run inside Flask/Gunicorn.

## MIB Translation Missing

Check MySQL mappings and Logstash dictionary mounts:

```bash
docker-compose logs --tail=100 logstash
ls -l /data/jscn-aiops/logstash/mib
```

Recent Trap documents should include `trap_oid_name`, `trap_oid_module`, `mib_translated`, and `mib_lookup_source` when dictionary lookup succeeds.
