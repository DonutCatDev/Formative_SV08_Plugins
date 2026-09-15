#!/usr/bin/env bash

set -Eeuo pipefail

KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
LEGACY_REPO="${KLIPPER_NETWORK_STATUS_LEGACY_DIR:-$HOME/klipper_network_status}"
LEGACY_MODULE="$KLIPPER_DIR/klippy/extras/network_status.py"
PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
remove_module=0

[[ "$LEGACY_REPO" == /* ]] || {
    printf 'Refusing non-absolute legacy repository path: %s\n' "$LEGACY_REPO" >&2
    exit 1
}
[[ "${LEGACY_REPO##*/}" == klipper_network_status ]] || {
    printf 'Refusing unexpected legacy repository name: %s\n' "$LEGACY_REPO" >&2
    exit 1
}
[[ ! -L "$LEGACY_REPO" ]] || {
    printf 'Refusing symlinked legacy repository path: %s\n' "$LEGACY_REPO" >&2
    exit 1
}

legacy_repo_resolved="$(readlink -m "$LEGACY_REPO")"
if [[ -e "$LEGACY_MODULE" && ! -L "$LEGACY_MODULE" ]]; then
    printf 'Refusing to remove non-symlink Klipper module: %s\n' "$LEGACY_MODULE" >&2
    exit 1
fi
if [[ -L "$LEGACY_MODULE" ]]; then
    module_target="$(readlink -m "$LEGACY_MODULE")"
    case "$module_target" in
        "$legacy_repo_resolved"/*) remove_module=1 ;;
        "$PLUGIN_DIR/klippy/extras/network_status.py")
            # The replacement is installed; preserve its owned module link.
            ;;
        *)
            printf 'Refusing legacy link with unexpected target: %s -> %s\n' \
                "$LEGACY_MODULE" "$module_target" >&2
            exit 1
            ;;
    esac
fi

if [[ -e "$LEGACY_REPO" && ! -d "$LEGACY_REPO" ]]; then
    printf 'Refusing non-directory legacy repository path: %s\n' "$LEGACY_REPO" >&2
    exit 1
fi
if [[ -d "$LEGACY_REPO" && ! -d "$LEGACY_REPO/.git" ]]; then
    printf 'Refusing directory that is not a Git repository: %s\n' "$LEGACY_REPO" >&2
    exit 1
fi

changed=0
if ((remove_module)); then
    unlink "$LEGACY_MODULE"
    printf 'Removed legacy module link: %s\n' "$LEGACY_MODULE"
    changed=1
fi
if [[ -d "$LEGACY_REPO" ]]; then
    rm -rf -- "$LEGACY_REPO"
    printf 'Removed legacy repository: %s\n' "$LEGACY_REPO"
    changed=1
fi

if ((changed)); then
    printf 'Legacy network_status installation removed. Install network_status next.\n'
else
    printf 'No legacy network_status installation found.\n'
fi
