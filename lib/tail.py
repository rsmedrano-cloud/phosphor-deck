"""phosphor tail HOST [SERVICE] - stream a fleet host's logs, right here.

    phosphor tail nimbus                    # journalctl -f, no unit filter
    phosphor tail relay nginx               # journalctl -f -u nginx
    phosphor tail relay systemd/nginx       # same, explicit
    phosphor tail nimbus docker/jellyfin    # docker logs -f --tail 100 jellyfin
    phosphor tail nimbus podman/jellyfin    # podman logs -f --tail 100 jellyfin

HOST is a name from your profile (`phosphor doctor` or the DECK tab list
them). This is exactly a normal ssh tab -- `ssh -t HOST journalctl -f ...`,
through `phosphor run --reconnect`, the same mechanism a dropped ssh tab
already reconnects with -- with the journalctl/docker/podman command
already filled in, so you don't have to remember the syntax or the alias
each time. Ctrl-C stops watching; it doesn't touch anything on the host.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BAD, RST, REPO
import deckconf

PHOSPHOR = os.path.join(REPO, "phosphor")


def remote_argv(service):
    """The command to run on the host: journalctl by default, or docker/
    podman logs when `service` names a container that way."""
    if not service:
        return ["journalctl", "-f", "-n", "100"]
    kind, sep, name = service.partition("/")
    if not sep:
        kind, name = "systemd", service
    if kind in ("docker", "podman"):
        return [kind, "logs", "-f", "--tail", "100", name]
    return ["journalctl", "-f", "-n", "100", "-u", name]


def find_host(prof, name):
    return next((h for h in deckconf.hosts(prof) if h.get("name") == name), None)


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print("usage: phosphor tail HOST [SERVICE]"); return 1
    host, service = a[0], (a[1] if len(a) > 1 else None)
    prof, _ = deckconf.load()
    h = find_host(prof, host)
    if not h:
        known = ", ".join(x["name"] for x in deckconf.hosts(prof)) or "(none in your profile)"
        print(BAD + " no host named %r in your profile -- have: %s" % (host, known) + RST)
        return 1
    cmd = remote_argv(service)
    argv = cmd if h.get("local") else ["ssh", "-t", deckconf.target(h)] + cmd
    name = ("TAIL-" + host).upper()[:24]
    os.execv(sys.executable, [sys.executable, PHOSPHOR, "run", "--name", name, "--reconnect", "--"] + argv)


if __name__ == "__main__":
    sys.exit(main() or 0)
