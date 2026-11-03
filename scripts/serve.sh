#!/usr/bin/env bash
# Serves the register site (data/site) on this machine only: http://localhost:$SITE_PORT
# The site needs no internet access: every script and font is bundled (web/registre/NOTICE.md).
# It is served rather than opened as a file because browsers block the page's own
# requests (its components, its data) on file:// URLs.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${SITE_PORT:-$({ grep -E '^SITE_PORT=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'; } || true)}
PORT=${PORT:-8000}
if [[ ! -f data/site/index.html ]]; then
    echo "Pas encore de site : lancez d'abord « make site » ou « make daily »." >&2
    exit 1
fi
echo "Registre servi sur http://localhost:$PORT (Ctrl+C pour arrêter)"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory data/site
