#!/usr/bin/env bash
# Run as root on the NAS. Never source .env as executable shell code.
set -Eeuo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v flock >/dev/null || { echo "flock is required" >&2; exit 1; }
exec 9>.update.lock
flock -n 9 || { echo "Another update is running; skipped."; exit 0; }
mkdir -p logs
exec > >(tee -a "logs/update-$(date +%F).log") 2>&1
log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*"; }
trap 'log "Update failed at line $LINENO. Inspect logs; data was not automatically restored."' ERR
compose() { docker compose --project-name fitlog-nas --env-file .env -f compose.yml "$@"; }
[[ -f .env ]] || { log "Missing .env"; exit 1; }
[[ ! -f .update-failed ]] || { log "Previous update failed. Resolve it and remove .update-failed before retrying."; exit 1; }
compose config --quiet
container=$(compose ps -a -q fitlog)
[[ -n "$container" ]] || { log "Complete the initial Compose migration before scheduling updates."; exit 1; }
health=$(docker inspect --format '{{.State.Health.Status}}' "$container")
[[ "$health" == healthy ]] || { log "Current container is not healthy; refusing unattended update."; exit 1; }
old_image=$(docker inspect --format '{{.Image}}' "$container")
compose pull fitlog
image=$(compose config --images)
new_image=$(docker image inspect --format '{{.Id}}' "$image")
if [[ "$old_image" == "$new_image" ]]; then
  log "Image unchanged; container left running."
  exit 0
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
rollback="fitlog-rollback:$stamp"
docker image tag "$old_image" "$rollback"
log "New image found. Backing up SQLite before replacement."
compose exec -T fitlog python - "$stamp" <<'PY'
import sqlite3, sys
from pathlib import Path
from contextlib import closing
root = Path('/app/data')
source = root / 'fitlog.db'
if not source.is_file():
    raise SystemExit('Expected SQLite database is missing; update cancelled')
target = root / 'backups' / ('before-auto-update-' + sys.argv[1] + '.db')
target.parent.mkdir(exist_ok=True)
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30)) as src:
    with closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Backup integrity check failed')
print('Verified backup:', target)
PY
# Latch survives interruption during recreation; no unattended retry after failure.
printf 'previous_image=%s\nbackup=before-auto-update-%s.db\n' "$rollback" "$stamp" > .update-failed
if compose up -d --no-deps --no-build --pull never --wait --wait-timeout 120 fitlog; then
  rm -- .update-failed
  log "Update healthy. Previous image retained as $rollback."
else
  log "New version failed health checks; automatic updates paused."
  log "Previous image: $rollback; backup: data/backups/before-auto-update-$stamp.db"
  log "No automatic downgrade or database restore: a new schema may be incompatible."
  exit 1
fi
