#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="sdlc-full"
BEGIN_MARKER="<!-- BEGIN sdlc-full skill -->"
END_MARKER="<!-- END sdlc-full skill -->"
copy_skill() { local t="$1"; mkdir -p "$t"; [ "$(cd "$t" && pwd)" = "$SKILL_DIR" ] && { echo "✓ Already: $t"; return; }; cp -R "$SKILL_DIR/." "$t/"; echo "✓ Installed: $t"; }
install_project() { copy_skill "${1:-.}/.agents/skills/$SKILL_NAME"; }
install_global()  { copy_skill "$HOME/.agents/skills/$SKILL_NAME"; }
install_kiro()    { copy_skill "${1:-$HOME}/.kiro/skills/$SKILL_NAME"; }
install_claude()  { copy_skill "${1:-$HOME}/.claude/skills/$SKILL_NAME"; }
install_copilot() {
  local b="${1:-$HOME}"; local tf="$b/.github/copilot-instructions.md"; mkdir -p "$b/.github"
  local tmp="$b/.github/.${SKILL_NAME}-frag"
  { printf '%s\n' "$BEGIN_MARKER"; cat "$SKILL_DIR/SKILL.md"; printf '%s\n' "$END_MARKER"; } > "$tmp"
  if [ -f "$tf" ] && grep -Fq "$BEGIN_MARKER" "$tf"; then
    SKILL_NAME="$SKILL_NAME" python3 - "$tf" "$tmp" <<'PY'
from pathlib import Path;import re,sys,os
t=Path(sys.argv[1]);f=Path(sys.argv[2]).read_text(encoding='utf-8');s=os.environ['SKILL_NAME']
text=t.read_text(encoding='utf-8');p=re.compile(r'<!-- BEGIN '+re.escape(s)+r' skill -->.*?<!-- END '+re.escape(s)+r' skill -->\n?',re.DOTALL)
t.write_text(p.sub(f+'\n',text),encoding='utf-8')
PY
    rm -f "$tmp"; echo "✓ Updated: $tf"; return
  fi
  [ -f "$tf" ] && [ -s "$tf" ] && printf '\n' >> "$tf"; cat "$tmp" >> "$tf"; rm -f "$tmp"; echo "✓ Appended: $tf"
}
[ $# -eq 0 ] && { install_project; exit 0; }
while [ $# -gt 0 ]; do
  case "$1" in
    --project) shift; [[ $# -gt 0 && ! "$1" =~ ^-- ]] && { install_project "$1"; shift; } || install_project;;
    --global)  install_global; shift;;
    --kiro)    shift; [[ $# -gt 0 && ! "$1" =~ ^-- ]] && { install_kiro "$1"; shift; } || install_kiro;;
    --claude)  shift; [[ $# -gt 0 && ! "$1" =~ ^-- ]] && { install_claude "$1"; shift; } || install_claude;;
    --copilot) shift; [[ $# -gt 0 && ! "$1" =~ ^-- ]] && { install_copilot "$1"; shift; } || install_copilot;;
    --all)     install_project; install_global; install_kiro; install_claude; install_copilot; shift;;
    *)         echo "Usage: $0 [--project [PATH]] [--global] [--kiro] [--claude] [--copilot] [--all]"; exit 1;;
  esac
done
