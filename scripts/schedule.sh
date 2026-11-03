#!/usr/bin/env bash
# Installs, removes or shows the daily schedule on THIS machine:
#   - the morning update (scripts/daily.sh) every day at $DAILY_TIME (default 08:00,
#     local time);
#   - the local site server (scripts/serve.sh), started now and kept running.
#
# Usage: scripts/schedule.sh install|uninstall|status [--dry-run]
#   macOS: launchd agents in ~/Library/LaunchAgents. A run missed while the Mac was
#          asleep runs at wake-up; one missed while it was shut down is skipped.
#   Linux: systemd user units in ~/.config/systemd/user; Persistent=true also catches up
#          a run missed while the machine was off.
#   Otherwise (WSL without systemd…): crontab; a missed run is skipped, and the server
#          is checked every 10 minutes and started if it is down.
#   Windows: run it inside WSL (Ubuntu); see README.
# --dry-run prints what would be written and changes nothing.
# SCHEDULER=launchd|systemd|cron forces a scheduler instead of the one detected.
set -euo pipefail

ACTION=${1:-status}
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1
case $ACTION in install | uninstall | status) ;; *)
    echo "usage : $0 install|uninstall|status [--dry-run]" >&2
    exit 2 ;;
esac

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh

DAILY_TIME=$(env_value DAILY_TIME 08:00)
if ! [[ "$DAILY_TIME" =~ ^([01]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then
    echo "DAILY_TIME invalide dans .env : « $DAILY_TIME » (attendu HH:MM)" >&2
    exit 2
fi
HOUR=$((10#${BASH_REMATCH[1]}))
MINUTE=$((10#${BASH_REMATCH[2]}))
LABEL=edu.essec.metalab.observatoire

# How the jobs run the CLI: through uv, or straight from a pip-installed .venv.
JOB_RUN=""
if command -v uv >/dev/null; then
    PATH_FOR_JOBS="$(dirname "$(command -v uv)"):/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    JOB_RUN="uv run --extra dev"
elif [[ -x "$ROOT/.venv/bin/observatoire" ]]; then
    PATH_FOR_JOBS="$ROOT/.venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
elif [[ $ACTION == install ]]; then
    echo "Ni uv ni .venv/bin/observatoire : lancez d'abord « make install » (ou « make install-pip »)." >&2
    exit 1
else
    PATH_FOR_JOBS="/usr/local/bin:/usr/bin:/bin"
fi

write() {  # write PATH: content from stdin, or printed with --dry-run
    if ((DRY_RUN)); then
        echo "----- $1"
        cat
    else
        mkdir -p "$(dirname "$1")"
        cat >"$1"
        echo "écrit : $1"
    fi
}

run() {  # run COMMAND...: executed, or printed with --dry-run
    if ((DRY_RUN)); then echo "+ $*"; else "$@"; fi
}

first_build() {  # a server with nothing to serve would only wait: build the site once now
    if [[ ! -f "$ROOT/data/site/index.html" ]]; then
        echo "Pas encore de site : première mise à jour maintenant (une à deux minutes)…"
        run env RUN="$JOB_RUN" PATH="$PATH_FOR_JOBS" /bin/bash "$ROOT/scripts/daily.sh" || true
    fi
}

xml() {  # xml TEXT: escaped for a plist string
    local text=${1//&/&amp;}
    text=${text//</&lt;}
    printf '%s' "${text//>/&gt;}"
}

# --- macOS: launchd --------------------------------------------------------------------
launchd_dir="$HOME/Library/LaunchAgents"

launchd_plist() {  # launchd_plist NAME SCRIPT KIND(calendar|keepalive)
    local root
    root=$(xml "$ROOT")
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL.$1</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$root/scripts/$2</string></array>
  <key>WorkingDirectory</key><string>$root</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$(xml "$PATH_FOR_JOBS")</string>
    <key>RUN</key><string>$JOB_RUN</string>
  </dict>
  <key>StandardOutPath</key><string>$root/data/logs/launchd-$1.log</string>
  <key>StandardErrorPath</key><string>$root/data/logs/launchd-$1.log</string>
EOF
    if [[ $3 == calendar ]]; then
        echo "  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>"
    else
        echo "  <key>RunAtLoad</key><true/>"
        echo "  <key>KeepAlive</key><true/>"
    fi
    echo "</dict>"
    echo "</plist>"
}

refuse_protected_folder() {
    # Since Catalina, a launchd job cannot read these folders without Full Disk Access,
    # and nothing tells the user: every run would fail with "Operation not permitted".
    local protected
    for protected in Documents Desktop Downloads "Library/Mobile Documents"; do
        if [[ "$ROOT/" == "$HOME/$protected/"* ]]; then
            echo "Le dépôt est dans ~/$protected, que macOS interdit aux tâches planifiées." >&2
            echo "Déplacez-le (par exemple : mv \"$ROOT\" ~/ia-presidentielle), puis relancez." >&2
            exit 1
        fi
    done
}

launchd() {
    local domain name script kind
    domain="gui/$(id -u)"
    case $ACTION in
    install)
        refuse_protected_folder
        mkdir -p "$ROOT/data/logs"
        first_build
        for job in "daily daily.sh calendar" "site serve.sh keepalive"; do
            read -r name script kind <<<"$job"
            launchd_plist "$name" "$script" "$kind" | write "$launchd_dir/$LABEL.$name.plist"
            run launchctl bootout "$domain/$LABEL.$name" 2>/dev/null || true
            run launchctl bootstrap "$domain" "$launchd_dir/$LABEL.$name.plist"
        done ;;
    uninstall)
        for name in daily site; do
            run launchctl bootout "$domain/$LABEL.$name" 2>/dev/null || true
            run rm -f "$launchd_dir/$LABEL.$name.plist"
        done ;;
    status)
        launchctl list | grep "$LABEL" || echo "aucune tâche installée" ;;
    esac
}

# --- Linux: systemd user units ---------------------------------------------------------
systemd_dir="$HOME/.config/systemd/user"

systemd() {
    case $ACTION in
    install)
        first_build
        write "$systemd_dir/observatoire-daily.service" <<EOF
[Unit]
Description=Observatoire IA 2027 : mise à jour quotidienne du registre

[Service]
Type=oneshot
WorkingDirectory=$ROOT
Environment="PATH=$PATH_FOR_JOBS" "RUN=$JOB_RUN"
ExecStart=/bin/bash "$ROOT/scripts/daily.sh"
EOF
        write "$systemd_dir/observatoire-daily.timer" <<EOF
[Unit]
Description=Observatoire IA 2027 : tous les jours à $DAILY_TIME

[Timer]
OnCalendar=*-*-* $(printf '%02d:%02d' "$HOUR" "$MINUTE"):00
# A run missed while the machine was off runs at the next boot.
Persistent=true

[Install]
WantedBy=timers.target
EOF
        write "$systemd_dir/observatoire-site.service" <<EOF
[Unit]
Description=Observatoire IA 2027 : site du registre sur localhost

[Service]
WorkingDirectory=$ROOT
Environment="PATH=$PATH_FOR_JOBS"
ExecStart=/bin/bash "$ROOT/scripts/serve.sh"
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
        run systemctl --user daemon-reload
        run systemctl --user enable --now observatoire-daily.timer observatoire-site.service
        # A second install (new SITE_PORT, moved checkout) must reach the running server.
        run systemctl --user restart observatoire-site.service
        echo "Pour que la tâche tourne sans session ouverte : loginctl enable-linger ${USER:-$(id -un)}" ;;
    uninstall)
        run systemctl --user disable --now observatoire-daily.timer observatoire-site.service || true
        run rm -f "$systemd_dir"/observatoire-{daily.service,daily.timer,site.service}
        run systemctl --user daemon-reload ;;
    status)
        systemctl --user list-timers observatoire-daily.timer --no-pager || true
        systemctl --user status observatoire-site.service --no-pager || true ;;
    esac
}

# --- Fallback: crontab -----------------------------------------------------------------
TAG="# observatoire-ia-2027"

cron() {
    if ! ((DRY_RUN)) && ! command -v crontab >/dev/null; then
        echo "Ni systemd ni crontab : installez cron (sudo apt install cron) ou activez systemd." >&2
        exit 1
    fi
    local current env_prefix
    current=$(crontab -l 2>/dev/null | grep -v "$TAG" || true)
    env_prefix="PATH='$PATH_FOR_JOBS' RUN='$JOB_RUN'"
    case $ACTION in
    install)
        first_build
        {
            [[ -n "$current" ]] && echo "$current"
            echo "$MINUTE $HOUR * * * cd '$ROOT' && $env_prefix /bin/bash scripts/daily.sh >/dev/null 2>&1 $TAG"
            echo "*/10 * * * * cd '$ROOT' && $env_prefix /bin/bash scripts/serve.sh --if-down >>data/logs/serve.log 2>&1 $TAG"
        } | if ((DRY_RUN)); then cat; else crontab - && echo "crontab mise à jour"; fi
        if ! ((DRY_RUN)); then
            nohup /bin/bash "$ROOT/scripts/serve.sh" --if-down >>"$ROOT/data/logs/serve.log" 2>&1 &
        fi
        if ! pgrep -x cron >/dev/null && ! pgrep -x crond >/dev/null; then
            echo "Attention : le service cron ne tourne pas, rien ne se lancera (WSL : sudo service cron start)." >&2
        fi
        echo "Avec cron, une exécution manquée (machine éteinte à $DAILY_TIME) n'est pas rattrapée." ;;
    uninstall)
        if ((DRY_RUN)); then echo "$current"; else echo "$current" | crontab -; fi ;;
    status)
        crontab -l 2>/dev/null | grep "$TAG" || echo "aucune tâche installée" ;;
    esac
}

detect() {
    case "$(uname -s)" in
    Darwin) echo launchd ;;
    Linux)
        if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
            echo systemd
        else
            echo cron
        fi ;;
    *) echo unsupported ;;
    esac
}

case "${SCHEDULER:-$(detect)}" in
launchd) launchd ;;
systemd) systemd ;;
cron) cron ;;
*)
    echo "Système non pris en charge : sous Windows, utilisez WSL (voir README)." >&2
    exit 2 ;;
esac
