#!/usr/bin/env bash
set -euo pipefail
cat >/usr/local/bin/muz-admin <<'SH'
#!/usr/bin/env bash
export MUZTOOLS_DATA="${MUZTOOLS_DATA:-/root/muz-tool/data}"
cd /root/muz-tool/backend
exec /root/muz-tool/backend/.venv/bin/python -m muztool.cli "$@"
SH
chmod +x /usr/local/bin/muz-admin
echo "installed /usr/local/bin/muz-admin"
