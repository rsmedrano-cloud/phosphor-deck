"""phosphor completion - tab completion for bash and zsh.

    phosphor completion bash >> ~/.bashrc      (or a file you source)
    phosphor completion zsh  >> ~/.zshrc

It completes the commands, and after `help` the manual's topics.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import REPO

CMDS = ("doctor init setup panel phone screen gen up attach deck restart down update version note notes fleet "
        "edit shortcuts tabs keep workspace pulse adjutant notify face keys store new mentions clip send web tunnel path privacy run "
        "help docs prom logs trace ci recipe tts demo services glance review push screens")
# the manual's pages, so a new one completes without touching this file
TOPICS = " ".join(sorted(f[:-3] for f in os.listdir(os.path.join(REPO, "doc/manual"))
                         if f.endswith(".md") and f != "README.md"))

BASH = """# phosphor completion (bash) — phosphor completion bash
_phosphor() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD-1]}
    case "$prev" in
        help) COMPREPLY=( $(compgen -W "%(topics)s" -- "$cur") ); return ;;
        web) COMPREPLY=( $(compgen -W "on off status token" -- "$cur") ); return ;;
        tunnel) COMPREPLY=( $(compgen -W "on off" -- "$cur") ); return ;;
        tts) COMPREPLY=( $(compgen -W "install status on off --voice --list" -- "$cur") ); return ;;
        --voice) COMPREPLY=( $(compgen -W "glados adjutant hal synth system" -- "$cur") ); return ;;
        note|notes) COMPREPLY=( $(compgen -W "--kind --by --book --file --tab --here --archive" -- "$cur") ); return ;;
        workspace) COMPREPLY=( $(compgen -W "new open list" -- "$cur") ); return ;;
        --kind) COMPREPLY=( $(compgen -W "note idea decision todo summary" -- "$cur") ); return ;;
        completion) COMPREPLY=( $(compgen -W "bash zsh" -- "$cur") ); return ;;
    esac
    if [ "$COMP_CWORD" = 1 ]; then
        COMPREPLY=( $(compgen -W "%(cmds)s completion" -- "$cur") )
    else
        COMPREPLY=( $(compgen -f -- "$cur") )
    fi
}
complete -F _phosphor phosphor
"""

ZSH = """# phosphor completion (zsh) — phosphor completion zsh
_phosphor() {
    local -a cmds topics
    cmds=(%(cmds)s completion)
    topics=(%(topics)s)
    if (( CURRENT == 2 )); then
        compadd -- $cmds
        return
    fi
    case ${words[2]} in
        help) compadd -- $topics ;;
        web) compadd -- on off status token ;;
        tunnel) compadd -- on off ;;
        note|notes) compadd -- --kind --by --book --file --tab --here --archive ;;
        workspace) compadd -- new open list ;;
        tts) compadd -- install status on off --voice --list ;;
        completion) compadd -- bash zsh ;;
        *) _files ;;
    esac
}
compdef _phosphor phosphor
"""

def main():
    shell = (sys.argv[1:] or [""])[0]
    if shell not in ("bash", "zsh"):
        print("usage: phosphor completion bash|zsh", file=sys.stderr)
        print("  bash:  phosphor completion bash >> ~/.bashrc", file=sys.stderr)
        print("  zsh:   phosphor completion zsh  >> ~/.zshrc", file=sys.stderr)
        return 1
    sys.stdout.write((BASH if shell == "bash" else ZSH) % {"cmds": CMDS, "topics": TOPICS})
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
