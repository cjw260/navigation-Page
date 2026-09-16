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
expected = {'WEB_IMAGE': 'ghcr.io/cjw260/navigation-page-web'}
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
  else
    compose "$RELEASE_DIR" down # Application containers only; persistent volumes retained.
  fi
  exit 1
fi
