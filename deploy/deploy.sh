#!/usr/bin/env bash
# Receives a short-lived GHCR token on stdin. Never enable shell tracing.
set -Eeuo pipefail
umask 077
APP=navigation-page
APP_ROOT="/opt/cjw-sites/$APP"
RELEASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ACTOR="${1:?GitHub actor required}"
[[ "$ACTOR" =~ ^[A-Za-z0-9-]+$ ]] || exit 2
[[ "$RELEASE_DIR" == "$APP_ROOT/releases/"* ]] || exit 2
[[ -f "$APP_ROOT/READY" ]] || { echo 'Initial server setup is not complete.' >&2; exit 2; }
exec 9>"$APP_ROOT/deploy.lock"
flock -w 600 9
python3 - "$RELEASE_DIR/images.env" <<'PY'
import re, sys
lines = open(sys.argv[1]).read().splitlines()
expected = {'WEB_IMAGE': 'ghcr.io/cjw260/navigation-page-web', 'ADMIN_IMAGE': 'ghcr.io/cjw260/navigation-page-admin'}
found = {}
for line in lines:
    key, sep, value = line.partition('=')
    if not sep or key not in expected or key in found:
        raise SystemExit('Invalid image manifest')
    if not re.fullmatch(re.escape(expected[key]) + r'@sha256:[a-f0-9]{64}', value):
        raise SystemExit('Image must use the expected repository and an immutable digest')
    found[key] = value
if set(found) != set(expected):
    raise SystemExit('Incomplete image manifest')
PY
previous=''
if [[ -L "$APP_ROOT/current" ]]; then previous="$(readlink -f "$APP_ROOT/current")"; fi
registry_auth="$(mktemp -d)"
export DOCKER_CONFIG="$registry_auth"
trap 'rm -rf -- "$registry_auth"' EXIT
docker login ghcr.io --username "$ACTOR" --password-stdin >/dev/null
compose() {
  local release="$1"; shift
  docker compose --project-name "cjw-$APP" --env-file "$release/images.env" -f "$release/compose.yaml" "$@"
}
# Persistent owner-managed data, separate from immutable releases.
mkdir -p "$APP_ROOT/data/admin/public"
chmod 700 "$APP_ROOT/data/admin"
chmod 755 "$APP_ROOT/data/admin/public"
# Back up SQLite before a new backend version starts. Do not copy a live WAL file.
python3 - "$APP_ROOT/data/admin" <<'PYBACKUP'
from pathlib import Path
import sqlite3,sys,time
p=Path(sys.argv[1]); db=p/'content.sqlite3'
if db.exists():
    (p/'backups').mkdir(exist_ok=True)
    with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as source, sqlite3.connect(p/'backups'/f'deploy-{time.time_ns()}.sqlite3') as target:
        source.backup(target)
PYBACKUP
# Resolve and pull every image before touching existing application containers.
compose "$RELEASE_DIR" config --quiet
compose "$RELEASE_DIR" pull --policy always
if compose "$RELEASE_DIR" up -d --wait --wait-timeout 120 --pull never; then
  if [[ -n "$previous" && "$previous" != "$RELEASE_DIR" ]]; then
    ln -sfn "$previous" "$APP_ROOT/previous.next"
    mv -Tf "$APP_ROOT/previous.next" "$APP_ROOT/previous"
  fi
  ln -sfn "$RELEASE_DIR" "$APP_ROOT/current.next"
  mv -Tf "$APP_ROOT/current.next" "$APP_ROOT/current"
  echo 'Deployment healthy.'
else
  echo 'Health check failed; restoring previous application release.' >&2
  if [[ -n "$previous" ]]; then
    compose "$previous" up -d --wait --wait-timeout 120 --pull never || {
      echo 'Rollback failed. Manual intervention required.' >&2; exit 2;
    }
    # A pre-admin release cannot use this service; stop it without deleting data.
    if ! grep -q '^ADMIN_IMAGE=' "$previous/images.env"; then
      compose "$RELEASE_DIR" stop admin
    fi
  else
    compose "$RELEASE_DIR" down # Application containers only; persistent volumes retained.
  fi
  exit 1
fi
