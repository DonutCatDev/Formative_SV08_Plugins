#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="${FORMATIVE_PLUGINS_REPO_DIR:-$SCRIPT_DIR}"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
CONFIG_DIR="${PRINTER_CONFIG_DIR:-$HOME/printer_data/config}"
RESTART_SERVICES=1

if [[ "${1:-}" == --no-restart ]]; then
    RESTART_SERVICES=0
    shift
fi
if (($#)); then
    printf 'Usage: %s [--no-restart]\n' "${0##*/}" >&2
    exit 2
fi

PLUGIN_ROOT="$REPO_DIR/plugins"
[[ -d "$PLUGIN_ROOT" ]] || { printf 'Plugin directory not found: %s\n' "$PLUGIN_ROOT" >&2; exit 1; }

clear_screen() {
    if [[ -t 1 && -n "${TERM:-}" && "$TERM" != dumb ]]; then
        printf '\033[2J\033[H'
    fi
}

plugin_status() {
    local plugin="$1" source_dir="$PLUGIN_ROOT/$1"
    local payload=0 linked=0 expected=0 source_file target

    if [[ -d "$source_dir/klippy/extras" ]]; then
        while IFS= read -r -d '' source_file; do
            payload=1
            expected=$((expected + 1))
            target="$KLIPPER_DIR/klippy/extras/${source_file##*/}"
            if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source_file")" ]]; then
                linked=$((linked + 1))
            fi
        done < <(find "$source_dir/klippy/extras" -maxdepth 1 -type f -name '*.py' -print0)
    fi
    if [[ -d "$source_dir/config" ]]; then
        payload=1
        expected=$((expected + 1))
        target="$CONFIG_DIR/custom_plugins/$plugin"
        if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source_dir/config")" ]]; then
            linked=$((linked + 1))
        fi
    fi
    if [[ -d "$source_dir/activation" ]]; then
        while IFS= read -r -d '' source_file; do
            payload=1
            expected=$((expected + 1))
            relative_target="${source_file#"$source_dir/activation/"}"
            target="$CONFIG_DIR/$relative_target"
            if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source_file")" ]]; then
                linked=$((linked + 1))
            fi
        done < <(find "$source_dir/activation" -type f -print0)
    fi

    if ((payload == 0)); then
        printf 'planned'
    elif ((linked == expected)); then
        printf 'installed'
    elif ((linked > 0)); then
        printf 'partial'
    else
        printf 'not installed'
    fi
}

pause_menu() {
    printf '\nPress Enter to continue...'
    IFS= read -r _ || true
}

run_install() {
    local plugin="$1" restart_arg=()
    ((RESTART_SERVICES)) || restart_arg+=(--no-restart)
    FORMATIVE_PLUGINS_REPO_DIR="$REPO_DIR" \
    FORMATIVE_PLUGINS_SKIP_UPDATE=1 \
    KLIPPER_DIR="$KLIPPER_DIR" \
    PRINTER_CONFIG_DIR="$CONFIG_DIR" \
        "$REPO_DIR/install-plugins.sh" "${restart_arg[@]}" "$plugin"
}

run_uninstall() {
    local plugin="$1" restart_arg=()
    ((RESTART_SERVICES)) || restart_arg+=(--no-restart)
    FORMATIVE_PLUGINS_REPO_DIR="$REPO_DIR" \
    FORMATIVE_PLUGINS_SKIP_UPDATE=1 \
    KLIPPER_DIR="$KLIPPER_DIR" \
    PRINTER_CONFIG_DIR="$CONFIG_DIR" \
        "$REPO_DIR/install-plugins.sh" --uninstall "${restart_arg[@]}" "$plugin"
}

plugin_menu() {
    local plugin="$1" choice
    while true; do
        clear_screen
        printf '%s\n' '=================================================='
        printf '  Formative SV08 Plugin Manager\n'
        printf '%s\n' '=================================================='
        printf '  Plugin: %s\n' "$plugin"
        printf '  Status: %s\n' "$(plugin_status "$plugin")"
        printf '%s\n' '--------------------------------------------------'
        printf '  1) Install / repair\n'
        printf '  2) Uninstall\n'
        printf '  B) Back\n'
        printf '%s\n' '--------------------------------------------------'
        printf 'Select an action: '
        IFS= read -r choice || return 0
        case "${choice,,}" in
            1|i|install) run_install "$plugin"; pause_menu ;;
            2|u|uninstall|remove) run_uninstall "$plugin"; pause_menu ;;
            b|back|q|quit) return 0 ;;
            *) printf 'Invalid selection: %s\n' "$choice"; pause_menu ;;
        esac
    done
}

while true; do
    mapfile -t plugins < <(find "$PLUGIN_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
    clear_screen
    printf '%s\n' '=================================================='
    printf '  Formative SV08 Plugin Manager\n'
    printf '%s\n' '=================================================='
    if ((${#plugins[@]} == 0)); then
        printf '  No plugins are available.\n'
    else
        for index in "${!plugins[@]}"; do
            printf '  %d) %-28s [%s]\n' "$((index + 1))" "${plugins[$index]}" "$(plugin_status "${plugins[$index]}")"
        done
    fi
    printf '%s\n' '--------------------------------------------------'
    printf '  Q) Quit\n'
    printf '%s\n' '--------------------------------------------------'
    printf 'Select a plugin: '
    IFS= read -r choice || exit 0
    case "${choice,,}" in
        q|quit|exit) exit 0 ;;
        ''|*[!0-9]*) printf 'Invalid selection: %s\n' "$choice"; pause_menu ;;
        *)
            selection=$((10#$choice - 1))
            if ((selection >= 0 && selection < ${#plugins[@]})); then
                plugin_menu "${plugins[$selection]}"
            else
                printf 'Invalid selection: %s\n' "$choice"
                pause_menu
            fi
            ;;
    esac
done
