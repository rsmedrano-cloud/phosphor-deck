"""phosphor mcp - the deck, read-only, for any assistant that speaks MCP.

    phosphor mcp        a Model Context Protocol server on stdin/stdout

An assistant starts it as a child process and asks over the pipe; nothing
listens on a port, and it ends when the assistant closes the pipe. Register
it once, e.g. `claude mcp add phosphor -- phosphor mcp`.

Its tools only read what's already on this machine: glance, fleet (from the
deck's own cache, no ssh), notes, workspaces and the deck's log. None of
them sends, restarts or writes anything, so there's no tool to ask for that.
"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Newest first; an older client gets its own version back, anything else ours.
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
KINDS = ("note", "idea", "decision", "todo", "summary")
MAX_NOTES, MAX_LINES = 200, 400

def _int(v, default, top):
    try:
        return max(1, min(int(v), top))
    except (TypeError, ValueError):
        return default

def t_glance(a):
    import glance
    return glance.payload()

def t_fleet(a):
    import deckconf, fleet
    out = fleet.as_json(deckconf.fleet_hosts(deckconf.load()[0]))
    host = a.get("host")
    if host:
        if host not in out["hosts"]:
            raise ValueError("no host %r in the profile: %s" % (host, ", ".join(out["hosts"]) or "none"))
        out["hosts"] = {host: out["hosts"][host]}
    return out

def t_notes(a):
    import notes
    path = notes.archive_of(notes.PATH) if a.get("archive") else notes.PATH
    rows = notes.entries(path, tab=a.get("tab") or None,
                         project=None if a.get("project") is None else notes.clean_project(a["project"]))
    kind = a.get("kind")
    if kind:
        rows = [e for e in rows if e["kind"] == kind]
    q = (a.get("query") or "").lower()
    if q:
        rows = [e for e in rows if q in (e["title"] + "\n" + "\n".join(e["body"])).lower()]
    limit = _int(a.get("limit"), 20, MAX_NOTES)
    return {"total": len(rows), "notes": [
        {"when": e["when"], "kind": e["kind"], "by": e["by"], "tab": e["tab"] or None,
         "project": e["project"] or None,
         "title": e["title"], "body": "\n".join(e["body"])} for e in rows[:limit]]}

def t_workspaces(a):
    import workspace
    return workspace.as_json()

def t_logs(a):
    import dlog
    tool = (a.get("tool") or "").upper() or None
    n = _int(a.get("lines"), 100, MAX_LINES)
    if tool and os.path.exists(dlog.tracefile(tool)):
        lines = dlog.tail(dlog.tracefile(tool), n)
    elif tool:
        lines = dlog.tail_for(tool, n)
    else:
        lines = dlog.tail(dlog.LOG, n)
    return {"tool": tool, "lines": lines}

def _obj(props=None):
    return {"type": "object", "properties": props or {}, "additionalProperties": False}

TOOLS = {
    "glance": (t_glance, "The deck at a glance: a status light (green/amber/red/unknown), fleet "
               "problems, unread mentions, open todos and dirty workspaces.", _obj()),
    "fleet": (t_fleet, "Every fleet host's latest reading from the deck's own cache (no ssh): CPU, "
              "memory, disks, containers, failed units, pending reboot and updates, sensors. "
              "stale is true when the deck's fleet panel isn't polling.",
              _obj({"host": {"type": "string", "description": "only this host"}})),
    "notes": (t_notes, "The deck's shared notebook, newest first: what was done, decided and is "
              "left to do. total counts every match before the limit.",
              _obj({"kind": {"type": "string", "enum": list(KINDS)},
                    "tab": {"type": "string", "description": "only notes taken from this tab"},
                    "project": {"type": "string", "description": "only notes filed under this project (\"\" for the ones with none)"},
                    "query": {"type": "string", "description": "text in the title or body (any case)"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_NOTES, "default": 20},
                    "archive": {"type": "boolean", "description": "read the archive instead", "default": False}})),
    "workspaces": (t_workspaces, "The workspaces under the projects folder, each with its git state "
                   "(uncommitted changes, commits ahead/behind).", _obj()),
    "logs": (t_logs, "The end of the deck's own log (crashes, hangs, exits, restarts), or one tool's "
             "lines (its trace file when one is on). Holds no note text or host names.",
             _obj({"tool": {"type": "string", "description": "e.g. FLEET, PROM, NOTES"},
                   "lines": {"type": "integer", "minimum": 1, "maximum": MAX_LINES, "default": 100}})),
}

def tool_list():
    return [{"name": n, "description": d, "inputSchema": s,
             "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
            for n, (_, d, s) in TOOLS.items()]

def call(name, args):
    """A tools/call result. A tool that fails is a result with isError, so
    the assistant reads why; only an unknown name is a protocol error."""
    fn = TOOLS[name][0]
    try:
        data = fn(args if isinstance(args, dict) else {})
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}]}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}],
            "structuredContent": data}

def version():
    try:
        import version as v
        return open(os.path.join(v.REPO, "VERSION")).read().strip()
    except Exception:
        return "?"

def handle(msg):
    """One JSON-RPC message in, its reply out (None for a notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "invalid request"}}
    method, mid, p = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:
        return None                                   # notifications/initialized and the like
    def ok(result): return {"jsonrpc": "2.0", "id": mid, "result": result}
    def err(code, text): return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}
    if not isinstance(p, dict):
        return err(-32602, "params must be an object")
    if method == "initialize":
        want = p.get("protocolVersion")
        return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "phosphor", "version": version()},
                   "instructions": "Phosphor Deck, read-only: glance, fleet, notes, workspaces, logs. "
                                   "Nothing here can send, restart or write."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        if not isinstance(p.get("name"), str) or p["name"] not in TOOLS:
            return err(-32602, "unknown tool: %s" % p.get("name"))
        return ok(call(p["name"], p.get("arguments")))
    return err(-32601, "method not found: %s" % method)

def safe(msg):
    """handle(), but a message it chokes on is an error reply, never the
    end of the server: the next request still gets its answer."""
    try:
        return handle(msg)
    except Exception as e:
        mid = msg.get("id") if isinstance(msg, dict) else None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}

def serve(inp, out):
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(msg, list) and msg:         # a batch (2025-03-26 only, but cheap)
                reply = [r for r in map(safe, msg) if r is not None] or None
            else:
                reply = safe(msg if msg != [] else None)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()

def main():
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__); return 0
    if sys.stdin.isatty():
        print(__doc__)
        print("It talks JSON-RPC over a pipe: an assistant starts it, not a terminal.")
        return 1
    # stdout is the protocol: anything a module prints goes to stderr instead
    out = io.TextIOWrapper(os.fdopen(os.dup(sys.stdout.fileno()), "wb"), encoding="utf-8")
    sys.stdout = sys.stderr
    inp = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    try:
        serve(inp, out)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
