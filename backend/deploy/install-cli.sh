#!/usr/bin/env bash
set -euo pipefail

MUZTOOLS_DIR="${MUZTOOLS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
MUZTOOLS_DATA="${MUZTOOLS_DATA:-$MUZTOOLS_DIR/data}"
MUZTOOLS_VENV="${MUZTOOLS_VENV:-$MUZTOOLS_DIR/backend/.venv}"

for command_name in muz-admin muzadmin; do
  cat >"/usr/local/bin/$command_name" <<SH
#!/usr/bin/env bash
export MUZTOOLS_DATA="\${MUZTOOLS_DATA:-$MUZTOOLS_DATA}"
cd "$MUZTOOLS_DIR/backend"
exec "$MUZTOOLS_VENV/bin/python" -m muztool.cli "\$@"
SH
  chmod +x "/usr/local/bin/$command_name"
done
echo "installed /usr/local/bin/muz-admin and /usr/local/bin/muzadmin"
