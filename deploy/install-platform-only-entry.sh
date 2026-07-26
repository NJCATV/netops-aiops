#!/usr/bin/env bash
set -euo pipefail

deploy_dir="/opt/jscn-aiops/deploy"
env_file="${deploy_dir}/.env"

if [[ ! -f "${deploy_dir}/docker-compose.yml" || ! -f "${env_file}" ]]; then
  echo "未找到 /opt/jscn-aiops 生产部署目录。" >&2
  exit 1
fi

if grep -q '^AIOPS_WEB_BIND=' "${env_file}"; then
  sed -i 's/^AIOPS_WEB_BIND=.*/AIOPS_WEB_BIND=127.0.0.1/' "${env_file}"
else
  printf '\nAIOPS_WEB_BIND=127.0.0.1\n' >> "${env_file}"
fi

cd "${deploy_dir}"
docker-compose up -d --no-deps --force-recreate aiops-web
docker-compose restart aiops-api aiops-qq-adapter

api_ready=false
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/api/health >/dev/null; then
    api_ready=true
    break
  fi
  sleep 1
done
if [[ "${api_ready}" != "true" ]]; then
  echo "AIOps API 在 30 秒内未恢复健康。" >&2
  exit 1
fi

login_status="$(curl -sS -o /tmp/aiops-local-login-disabled.json -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  --data '{"username":"disabled","password":"disabled"}' \
  http://127.0.0.1:8080/api/auth/login)"

if [[ "${login_status}" != "410" ]]; then
  echo "本地登录接口未按预期返回 410，实际为 ${login_status}。" >&2
  exit 1
fi

if ! ss -lnt | awk '$4 == "127.0.0.1:5772" { found=1 } END { exit !found }'; then
  echo "AIOps Web 未绑定到 127.0.0.1:5772。" >&2
  exit 1
fi

echo "AIOps 本地弱鉴权已停用；20:5772 已限制为本机回环访问。"
docker-compose ps aiops-web aiops-api aiops-qq-adapter
