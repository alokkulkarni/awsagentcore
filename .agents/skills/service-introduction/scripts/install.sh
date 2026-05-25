#!/usr/bin/env bash
# Installs the service-introduction skill to various locations
# Usage: ./install.sh [--project [PATH]] [--global] [--kiro [PATH]] [--claude [PATH]] [--all] [--copilot [PATH]]

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="service-introduction"
BEGIN_MARKER="<!-- BEGIN service-introduction skill -->"
END_MARKER="<!-- END service-introduction skill -->"

copy_skill() {
    local target="$1"
    mkdir -p "$target"
    if [ "$(cd "$target" && pwd)" = "$SKILL_DIR" ]; then
        echo "✓ Already installed to: $target"
        return
    fi
    cp -R "$SKILL_DIR/." "$target/"
    echo "✓ Installed to: $target"
}

install_project() {
    local base="${1:-.}"
    copy_skill "$base/.agents/skills/$SKILL_NAME"
}

install_global() {
    copy_skill "$HOME/.agents/skills/$SKILL_NAME"
}

install_kiro() {
    local base="${1:-.}"
    copy_skill "$base/.kiro/skills/$SKILL_NAME"
}

install_claude() {
    local base="${1:-.}"
    copy_skill "$base/.claude/skills/$SKILL_NAME"
}

install_copilot() {
    local base="${1:-.}"
    local target_dir="$base/.github"
    local target_file="$target_dir/copilot-instructions.md"
    mkdir -p "$target_dir"
    local temp_file="$target_dir/.service-introduction-fragment"
    {
        printf '%s\n' "$BEGIN_MARKER"
        cat "$SKILL_DIR/SKILL.md"
        printf '%s\n' "$END_MARKER"
    } > "$temp_file"

    if [ -f "$target_file" ] && grep -Fq "$BEGIN_MARKER" "$target_file"; then
        python3 - "$target_file" "$temp_file" <<'PY'
from pathlib import Path
import re
import sys

target = Path(sys.argv[1])
fragment = Path(sys.argv[2]).read_text(encoding='utf-8')
text = target.read_text(encoding='utf-8')
pattern = re.compile(r'<!-- BEGIN service-introduction skill -->.*?<!-- END service-introduction skill -->\n?', re.DOTALL)
updated = pattern.sub(fragment + ('\n' if not fragment.endswith('\n') else ''), text)
if updated == text:
    updated = text.rstrip() + '\n\n' + fragment

target.write_text(updated, encoding='utf-8')
PY
        rm -f "$temp_file"
        echo "✓ Updated Copilot instructions fragment: $target_file"
        return
    fi

    if [ -f "$target_file" ] && [ -s "$target_file" ]; then
        printf '\n' >> "$target_file"
    fi
    cat "$temp_file" >> "$target_file"
    rm -f "$temp_file"
    echo "✓ Installed Copilot instructions fragment: $target_file"
}

if [ $# -eq 0 ]; then
    install_project
    exit 0
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --project)
            shift
            if [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; then
                install_project "$1"
                shift
            else
                install_project
            fi
            ;;
        --global)
            install_global
            shift
            ;;
        --kiro)
            shift
            if [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; then
                install_kiro "$1"
                shift
            else
                install_kiro
            fi
            ;;
        --claude)
            shift
            if [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; then
                install_claude "$1"
                shift
            else
                install_claude
            fi
            ;;
        --copilot)
            shift
            if [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; then
                install_copilot "$1"
                shift
            else
                install_copilot
            fi
            ;;
        --all)
            install_project
            install_global
            install_kiro
            install_claude
            shift
            ;;
        *)
            echo "Usage: $0 [--project [PATH]] [--global] [--kiro [PATH]] [--claude [PATH]] [--all] [--copilot [PATH]]"
            exit 1
            ;;
    esac
done
