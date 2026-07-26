#!/bin/sh
set -eu

release_dir="${AIOPS_RELEASE_DIR:-/home/yvesyuan/jscn-aiops-releases/20260717-161200}"
migration_file="${1:?migration SQL file is required}"

cd "$release_dir"
set -a
. runtime/app.env
set +a
export MYSQL_PWD="$MYSQL_PASSWORD"

mysql_args="-h $MYSQL_HOST -P $MYSQL_PORT -u $MYSQL_USER $MYSQL_DATABASE"
# shellcheck disable=SC2086
mysql $mysql_args -e 'CREATE TABLE IF NOT EXISTS ai_findings_backup_20260719 LIKE ai_findings'
# shellcheck disable=SC2086
backup_rows=$(mysql -N $mysql_args -e 'SELECT COUNT(*) FROM ai_findings_backup_20260719')
if [ "$backup_rows" = "0" ]; then
  # shellcheck disable=SC2086
  mysql $mysql_args -e 'INSERT INTO ai_findings_backup_20260719 SELECT * FROM ai_findings'
fi
# shellcheck disable=SC2086
mysql $mysql_args < "$migration_file"
# shellcheck disable=SC2086
mysql -N $mysql_args -e 'SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME="ai_findings" AND COLUMN_NAME="device_ip"; SELECT COUNT(*) FROM ai_findings_backup_20260719'

unset MYSQL_PWD
