#!/usr/bin/env bash
set -euo pipefail

MUZTOOLS_DIR="${MUZTOOLS_DIR:-/srv/muz-tool}"
MUZTOOLS_DATA="${MUZTOOLS_DATA:-$MUZTOOLS_DIR/data}"
MUZTOOLS_VENV="${MUZTOOLS_VENV:-$MUZTOOLS_DIR/backend/.venv}"

cat >/usr/local/bin/muz-admin <<SH
#!/usr/bin/env bash
export MUZTOOLS_DATA="\${MUZTOOLS_DATA:-$MUZTOOLS_DATA}"
cd "$MUZTOOLS_DIR/backend"
exec "$MUZTOOLS_VENV/bin/python" -m muztool.cli "\$@"
SH
chmod +x /usr/local/bin/muz-admin
echo "installed /usr/local/bin/muz-admin"
