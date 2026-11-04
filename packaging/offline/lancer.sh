#!/usr/bin/env bash
# Opens the offline register in the browser, served from this folder on this computer only.
#
# A browser refuses a page's own requests (its components, its fonts) on file:// URLs, so
# the site needs a small local web server. This uses python3 when it is really installed,
# else perl, which macOS and Linux ship: nothing to install.
set -u
cd "$(dirname "$0")/.." || exit 1
SITE="$PWD/site"

is_listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

free_port() {
    local port
    for port in $(seq 8000 8019); do
        is_listening "$port" || { echo "$port"; return 0; }
    done
    return 1
}

has_python() {
    command -v python3 >/dev/null 2>&1 || return 1
    # On a Mac without the developer tools, /usr/bin/python3 is a stub whose first run
    # opens an installation prompt: never call it there.
    if [ "$(uname)" = Darwin ] && [ "$(command -v python3)" = /usr/bin/python3 ] &&
        ! xcode-select -p >/dev/null 2>&1; then
        return 1
    fi
    python3 -c "import http.server" >/dev/null 2>&1
}

open_when_ready() {
    local url=$1 tries=0
    until is_listening "$PORT"; do
        tries=$((tries + 1))
        [ "$tries" -gt 100 ] && return 1
        sleep 0.1
    done
    if command -v open >/dev/null 2>&1; then open "$url"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1
    fi
}

if [ ! -f "$SITE/index.html" ]; then
    echo "Dossier « site » introuvable à côté de ce fichier : décompressez toute l'archive."
    exit 1
fi
PORT=$(free_port) || { echo "Aucun port libre entre 8000 et 8019."; exit 1; }
URL="http://127.0.0.1:$PORT/"

echo "Registre IA 2027 — hors ligne"
echo "Adresse : $URL"
echo "Laissez cette fenêtre ouverte pendant la consultation ; fermez-la (ou Ctrl+C) pour arrêter."
open_when_ready "$URL" &

if has_python; then
    exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SITE" 2>/dev/null
elif command -v perl >/dev/null 2>&1; then
    exec perl "$PWD/outils/serveur.pl" "$SITE" "$PORT"
fi
echo "Ni python3 ni perl sur cet ordinateur : voir LISEZ-MOI.txt."
exit 1
