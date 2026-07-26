# Task 2: Docker Compose 基础环境

## Scope

本任务只完成 JSCN-20 Docker Compose 基础环境，不部署 Elasticsearch、Kibana、Logstash、Redis、MySQL，不开发 Python Worker，不编写 Logstash pipeline。

执行时间：2026-05-17

执行用户：`aiops`

## Account and Permission

| Item | Result |
| --- | --- |
| Runtime user | `aiops` |
| User groups after setup | `aiops sudo docker` |
| Passwordless sudo | not enabled |
| Docker socket access | `aiops` 新登录会话可直接访问 |

说明：旧的 SSH alias `JSCN-20` 默认用户仍是 `yvesyuan`，该用户不在 docker 组中，直接访问 Docker socket 会被拒绝。Docker 操作应使用 `aiops` 用户的新会话执行。

## Installation Result

由于访问 Docker 官方仓库 `download.docker.com` 时出现 TLS connection reset，本任务改用 Ubuntu 20.04 系统仓库安装 Docker 基础环境。

| Component | Version |
| --- | --- |
| Docker Engine | `26.1.3` |
| docker-compose | `1.25.0` |
| containerd | `1.7.24` |
| Docker service | active |

Docker info 摘要：

| Item | Result |
| --- | --- |
| Server Version | `26.1.3` |
| Storage Driver | `overlay2` |
| Cgroup Driver | `cgroupfs` |
| Docker Root Dir | `/var/lib/docker` |
| Operating System | Ubuntu 20.04.6 LTS |
| Architecture | x86_64 |

## Directory Setup

已创建并授权给 `aiops:aiops`：

```text
/opt/jscn-aiops
/data/jscn-aiops
/data/jscn-aiops/es
/data/jscn-aiops/logstash
/data/jscn-aiops/reports
/data/jscn-aiops/backups
```

权限验证：

```text
drwxr-xr-x aiops aiops /opt/jscn-aiops
drwxr-xr-x aiops aiops /data/jscn-aiops
drwxr-xr-x aiops aiops /data/jscn-aiops/es
drwxr-xr-x aiops aiops /data/jscn-aiops/logstash
drwxr-xr-x aiops aiops /data/jscn-aiops/reports
drwxr-xr-x aiops aiops /data/jscn-aiops/backups
```

## Docker Verification

已完成：

1. `docker --version`
2. `docker-compose --version`
3. `docker info`
4. 创建和删除 Docker network：`aiops-task2-check`
5. 创建和删除 Docker volume：`aiops-task2-check`

验证结论：Docker daemon 正常，`aiops` 用户具备 Docker network 和 volume 管理能力。

## Compose Skeleton

仓库新增：

1. `deploy/docker-compose.yml`
2. `deploy/README.md`

当前 Compose 文件只包含基础 network、占位 volume 和 smoke service，不包含任何业务服务。

JSCN-20 已同步部署骨架到：

```text
/opt/jscn-aiops/deploy/docker-compose.yml
/opt/jscn-aiops/deploy/README.md
```

Compose 配置校验已通过：

```bash
cd /opt/jscn-aiops/deploy
docker-compose config
```

输出摘要：

```text
version: '3.7'
services:
  compose-check:
    container_name: jscn-aiops-compose-check
    image: hello-world:latest
networks:
  aiops-backend:
    name: jscn-aiops-backend
volumes:
  aiops-placeholder:
    name: jscn-aiops-placeholder
```

## Known Issue

`docker run --rm hello-world` 未成功，原因是访问 Docker Hub 超时：

```text
Get "https://registry-1.docker.io/v2/": net/http: request canceled while waiting for connection
```

判断：Docker daemon 和用户权限正常，问题在外部镜像仓库访问。Task 3 部署 Elasticsearch/Kibana 前需要处理镜像源或离线镜像方案。

## Commands Executed

以下命令为脱敏后的操作记录，不包含 sudo 密码：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release
sudo apt-get install -y docker.io docker-compose
sudo usermod -aG docker aiops
sudo systemctl enable --now docker
sudo mkdir -p /opt/jscn-aiops /data/jscn-aiops/es /data/jscn-aiops/logstash /data/jscn-aiops/reports /data/jscn-aiops/backups
sudo chown -R aiops:aiops /opt/jscn-aiops /data/jscn-aiops
sudo chmod 755 /opt/jscn-aiops /data/jscn-aiops
docker --version
docker-compose --version
docker info
docker network create aiops-task2-check
docker volume create aiops-task2-check
docker network inspect aiops-task2-check
docker volume inspect aiops-task2-check
docker network rm aiops-task2-check
docker volume rm aiops-task2-check
```

## Acceptance Result

Task 2 验收项已完成：

1. Docker Engine 已安装并启动。
2. docker-compose 已安装。
3. `aiops` 用户可管理 Docker network 和 volume。
4. JSCN-20 规划目录已创建并授权。
5. 仓库已提供 Compose 基础骨架和启动规范。
6. Compose 骨架已同步到 `/opt/jscn-aiops/deploy` 并通过 `docker-compose config` 校验。
7. 已记录 Docker Hub 访问超时风险。
