#!/usr/bin/env bash
# Entry point of the server's container (Dockerfile): the register on the web.
#
#   1. first start, empty volume: build the register from the previous version's data
#      and the verified edition, without any model call (same steps as `make site`);
#   2. every day at DAILY_TIME (Europe/Paris by default, TZ), the morning update;
#   3. in the foreground, the site and its "Actualiser" button (`observatoire web`).
#
# data/ is the container's volume: the database, the site, the logs and the last refresh
# survive a redeploy.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/raw data/reports data/logs
# shellcheck source=scripts/env.sh
source scripts/env.sh

LEGACY_DB_URL=https://raw.githubusercontent.com/ESSEC-METALAB/ia-presidentielle/daily/data/observatoire.db
RESPONSES=$(env_value ANNOTATION_RESPONSES annotations/2026-11-03-brouillon.jsonl)

bootstrap() {
    echo "$(date '+%F %T') premier démarrage : registre construit depuis la version précédente"
    curl -fsSL -o data/raw/legacy-daily.db "$(env_value LEGACY_DB_URL "$LEGACY_DB_URL")" &&
        observatoire import-legacy --database data/raw/legacy-daily.db &&
        observatoire segment &&
        observatoire annotate --llm recorded --responses "$RESPONSES" &&
        observatoire register --out data/site
}

seconds_until() {  # seconds_until HH:MM: from now to the next HH:MM, local time (TZ)
    local now target
    now=$(date +%s)
    target=$(date -d "today $1" +%s)
    ((target <= now)) && target=$(date -d "tomorrow $1" +%s)
    echo $((target - now))
}

daily_loop() {
    local at
    at=$(env_value DAILY_TIME 08:00)
    while true; do
        sleep "$(seconds_until "$at")"
        scripts/daily.sh >/dev/null 2>&1
    done
}

if [[ ! -f data/observatoire.db ]]; then
    bootstrap >>data/logs/bootstrap.log 2>&1 || echo "échec du premier démarrage : data/logs/bootstrap.log"
fi
daily_loop &
exec observatoire web --port "$(env_value SITE_PORT 8000)"
