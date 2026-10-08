#!/usr/bin/env python3
"""phosphor mcp: a read-only MCP server that speaks clean JSON-RPC on stdio.

    python3 tests/mcp-check.py

Drives `phosphor mcp` over a pipe in a throwaway HOME (demo profile, a fleet
cache, a notebook, a deck.log): the handshake, every tool's answer, errors
as results, and stdout carrying nothing but protocol lines. Also checks that
no tool's files change, and that every tool says it's read-only.
"""
import hashlib, json, os, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
def need(what, ok):
    if not ok: fails.append(what)

home = tempfile.mkdtemp()
for d in (".config/phosphor", ".cache/phosphor", ".local/share/phosphor"):
    os.makedirs(os.path.join(home, d))
prof = os.path.join(home, ".config/phosphor/deck.toml")
open(prof, "w").write('[deck]\nsession = "mcp-check-nosuch"\ndemo = true\n\n'
                      '[[hosts]]\nname = "nebula"\nssh = "nebula"\n\n'
                      '[[hosts]]\nname = "atlas"\nssh = "atlas"\n')
json.dump({"t": time.time(), "hosts": {"nebula": {"ok": True, "CPU": 12, "MEMU": 100, "MEMT": 1000, "ms": 40}}},
          open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
open(os.path.join(home, ".local/share/phosphor/notes.md"), "w").write(
    "# Phosphor notes\n\n"
    "## 2026-01-01 10:00 · decision · me · keep it read-only\nNo writes from an assistant.\n\n"
    "## 2026-01-02 11:00 · todo · claude @SYS · wire the gadget\n\n"
    "## 2026-01-03 12:00 · note · me · plain one\n")
open(os.path.join(home, ".cache/phosphor/deck.log"), "w").write(
    "2026-01-01 10:00:00  FLEET      start\n2026-01-01 10:00:01  PROM       exit 1\n")
env = dict(os.environ, HOME=home, PHOSPHOR_PROFILE=prof, NO_COLOR="1")
for k in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID", "PHOSPHOR_NOTES", "PHOSPHOR_CACHE"):
    env.pop(k, None)

def snapshot():
    out = {}
    for base, _, files in os.walk(home):
        for f in files:
            p = os.path.join(base, f)
            if "__pycache__" not in p:
                out[p] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    return out

before = snapshot()
msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "check", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "glance", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "fleet", "arguments": {"host": "nebula"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "fleet", "arguments": {"host": "nowhere"}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "notes", "arguments": {"kind": "todo"}}},
    {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "notes", "arguments": {"query": "READ-ONLY", "limit": 1}}},
    {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "workspaces"}},
    {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "logs", "arguments": {"tool": "prom"}}},
    {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "restart"}},
    {"jsonrpc": "2.0", "id": 11, "method": "resources/list"},
    {"jsonrpc": "2.0", "id": 12, "method": "ping"},
]
stdin = "\n".join(json.dumps(m) for m in msgs) + "\nnot json\n"
r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "mcp"], input=stdin, env=env,
                   capture_output=True, text=True, timeout=60)
need("exits 0 when the pipe closes (rc %d: %s)" % (r.returncode, r.stderr[-300:]), r.returncode == 0)
lines = r.stdout.splitlines()
replies = {}
for l in lines:
    try:
        m = json.loads(l)
    except ValueError:
        fails.append("stdout carries a non-protocol line: %r" % l[:120]); continue
    replies[m.get("id")] = m
need("one reply per request, none for the notification (%d)" % len(lines), len(lines) == 13)
need("no escape codes", "\x1b" not in r.stdout)

def result(i):
    return (replies.get(i) or {}).get("result") or {}
def data(i):
    return result(i).get("structuredContent") or {}

init = result(1)
need("initialize: echoes a known protocol version", init.get("protocolVersion") == "2025-06-18")
need("initialize: tools capability and its name", "tools" in init.get("capabilities", {})
     and init.get("serverInfo", {}).get("name") == "phosphor")
tools = {t["name"]: t for t in result(2).get("tools", [])}
need("tools/list: the five tools (%s)" % sorted(tools), set(tools) == {"glance", "fleet", "notes", "workspaces", "logs"})
need("every tool says it's read-only", all(t.get("annotations", {}).get("readOnlyHint") is True
                                           and t.get("annotations", {}).get("destructiveHint") is False
                                           for t in tools.values()))
need("every tool has an object input schema", all(t.get("inputSchema", {}).get("type") == "object" for t in tools.values()))
need("glance: a status light", data(3).get("status") in ("green", "amber", "red", "unknown"))
need("glance: text content is the same JSON", json.loads(result(3)["content"][0]["text"]) == data(3)
     if result(3).get("content") else False)
need("fleet: one host, named and typed", list(data(4).get("hosts", {})) == ["nebula"]
     and data(4)["hosts"]["nebula"].get("cpu") == 12)
need("fleet: an unknown host is an error result, not a crash", result(5).get("isError") is True
     and "nowhere" in result(5)["content"][0]["text"])
n = data(6).get("notes") or [{}]
need("notes: kind filter, tab and by read", data(6).get("total") == 1 and n[0].get("by") == "claude"
     and n[0].get("tab") == "SYS" and n[0].get("title") == "wire the gadget")
n = data(7).get("notes") or [{}]
need("notes: query matches the body in any case", data(7).get("total") == 1 and n[0].get("kind") == "decision"
     and n[0].get("body") == "No writes from an assistant.")
need("workspaces: root and list", "root" in data(8) and data(8).get("workspaces") == [])
need("logs: only that tool's lines", data(9).get("lines") == ["2026-01-01 10:00:01  PROM       exit 1"])
need("an unknown tool is a protocol error", (replies.get(10) or {}).get("error", {}).get("code") == -32602)
need("an unknown method is -32601", (replies.get(11) or {}).get("error", {}).get("code") == -32601)
need("ping", result(12) == {} and "error" not in (replies.get(12) or {"error": 1}))
need("a broken line is a parse error", (replies.get(None) or {}).get("error", {}).get("code") == -32700)
need("nothing in HOME changed", snapshot() == before)

# on a terminal it says what it is instead of waiting on a pipe nobody fills
sys.path.insert(0, os.path.join(ROOT, "lib"))
import mcp
need("an old client gets its own version", mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05"}})["result"]["protocolVersion"] == "2024-11-05")
need("an unknown version gets ours", mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "1999-01-01"}})["result"]["protocolVersion"] == mcp.PROTOCOLS[0])
need("not JSON-RPC 2.0 is an invalid request", mcp.handle({"id": 1, "method": "ping"})["error"]["code"] == -32600)

if fails:
    print("\n".join(fails)); sys.exit(1)
print("mcp-check ok (%d tools)" % len(tools))
