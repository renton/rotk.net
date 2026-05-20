#!/bin/bash
# Runs on first DB init (when /var/lib/mysql is empty). Creates a
# least-privileged application user that the Flask app connects as.
# Root retains DDL privileges for create-all / migrations.
#
# Requires MYSQL_APP_PASSWORD to be set in the container environment
# (see .env / docker-compose.yml).

set -euo pipefail

if [[ -z "${MYSQL_APP_PASSWORD:-}" ]]; then
  echo "MYSQL_APP_PASSWORD is not set; refusing to create app user." >&2
  exit 1
fi

mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
CREATE DATABASE IF NOT EXISTS \`rotk.net\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'rotk_app'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';

GRANT SELECT, INSERT, UPDATE, DELETE ON \`rotk.net\`.* TO 'rotk_app'@'%';

FLUSH PRIVILEGES;
SQL
