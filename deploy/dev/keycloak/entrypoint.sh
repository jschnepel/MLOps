#!/bin/bash
# Export the bootstrap admin password as KC_BOOTSTRAP_ADMIN_PASSWORD (Keycloak has no *_FILE variants, T05) and every
# other /run/secrets/kc_* file as OPS_<UPPER-CASED NAME>, outside Keycloak's KC_* option namespace. The realm import
# resolves ${OPS_KC_*} placeholders from the environment.
# Secret files have no trailing newline (scripts/bootstrap_dev.py), and $(cat ...) would strip one anyway, so the
# exported values match the files byte for byte.
set -euo pipefail
for f in /run/secrets/kc_*; do
  [ -e "$f" ] || continue  # an unmatched glob stays literal; skip it rather than fail on a missing file
  name="$(basename "$f")"
  if [ "$name" = "kc_bootstrap_admin_password" ]; then
    export KC_BOOTSTRAP_ADMIN_PASSWORD="$(cat "$f")"
  else
    export "OPS_${name^^}"="$(cat "$f")"
  fi
done
# exec replaces the shell so Keycloak is PID 1 and receives the stop signal from `docker compose down`.
exec /opt/keycloak/bin/kc.sh start-dev --import-realm
