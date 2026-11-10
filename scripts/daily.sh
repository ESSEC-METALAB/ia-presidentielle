#!/usr/bin/env bash
# The morning update: collect, segment, annotate, watch, rebuild the site.
#
# Run by `make daily`, and every day at 08:00 by the schedule `make schedule` installs.
# A failed step is logged and the next ones still run: a source that is down must not
# leave yesterday's site in place of today's. The run fails (exit 1) only if the site
# could not be rebuilt.
#
# Settings, read from .env like the Python CLI reads it (scripts/env.sh), all optional:
#   LLM_PROVIDER=mistral       annotate new passages with Mistral (needs MISTRAL_API_KEY
#                              and MISTRAL_MODEL); otherwise the recorded answers are
#                              replayed and new passages wait, listed in the watch note
#   DAILY_IMPORT_LEGACY=1      also import what the previous version (branch `daily`,
#                              GitHub Actions) collected; 0 to stop
#   DAILY_GIT_PULL=0           1: `git pull --ff-only` first, to receive config changes
#   ANNOTATION_RESPONSES=...   recorded answers to replay (default: the committed edition)
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
mkdir -p data/logs data/raw data/reports
# shellcheck source=scripts/env.sh
source scripts/env.sh

LOG="data/logs/daily-$(date +%Y-%m-%d).log"
exec > >(tee -a "$LOG") 2>&1

# How to call the CLI. RUN="" uses an activated virtualenv directly.
read -r -a RUN_PREFIX <<<"${RUN-uv run --extra dev}"

# shellcheck disable=SC2329  # called through step
obs() {  # obs ARGS...: the observatoire CLI (bash 3.2 on macOS: no empty "${a[@]}" under -u)
    if ((${#RUN_PREFIX[@]})); then "${RUN_PREFIX[@]}" observatoire "$@"; else observatoire "$@"; fi
}
LOCK=data/.daily.lock
LEGACY_DB_URL=https://raw.githubusercontent.com/ESSEC-METALAB/ia-presidentielle/daily/data/observatoire.db


# One run at a time: two writers on one SQLite file corrupt it. mkdir is atomic, and
# works on macOS, which has no flock. A lock is stale when its PID is gone or is no longer
# a daily run (PIDs are reused); two runs finding the same stale lock race on the mkdir
# that follows its removal, and the loser stops.
if ! mkdir "$LOCK" 2>/dev/null; then
    holder=$(cat "$LOCK/pid" 2>/dev/null || true)
    if [[ -n "$holder" ]] && ps -p "$holder" -o command= 2>/dev/null | grep -q 'daily\.sh'; then
        echo "$(date '+%F %T') une mise à jour tourne déjà (PID $holder) : abandon"
        exit 0
    fi
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || { echo "une autre mise à jour vient de démarrer : abandon"; exit 0; }
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

declare -a SUMMARY=()
step() {  # step NAME COMMAND...: run, time and record one step without stopping the run
    local name=$1 start=$SECONDS status
    shift
    echo
    echo "=== $(date '+%F %T') $name"
    "$@"
    status=$?
    SUMMARY+=("$(printf '%-14s %-6s %4ss' "$name" "$([[ $status -eq 0 ]] && echo ok || echo ÉCHEC)" $((SECONDS - start)))")
    return $status
}

# shellcheck disable=SC2329  # called through step
import_legacy() {
    # Offline, the last fetched copy of the branch is imported again: nothing new, no harm.
    # Without a git checkout (the server's container), the same file is downloaded.
    if git rev-parse --git-dir >/dev/null 2>&1; then
        git fetch --quiet origin daily || echo "git fetch impossible : dernière copie connue de origin/daily"
        git show origin/daily:data/observatoire.db >data/raw/legacy-daily.db || return 1
    else
        curl -fsSL -o data/raw/legacy-daily.db.part "$(env_value LEGACY_DB_URL "$LEGACY_DB_URL")" &&
            mv data/raw/legacy-daily.db.part data/raw/legacy-daily.db ||
            echo "téléchargement impossible : dernière copie connue de la base précédente"
        [[ -f data/raw/legacy-daily.db ]] || return 1
    fi
    obs import-legacy --database data/raw/legacy-daily.db
}

# shellcheck disable=SC2329  # called through step
annotate() {
    if [[ "$(env_value LLM_PROVIDER fake)" == "mistral" ]]; then
        obs annotate --llm mistral
    else
        local responses
        responses=$(env_value ANNOTATION_RESPONSES annotations/2026-11-03-brouillon.jsonl)
        echo "LLM_PROVIDER n'est pas « mistral » : réponses enregistrées rejouées ($responses) ;"
        echo "les nouveaux passages attendent une annotation (voir la veille)."
        obs annotate --llm recorded --responses "$responses"
    fi
}

echo "##### Mise à jour du $(date '+%F %T')"
[[ "$(env_value DAILY_GIT_PULL 0)" == "1" ]] && step git-pull git pull --ff-only
# COLLECT_FULL_WINDOW_ONCE=<label>: the first run with that label reads the social media
# accounts over the whole collection window (`collect --full-window`), then leaves a
# marker so that the next runs read only the last days again.
full_window_marker="data/.full-window-$(env_value COLLECT_FULL_WINDOW_ONCE '')"
if [[ "$full_window_marker" != "data/.full-window-" && ! -e "$full_window_marker" ]]; then
    step collect obs collect --full-window && touch "$full_window_marker"
else
    step collect obs collect
fi
[[ "$(env_value DAILY_IMPORT_LEGACY 1)" == "1" ]] && step import-legacy import_legacy
step segment obs segment
step annotate annotate
step watch obs watch --out data/reports/veille.md
step register obs register --out data/site
SITE=$?
step corpus obs corpus --out data/reports/corpus.html

# Logs older than 30 days go.
find data/logs -name 'daily-*.log' -mtime +30 -delete 2>/dev/null

echo
echo "##### Bilan"
printf '  %s\n' "${SUMMARY[@]}"
echo "  site : data/site/index.html — veille : data/reports/veille.md — journal : $LOG"
# When the register was last updated, whoever asked (schedule or the site's button): the
# date the site shows next to its "Actualiser" button (`observatoire web`).
printf '{"finishedAt": "%s", "exitCode": %d}\n' "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" \
    $((SITE == 0 ? 0 : 1)) >data/last-update.json
exit $((SITE == 0 ? 0 : 1))
