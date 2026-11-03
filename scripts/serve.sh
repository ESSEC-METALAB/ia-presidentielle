#!/usr/bin/env bash
# Serves the register site (data/site) on this machine only: http://localhost:$SITE_PORT
#
# The site needs no internet access: every script and font is bundled
# (web/registre/NOTICE.md). It is served rather than opened as a file because browsers
# block a page's own requests (its components, its data) on file:// URLs.
#
# If there is no site yet, it waits for the first build instead of exiting, so a
# supervisor (launchd, systemd) does not restart it in a loop.
# --if-down: exit at once if something already answers on the port (used by cron).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/env.sh
source scripts/env.sh

PORT=$(env_value SITE_PORT 8000)
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || ((PORT < 1 || PORT > 65535)); then
    echo "SITE_PORT invalide dans .env : « $PORT »" >&2
    exit 2
fi

if [[ "${1:-}" == "--if-down" ]] &&
    python3 -c "import socket,sys; socket.create_connection(('127.0.0.1', int(sys.argv[1])), 1)" "$PORT" 2>/dev/null; then
    exit 0
fi

if [[ ! -f data/site/index.html ]]; then
    echo "Pas encore de site : en attente de « make site » ou de la première mise à jour…"
    until [[ -f data/site/index.html ]]; do sleep 60; done
fi
echo "Registre servi sur http://localhost:$PORT (Ctrl+C pour arrêter)"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory data/site
