#!/usr/bin/env bash

set -Eeuo pipefail

REPO_DIR="${FORMATIVE_PLUGINS_REPO_DIR:-$HOME/Formative_SV08_Plugins}"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
CONFIG_DIR="${PRINTER_CONFIG_DIR:-$HOME/printer_data/config}"
RESTART_SERVICES=1
PURGE_UPDATE_MANAGER=0
declare -a REQUESTED=()

usage() {
    printf 'Usage: %s [--no-restart] [--purge-update-manager] [plugin ...]\n' "${0##*/}"
    printf '\nWith no plugin names, uninstalls every plugin in the repository.\n'
    printf 'Only symlinks that still resolve into this repository are removed.\n'
}

while (($#)); do
    case "$1" in
        --no-restart) RESTART_SERVICES=0 ;;
        --purge-update-manager) PURGE_UPDATE_MANAGER=1 ;;
        -h|--help) usage; exit 0 ;;
        --*) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
        *) REQUESTED+=("$1") ;;
    esac
    shift
done

[[ -d "$REPO_DIR/plugins" ]] || { printf 'Plugin repository not found: %s\n' "$REPO_DIR" >&2; exit 1; }
mapfile -t AVAILABLE < <(find "$REPO_DIR/plugins" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
if ((${#REQUESTED[@]} == 0)); then REQUESTED=("${AVAILABLE[@]}"); fi

changed=0
for plugin in "${REQUESTED[@]}"; do
    [[ "$plugin" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { printf 'Invalid plugin name: %s\n' "$plugin" >&2; exit 1; }
    source_dir="$REPO_DIR/plugins/$plugin"
    [[ -d "$source_dir" ]] || { printf 'Unknown plugin: %s\n' "$plugin" >&2; exit 1; }

    if [[ -d "$source_dir/klippy/extras" ]]; then
        while IFS= read -r -d '' source_file; do
            target="$KLIPPER_DIR/klippy/extras/${source_file##*/}"
            if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source_file")" ]]; then
                unlink "$target"
                printf 'Removed link: %s\n' "$target"
                changed=1
            fi
        done < <(find "$source_dir/klippy/extras" -maxdepth 1 -type f -name '*.py' -print0)
    fi

    target="$CONFIG_DIR/custom_plugins/$plugin"
    if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source_dir/config")" ]]; then
        unlink "$target"
        printf 'Removed link: %s\n' "$target"
        changed=1
    fi
done

if ((PURGE_UPDATE_MANAGER)); then
    update_config="$CONFIG_DIR/formative-sv08-plugins-update.conf"
    if [[ -L "$update_config" ]]; then
        printf 'Refusing to remove unexpected symlink: %s\n' "$update_config" >&2
        exit 1
    elif [[ -f "$update_config" ]] && grep -q '^# Managed by install-plugins\.sh\.$' "$update_config"; then
        rm "$update_config"
        printf 'Removed managed Update Manager file: %s\n' "$update_config"
        printf 'The include line in moonraker.conf is retained for manual review.\n'
        changed=1
    fi
fi

if ((changed && RESTART_SERVICES)); then
    if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active klipper.service >/dev/null 2>&1; then
        systemctl --user restart klipper.service
    fi
    if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active moonraker.service >/dev/null 2>&1; then
        systemctl --user restart moonraker.service
    fi
fi

printf 'Plugin uninstall complete. Remove obsolete config include lines manually.\n'
