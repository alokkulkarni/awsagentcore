#!/usr/bin/env bash
# Installs the deployment-playbook skill to various locations
# Usage: ./install.sh [--global] [--project] [--all]

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="deployment-playbook"

install_project() {
    local target="${1:-.}/.agents/skills/$SKILL_NAME"
    mkdir -p "$target"
    if [ "$(cd "$target" && pwd)" = "$SKILL_DIR" ]; then
        echo "✓ Already installed to project: $target"
        return
    fi
    cp -r "$SKILL_DIR/." "$target/"
    echo "✓ Installed to project: $target"
}

install_global() {
    local target="$HOME/.agents/skills/$SKILL_NAME"
    mkdir -p "$target"
    if [ "$(cd "$target" && pwd)" = "$SKILL_DIR" ]; then
        echo "✓ Already installed globally: $target"
        return
    fi
    cp -r "$SKILL_DIR/." "$target/"
    echo "✓ Installed globally: $target"
}

case "${1:---project}" in
    --global) install_global ;;
    --project) install_project ;;
    --all) install_project; install_global ;;
    *) echo "Usage: $0 [--project] [--global] [--all]"; exit 1 ;;
esac
