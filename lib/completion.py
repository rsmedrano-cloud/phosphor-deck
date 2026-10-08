"""phosphor completion - tab completion for bash and zsh.

    phosphor completion bash >> ~/.bashrc      (or a file you source)
    phosphor completion zsh  >> ~/.zshrc

It completes the commands, then each command's words (a subcommand, or
after `help` the manual's topics) and flags, and the values of the flags
that take fixed ones -- all from share/commands.json (lib/cli.py), so a
new command or flag completes without touching this file.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cli


def q(words):
    return " ".join(words)


def bash():
    after, values = cli.completions()
    vals = "".join('        %s) COMPREPLY=( $(compgen -W "%s" -- "$cur") ); return ;;\n' % (f, q(v))
                   for f, v in sorted(values.items()))
    cmds = "".join('        %s) w="%s"; o="%s" ;;\n' % (n, q(w), q(o)) for n, (w, o) in after.items())
    return """# phosphor completion (bash) — phosphor completion bash
_phosphor() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD-1]} w= o=
    if [ "$COMP_CWORD" = 1 ]; then
        COMPREPLY=( $(compgen -W "%s" -- "$cur") ); return
    fi
    case "$prev" in
%s    esac
    case "${COMP_WORDS[1]}" in
%s    esac
    case "$cur" in
        -*) COMPREPLY=( $(compgen -W "$o" -- "$cur") ) ;;
        *) if [ "$COMP_CWORD" = 2 ] && [ -n "$w" ]; then
               COMPREPLY=( $(compgen -W "$w" -- "$cur") )
           else
               COMPREPLY=( $(compgen -f -- "$cur") )
           fi ;;
    esac
}
complete -F _phosphor phosphor
""" % (q(after), vals, cmds)


def zsh():
    after, values = cli.completions()
    vals = "".join("        %s) compadd -- %s; return ;;\n" % (f, q(v)) for f, v in sorted(values.items()))
    cmds = "".join('        %s) w=(%s); o=(%s) ;;\n' % (n, q(w), q(o)) for n, (w, o) in after.items())
    return """# phosphor completion (zsh) — phosphor completion zsh
_phosphor() {
    local -a w o
    if (( CURRENT == 2 )); then
        compadd -- %s
        return
    fi
    case ${words[CURRENT-1]} in
%s    esac
    case ${words[2]} in
%s    esac
    if [[ ${words[CURRENT]} == -* ]]; then
        compadd -- $o
    elif (( CURRENT == 3 && ${#w} )); then
        compadd -- $w
    else
        _files
    fi
}
compdef _phosphor phosphor
""" % (q(after), vals, cmds)


def main():
    shell = (sys.argv[1:] or [""])[0]
    if shell not in ("bash", "zsh"):
        print("usage: phosphor completion bash|zsh", file=sys.stderr)
        print("  bash:  phosphor completion bash >> ~/.bashrc", file=sys.stderr)
        print("  zsh:   phosphor completion zsh  >> ~/.zshrc", file=sys.stderr)
        return 1
    sys.stdout.write(bash() if shell == "bash" else zsh())
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
