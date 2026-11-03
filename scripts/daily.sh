#!/usr/bin/env bash
# The morning update: collect, segment, annotate, watch, rebuild the site.
#
# Run by `make daily`, and every day at 08:00 by the schedule `make schedule` installs.
# A failed step is logged and the next ones still run: a source that is down must not
# leave yesterday's site in place of today's. The run fails (exit 1) only if the site
# could not be rebuilt.
#
# Settings, read from .env (all optional):
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

LOG="data/logs/daily-$(date +%Y-%m-%d).log"
exec > >(tee -a "$LOG") 2>&1

# How to call the CLI. RUN="" uses an activated virtualenv directly.
read -r -a RUN_PREFIX <<<"${RUN-uv run --extra dev}"

# shellcheck disable=SC2329  # called through step
obs() {  # obs ARGS...: the observatoire CLI (bash 3.2 on macOS: no empty "${a[@]}" under -u)
    if ((${#RUN_PREFIX[@]})); then "${RUN_PREFIX[@]}" observatoire "$@"; else observatoire "$@"; fi
}
LOCK=data/.daily.lock

env_value() {  # env_value KEY DEFAULT: the process environment first, then .env
    local value="${!1:-}"
    if [[ -z "$value" && -f .env ]]; then
        value=$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d '"'"'"'\r')
    fi
    echo "${value:-$2}"
}

# One run at a time: two writers on one SQLite file corrupt it. mkdir is atomic, and
# works on macOS, which has no flock. A lock left by a killed run is detected by its PID.
if ! mkdir "$LOCK" 2>/dev/null; then
    if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then
        echo "$(date '+%F %T') une mise à jour tourne déjà (PID $(cat "$LOCK/pid")) : abandon"
        exit 0
    fi
    rm -rf "$LOCK" && mkdir "$LOCK"
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
    git fetch --quiet origin daily &&
        git show origin/daily:data/observatoire.db >data/raw/legacy-daily.db &&
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
step collect obs collect
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
exit $((SITE == 0 ? 0 : 1))
