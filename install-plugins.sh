#!/usr/bin/env bash

set -Eeuo pipefail

REPO_URL="${FORMATIVE_PLUGINS_REPO_URL:-https://github.com/DonutCatDev/Formative_SV08_Plugins.git}"
REPO_DIR="${FORMATIVE_PLUGINS_REPO_DIR:-$HOME/Formative_SV08_Plugins}"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
CONFIG_DIR="${PRINTER_CONFIG_DIR:-$HOME/printer_data/config}"
PRIMARY_BRANCH="${FORMATIVE_PLUGINS_PRIMARY_BRANCH:-main}"
RESTART_SERVICES=1
LIST_ONLY=0
INSTALL_ALL=0
MODE=install
PURGE_UPDATE_MANAGER=0
declare -a REQUESTED=()

usage() {
    printf 'Usage: %s [--no-restart] [--list] [--uninstall] [--all | plugin ...]\n' "${0##*/}"
    printf '\nWith no plugin names, opens the interactive plugin manager.\n'
    printf 'Use --uninstall with a plugin name or --all to remove plugins.\n'
    printf 'Use --purge-update-manager with --uninstall to remove its managed file.\n'
    printf '\nEnvironment overrides:\n'
    printf '  FORMATIVE_PLUGINS_REPO_URL       Git repository URL\n'
    printf '  FORMATIVE_PLUGINS_REPO_DIR       Clone destination\n'
    printf '  FORMATIVE_PLUGINS_PRIMARY_BRANCH Moonraker update branch\n'
    printf '  KLIPPER_DIR                       Klipper checkout\n'
    printf '  PRINTER_CONFIG_DIR                Klipper/Moonraker config directory\n'
}

while (($#)); do
    case "$1" in
        --no-restart) RESTART_SERVICES=0 ;;
        --list) LIST_ONLY=1 ;;
        --all) INSTALL_ALL=1 ;;
        --uninstall) MODE=uninstall ;;
        --purge-update-manager) PURGE_UPDATE_MANAGER=1 ;;
        -h|--help) usage; exit 0 ;;
        --*) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
        *) REQUESTED+=("$1") ;;
    esac
    shift
done

for command_name in git ln mkdir grep readlink find sort; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Missing required command: %s\n' "$command_name" >&2
        exit 1
    }
done

if [[ -e "$REPO_DIR" && ! -d "$REPO_DIR/.git" ]]; then
    printf 'Clone destination is not a Git repository: %s\n' "$REPO_DIR" >&2
    exit 1
fi
if [[ -d "$REPO_DIR/.git" ]]; then
    current_origin="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
    if [[ -n "$current_origin" && "$current_origin" != "$REPO_URL" ]]; then
        printf 'Repository origin mismatch at %s\nExpected: %s\nActual:   %s\n' \
            "$REPO_DIR" "$REPO_URL" "$current_origin" >&2
        exit 1
    fi
    if [[ -n "$current_origin" && "${FORMATIVE_PLUGINS_SKIP_UPDATE:-0}" != 1 ]]; then
        git -C "$REPO_DIR" pull --ff-only
    fi
else
    git clone "$REPO_URL" "$REPO_DIR"
fi

PLUGIN_ROOT="$REPO_DIR/plugins"
mapfile -t AVAILABLE < <(find "$PLUGIN_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
if ((LIST_ONLY)); then
    printf '%s\n' "${AVAILABLE[@]}"
    exit 0
fi
if ((${#REQUESTED[@]} == 0 && INSTALL_ALL == 0)); then
    manager_args=()
    ((RESTART_SERVICES)) || manager_args+=(--no-restart)
    exec "$REPO_DIR/plugin-manager.sh" "${manager_args[@]}"
fi
if ((INSTALL_ALL)); then REQUESTED=("${AVAILABLE[@]}"); fi

if [[ "$MODE" == install ]]; then
    [[ -d "$KLIPPER_DIR/klippy/extras" ]] || { printf 'Missing Klipper extras directory: %s\n' "$KLIPPER_DIR/klippy/extras" >&2; exit 1; }
    [[ -d "$CONFIG_DIR" ]] || { printf 'Missing printer config directory: %s\n' "$CONFIG_DIR" >&2; exit 1; }
    mkdir -p "$CONFIG_DIR/custom_plugins"
fi

changed=0
for plugin in "${REQUESTED[@]}"; do
    [[ "$plugin" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { printf 'Invalid plugin name: %s\n' "$plugin" >&2; exit 1; }
    source_dir="$PLUGIN_ROOT/$plugin"
    [[ -d "$source_dir" ]] || { printf 'Unknown plugin: %s\n' "$plugin" >&2; exit 1; }
    if [[ "$MODE" == uninstall ]]; then
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
        continue
    fi

    has_payload=0

    if [[ -d "$source_dir/klippy/extras" ]]; then
        while IFS= read -r -d '' source_file; do
            has_payload=1
            target="$KLIPPER_DIR/klippy/extras/${source_file##*/}"
            if [[ -e "$target" || -L "$target" ]]; then
                if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source_file")" ]]; then
                    printf 'Already linked: %s\n' "$target"
                    continue
                fi
                printf 'Refusing to replace existing Klipper module: %s\n' "$target" >&2
                exit 1
            fi
            ln -s "$source_file" "$target"
            printf 'Linked %s -> %s\n' "$target" "$source_file"
            has_payload=1
            changed=1
        done < <(find "$source_dir/klippy/extras" -maxdepth 1 -type f -name '*.py' -print0)
    fi

    if [[ -d "$source_dir/config" ]]; then
        target="$CONFIG_DIR/custom_plugins/$plugin"
        if [[ -e "$target" || -L "$target" ]]; then
            if [[ ! -L "$target" || "$(readlink -f "$target")" != "$(readlink -f "$source_dir/config")" ]]; then
                printf 'Refusing to replace existing plugin config path: %s\n' "$target" >&2
                exit 1
            fi
            printf 'Already linked: %s\n' "$target"
        else
            ln -s "$source_dir/config" "$target"
            printf 'Linked %s -> %s\n' "$target" "$source_dir/config"
        fi
        has_payload=1
        changed=1
    fi

    ((has_payload)) || printf 'Skipping planned plugin with no runtime payload: %s\n' "$plugin"
done

MOONRAKER_CONFIG="$CONFIG_DIR/moonraker.conf"
if [[ "$MODE" == install ]] && ((changed)) && [[ -f "$MOONRAKER_CONFIG" ]]; then
    UPDATE_CONFIG="$CONFIG_DIR/formative-sv08-plugins-update.conf"
    {
        printf '# Managed by install-plugins.sh.\n'
        printf '[update_manager formative_sv08_plugins]\n'
        printf 'type: git_repo\nchannel: dev\npath: %s\norigin: %s\n' "$REPO_DIR" "$REPO_URL"
        printf 'primary_branch: %s\nmanaged_services: klipper\n' "$PRIMARY_BRANCH"
    } > "$UPDATE_CONFIG"
    if ! grep -Eq '^[[:space:]]*\[include[[:space:]]+formative-sv08-plugins-update\.conf\][[:space:]]*(#.*)?$' "$MOONRAKER_CONFIG"; then
        printf '\n[include formative-sv08-plugins-update.conf]\n' >> "$MOONRAKER_CONFIG"
    fi
fi

if [[ "$MODE" == uninstall && "$PURGE_UPDATE_MANAGER" == 1 ]]; then
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

if [[ "$MODE" == install ]]; then
    printf 'Plugin installation complete. Activate desired config includes explicitly.\n'
else
    printf 'Plugin uninstall complete. Remove obsolete config include lines manually.\n'
fi
