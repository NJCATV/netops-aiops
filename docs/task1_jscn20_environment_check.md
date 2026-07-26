# Task 1: JSCN-20 服务器环境检查

## Scope

本任务只做 JSCN-20 环境检查和文档记录，不安装 Docker/Git，不部署 ELK，不创建运行目录，不启动任何服务。

检查时间：2026-05-17

连接方式：本地 SSH config 中的 `JSCN-20`

## Basic Host Information

| Item | Result |
| --- | --- |
| SSH alias | `JSCN-20` |
| Hostname | `aiServer20` |
| OS | Ubuntu 20.04.6 LTS |
| Kernel | Linux 5.4.0-216-generic |
| Architecture | x86_64 |
| Login user | `yvesyuan` |
| User groups | `yvesyuan sudo kvm libvirt` |
| Uptime | 202 days 20 hours |
| Server timezone | `Etc/UTC` |
| NTP | active, synchronized |

说明：服务器时区当前为 UTC。项目业务默认时区规划为 `Asia/Shanghai`，后续部署服务时需要通过容器环境变量或应用配置显式设置时区，避免报告时间窗口混乱。

## Network Information

`ip -brief address` 检查结果：

| Interface | State | Address |
| --- | --- | --- |
| `lo` | UNKNOWN | `127.0.0.1/8` |
| `eno1` | UP | no IP shown |
| `eno2` | DOWN | no IP shown |
| `eno3` | DOWN | no IP shown |
| `eno4` | DOWN | no IP shown |
| `br0` | UP | `172.25.60.20/29` |

## Resource Check

| Item | Result |
| --- | --- |
| CPU cores | 8 |
| Memory | 141 GiB total, 139 GiB available |
| Swap | 0 B |
| Root filesystem | 273 GiB total, 257 GiB available, mounted on `/` |
| `/data` filesystem | 916 GiB total, 869 GiB available, mounted on `/data` |
| Extra large disk | `/mnt`, 21.7 TiB available |

初步判断：资源足够支撑第一阶段单机 ELK 验证。后续 Elasticsearch 数据目录建议优先使用 `/data/jscn-aiops/es`，避免写入系统根目录。

## Disk Layout

关键挂载点：

| Device | Filesystem | Mountpoint | Available |
| --- | --- | --- | --- |
| `/dev/mapper/ubuntu--vg-ubuntu--lv` | ext4 | `/` | 256.7 GiB |
| `/dev/sdc1` | ext4 | `/data` | 868.8 GiB |
| `/dev/sdb1` | xfs | `/mnt` | 21.7 TiB |

## Port Check

UDP 监听检查命令：`ss -lun`

结果：当前仅看到本地 DNS UDP 53 监听，未发现 UDP `10086` 或 UDP `10087` 被占用。

TCP 监听检查命令：`ss -ltn`

已监听 TCP 端口：

| Address | Port |
| --- | ---: |
| `0.0.0.0` | 5332 |
| `127.0.0.53%lo` | 53 |
| `*` | 9090 |
| `[::]` | 5332 |

结论：Syslog UDP `10087` 和 SNMP Trap UDP `10086` 当前未被监听程序占用。

## Firewall Check

| Check | Result |
| --- | --- |
| `systemctl is-active firewalld` | inactive |
| `systemctl is-active ufw` | active |
| `ufw status` | 当前用户直接执行需要 root 权限 |
| `/etc/ufw/ufw.conf` | `ENABLED=no` |

说明：`ufw` systemd 服务显示 active，但配置文件中 `ENABLED=no`。由于 `ufw status` 需要 root 权限，Task 1 未进一步读取规则。后续开放 UDP `10086`、UDP `10087` 前，应使用 sudo 明确确认防火墙实际状态。

## Docker and Compose Check

| Command | Result |
| --- | --- |
| `docker --version` | `command not found` |
| `docker compose version` | `command not found` |
| `docker-compose --version` | `command not found` |
| `dpkg -l docker-ce` | package not found |
| `dpkg -l docker.io` | package not found |

结论：JSCN-20 未安装 Docker 和 Docker Compose。

## Git Check

| Command | Result |
| --- | --- |
| `git --version` | `git version 2.25.1` |
| `dpkg -l git` | installed: `1:2.25.1-1ubuntu3.14` |

结论：虽然任务输入中说明没有 Git，但服务器实际已安装 Git。

## Directory and Permission Check

| Path | Result |
| --- | --- |
| `/opt` | exists, owner `root:root`, mode `755` |
| `/data` | exists, owner `root:root`, mode `755` |
| `/opt/jscn-aiops` | not exists |
| `/data/jscn-aiops` | not exists |
| current user write `/opt` | no |
| current user write `/data` | no |
| passwordless sudo | no, `sudo: a password is required` |

结论：后续创建 `/opt/jscn-aiops` 和 `/data/jscn-aiops` 需要 sudo 权限或管理员预先创建并授权。

## Commands Executed

```bash
ssh JSCN-20 hostname
ssh JSCN-20 hostnamectl
ssh JSCN-20 uname -a
ssh JSCN-20 id
ssh JSCN-20 groups
ssh JSCN-20 uptime
ssh JSCN-20 date -Is
ssh JSCN-20 timedatectl
ssh JSCN-20 ip -brief address
ssh JSCN-20 nproc
ssh JSCN-20 free -h
ssh JSCN-20 df -h /
ssh JSCN-20 df -h /opt
ssh JSCN-20 df -h /data
ssh JSCN-20 lsblk -f
ssh JSCN-20 ss -lun
ssh JSCN-20 ss -ltn
ssh JSCN-20 docker --version
ssh JSCN-20 docker compose version
ssh JSCN-20 docker-compose --version
ssh JSCN-20 git --version
ssh JSCN-20 dpkg -l docker-ce
ssh JSCN-20 dpkg -l docker.io
ssh JSCN-20 dpkg -l git
ssh JSCN-20 systemctl is-active firewalld
ssh JSCN-20 systemctl is-active ufw
ssh JSCN-20 ufw status
ssh JSCN-20 cat /etc/ufw/ufw.conf
ssh JSCN-20 ls -ld /opt
ssh JSCN-20 ls -ld /data
ssh JSCN-20 ls -ld /opt/jscn-aiops
ssh JSCN-20 ls -ld /data/jscn-aiops
ssh JSCN-20 test -w /opt
ssh JSCN-20 test -w /data
ssh JSCN-20 sudo -n true
```

## Risks and Notes

1. Docker 未安装，Task 2 需要先制定 Docker 安装或替代部署方案。
2. 当前用户属于 sudo 组，但无免密 sudo；涉及安装、创建 `/opt/jscn-aiops` 和 `/data/jscn-aiops` 时需要输入 sudo 密码或由管理员预授权。
3. `/data` 空间适合作为 Elasticsearch、Logstash、报告和备份目录。
4. UDP `10086`、`10087` 未占用，但仍需在接入真实流量前确认防火墙和设备侧转发路径。
5. 服务器时区为 UTC，报告任务和索引日期需要显式处理 `Asia/Shanghai` 业务时区。

## Acceptance Result

Task 1 验收项已完成：

1. 已明确 OS 和内核版本。
2. 已明确 CPU、内存、磁盘资源。
3. 已明确 UDP `10086`、`10087` 当前未占用。
4. 已记录防火墙状态和待确认点。
5. 已明确 Docker 未安装。
6. 已明确 Git 已安装。
7. 已明确规划目录不存在且创建需要 sudo。
