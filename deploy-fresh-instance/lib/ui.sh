# deploy-fresh-instance: how each step talks to you. Sourced by deploy.sh.
#   banner   the step's number, phase and title
#   about    what the step makes and why (shown before anything runs)
#   will     the command(s) it is about to run
#   go       [y]es / [s]kip / [q]uit; a skip sets SKIPPED=true and returns 1 (steps do `go || return 0`)
#   console  a pause for something only a console can give you, with numbered directions
#   secret   read a value without echoing it (it goes to the helper's stdin, never the command line)

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; BLUE=$'\033[0;34m'; RESET=$'\033[0m'
ASSUME_YES=${ASSUME_YES:-false}

banner() {   # banner <n> <total> <phase> <title>
    echo
    echo "${BOLD}${BLUE}━━━ Step $1 of $2 · $3 ━━━${RESET}"
    echo "${BOLD}$4${RESET}"
}

about() { while [[ $# -gt 0 ]]; do echo "  $1"; shift; done; }

will() {
    echo "${DIM}  Will run:${RESET}"
    while [[ $# -gt 0 ]]; do echo "${DIM}    \$ $1${RESET}"; shift; done
}

go() {
    if $ASSUME_YES; then return 0; fi
    local answer
    while true; do
        read -r -p "${CYAN}  Run this step? [y]es / [s]kip / [q]uit: ${RESET}" answer </dev/tty
        case "${answer,,}" in
            y|yes) return 0 ;;
            s|skip) SKIPPED=true; echo "${YELLOW}  Skipped. Later steps that need what it makes will say so.${RESET}"; return 1 ;;
            q|quit) echo "  Stopped. Carry on later with: ./deploy.sh --config ${CONFIG} --from ${CURRENT_STEP}"; exit 0 ;;
        esac
    done
}

yesno() {   # yesno "question" → 0 for yes (never assumed: --yes doesn't answer these)
    local answer
    read -r -p "${CYAN}  $1 [y/N]: ${RESET}" answer </dev/tty
    [[ "${answer,,}" == y || "${answer,,}" == yes ]]
}

ask() {   # ask VAR "prompt" [default]
    local value
    read -r -p "${CYAN}  $2${3:+ [$3]}: ${RESET}" value </dev/tty
    printf -v "$1" '%s' "${value:-${3:-}}"
}

secret() {   # secret VAR "prompt"
    local value
    read -r -s -p "${CYAN}  $2 (hidden): ${RESET}" value </dev/tty
    echo
    printf -v "$1" '%s' "$value"
}

console() {   # console "title" "1. ..." "2. ..."
    echo
    echo "${YELLOW}${BOLD}  ▶ Your turn, in a console: $1${RESET}"
    shift
    while [[ $# -gt 0 ]]; do echo "${YELLOW}    $1${RESET}"; shift; done
    echo
}

ok()   { echo "${GREEN}[ OK ] $*${RESET}"; }
info() { echo "${CYAN}[....] $*${RESET}"; }
warn() { echo "${YELLOW}[WARN] $*${RESET}"; }
die()  { echo "${RED}[FAIL] $*${RESET}" >&2; exit 1; }
