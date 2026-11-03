# Sourced by the other scripts: reads one setting the way the Python CLI reads .env.
#
# env_value KEY DEFAULT prints the process environment's value if set, else the last
# `KEY=value` line of .env, else DEFAULT. Like python-dotenv (used by the CLI), it accepts
# `export KEY=value`, single or double quotes, and an unquoted ` # comment` at the end.
# shellcheck shell=bash

env_value() {
    local key=$1 default=$2 value line
    value="${!key:-}"
    if [[ -z "$value" && -f .env ]]; then
        line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" .env | tail -n 1 || true)
        value=${line#*=}
        value=${value%$'\r'}
        case $value in
        \"*\"*) value=${value#\"}; value=${value%%\"*} ;;
        \'*\'*) value=${value#\'}; value=${value%%\'*} ;;
        *) value=${value%%[[:space:]]#*}; value=${value%"${value##*[![:space:]]}"} ;;
        esac
    fi
    printf '%s\n' "${value:-$default}"
}
