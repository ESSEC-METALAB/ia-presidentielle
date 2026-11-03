#!/usr/bin/env bash
# Installs, removes or shows the daily schedule on THIS machine:
#   - the morning update (scripts/daily.sh) every day at $DAILY_TIME (default 08:00,
#     local time); a run missed while the machine was asleep or off runs at wake-up;
#   - the local site server (scripts/serve.sh), started at login and restarted if it stops.
#
# Usage: scripts/schedule.sh install|uninstall|status [--dry-run]
#   macOS: launchd agents in ~/Library/LaunchAgents
#   Linux: systemd user units in ~/.config/systemd/user (timer with Persistent=true);
#          without systemd, a crontab entry (a missed 08:00 is then skipped, not caught up)
#   Windows: run it inside WSL (Ubuntu); see README.
# --dry-run prints what would be written and changes nothing.
# SCHEDULER=launchd|systemd|cron forces a scheduler instead of the one detected.
set -euo pipefail

ACTION=${1:-status}
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DAILY_TIME=${DAILY_TIME:-$({ grep -E '^DAILY_TIME=' "$ROOT/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'; } || true)}
DAILY_TIME=${DAILY_TIME:-08:00}
HOUR=$((10#${DAILY_TIME%%:*}))
MINUTE=$((10#${DAILY_TIME##*:}))
LABEL=edu.essec.metalab.observatoire
UV_DIR=$(dirname "$(command -v uv 2>/dev/null || echo /usr/local/bin/uv)")
PATH_FOR_JOBS="$UV_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

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

# --- macOS: launchd --------------------------------------------------------------------
launchd_dir="$HOME/Library/LaunchAgents"

launchd_plist() {  # launchd_plist NAME SCRIPT KIND(calendar|keepalive)
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL.$1</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/scripts/$2</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH_FOR_JOBS</string></dict>
  <key>StandardOutPath</key><string>$ROOT/data/logs/launchd-$1.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/logs/launchd-$1.log</string>
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

launchd() {
    local domain name script kind
    domain="gui/$(id -u)"
    case $ACTION in
    install)
        mkdir -p "$ROOT/data/logs"
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
        write "$systemd_dir/observatoire-daily.service" <<EOF
[Unit]
Description=Observatoire IA 2027 : mise à jour quotidienne du registre

[Service]
Type=oneshot
WorkingDirectory=$ROOT
Environment=PATH=$PATH_FOR_JOBS
ExecStart=/bin/bash $ROOT/scripts/daily.sh
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
ExecStart=/bin/bash $ROOT/scripts/serve.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
        run systemctl --user daemon-reload
        run systemctl --user enable --now observatoire-daily.timer observatoire-site.service
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
    local current
    current=$(crontab -l 2>/dev/null | grep -v "$TAG" || true)
    case $ACTION in
    install)
        {
            [[ -n "$current" ]] && echo "$current"
            echo "$MINUTE $HOUR * * * PATH=$PATH_FOR_JOBS /bin/bash $ROOT/scripts/daily.sh >/dev/null 2>&1 $TAG"
            echo "@reboot PATH=$PATH_FOR_JOBS /bin/bash $ROOT/scripts/serve.sh >/dev/null 2>&1 $TAG"
        } |
            if ((DRY_RUN)); then cat; else crontab - && echo "crontab mise à jour"; fi
        echo "Sans systemd, une exécution manquée (machine éteinte à $DAILY_TIME) n'est pas rattrapée." ;;
    uninstall)
        if ((DRY_RUN)); then echo "$current"; else echo "$current" | crontab -; fi ;;
    status)
        crontab -l 2>/dev/null | grep "$TAG" || echo "aucune tâche installée" ;;
    esac
}

case $ACTION in install | uninstall | status) ;; *)
    echo "usage : $0 install|uninstall|status [--dry-run]" >&2
    exit 2 ;;
esac

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
