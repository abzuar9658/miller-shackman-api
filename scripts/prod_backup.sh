#!/usr/bin/env bash
# Nightly Postgres backups to S3. Runs on the EC2 host via crontab:
#   0 3 * * * /opt/miller-schackman/scripts/prod_backup.sh >> /var/log/miller-schackman-backup.log 2>&1
# Requires: docker compose stack running, AWS CLI on the host, EC2 instance
# role with s3:PutObject on the backups bucket, BACKUPS_BUCKET exported below.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/miller-schackman}"
BACKUPS_BUCKET="${BACKUPS_BUCKET:?Set BACKUPS_BUCKET to the S3 backups bucket name}"
DATE="$(date -u +%Y-%m-%d)"
STAMP="$(date -u +%H%M%S)"

cd "$COMPOSE_DIR"

compose() {
    docker compose -f compose.prod.yaml "$@"
}

backup_database() {
    local service="$1" user="$2" db="$3" label="$4"
    local file="/tmp/${label}-${DATE}-${STAMP}.dump.gz"
    echo "[$(date -u +%FT%TZ)] dumping ${label}..."
    compose exec -T "$service" pg_dump -Fc -U "$user" "$db" | gzip > "$file"
    # An empty/near-empty dump means pg_dump silently produced nothing;
    # fail loudly instead of uploading a useless backup.
    local size
    size="$(wc -c < "$file")"
    if [ "$size" -lt 1024 ]; then
        echo "[$(date -u +%FT%TZ)] ERROR: ${label} dump is only ${size} bytes — aborting." >&2
        rm -f "$file"
        exit 1
    fi
    aws s3 cp "$file" "s3://${BACKUPS_BUCKET}/postgres/${DATE}/$(basename "$file")" --only-show-errors
    rm -f "$file"
    echo "[$(date -u +%FT%TZ)] ${label} backup uploaded (${size} bytes)."
}

# App database credentials come from the compose .env file.
set -a
# shellcheck disable=SC1091
source .env
set +a

backup_database postgres "${POSTGRES_USER}" "${POSTGRES_DB}" app
backup_database temporal-postgres temporal temporal temporal

echo "[$(date -u +%FT%TZ)] backup run complete."
