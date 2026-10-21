#!/usr/bin/env python3
"""A name used but never defined anywhere it could come from.

    python3 tests/names-check.py

Compiling doesn't catch it, and the line only fails when it runs: STATE_TXT
in mentions.py stayed undefined for five weeks, on a branch only a
preparing-notes state reached. symtable says which names each scope reads
from the module's globals; each must be bound at the module's top level
(an assignment, a def, an import, a `global` in some function), come in
through `from ui import *` (followed into lib/), or be a builtin.
"""
import builtins, glob, os, symtable, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
MODULE_ATTRS = {"__file__", "__name__", "__doc__", "__spec__", "__loader__",
                "__package__", "__builtins__", "__path__", "__annotations__"}
BUILTINS = set(dir(builtins)) | MODULE_ATTRS
_tables, _exports = {}, {}


def table(path):
    if path not in _tables:
        _tables[path] = symtable.symtable(open(path).read(), path, "exec")
    return _tables[path]


def scopes(t):
    yield t
    for c in t.get_children():
        yield from scopes(c)


def star_sources(path):
    """The lib modules this file pulls in with `from X import *`."""
    import ast
    out = []
    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
            src = os.path.join(LIB, (n.module or "") + ".py")
            out.append(src if os.path.exists(src) else None)
    return out


def bound(path):
    """Every name the module binds at its top level, its stars included."""
    t = table(path)
    names = {s.get_name() for s in t.get_symbols()
             if s.is_assigned() or s.is_imported() or s.is_namespace()}
    for sc in scopes(t):  # `global X` then `X = ...` inside a function
        names |= {s.get_name() for s in sc.get_symbols()
                  if s.is_declared_global() and s.is_assigned()}
    for src in star_sources(path):
        if src is None:
            return None  # a star from outside lib: can't know what it brings
        names |= exports(src)
    return names


def exports(path):
    """What `from module import *` brings: its public top-level names."""
    if path not in _exports:
        _exports[path] = set()  # a cycle stops here
        _exports[path] = {n for n in (bound(path) or ()) if not n.startswith("_")}
    return _exports[path]


def undefined(path):
    have = bound(path)
    if have is None:
        return []
    have |= BUILTINS
    out = []
    for sc in scopes(table(path)):
        for s in sc.get_symbols():
            n = s.get_name()
            if s.is_referenced() and s.is_global() and n not in have:
                out.append((sc.get_lineno(), sc.get_name(), n))
    return sorted(set(out))


def main():
    files = (sorted(glob.glob(os.path.join(LIB, "*.py"))) + [os.path.join(ROOT, "phosphor")]
             + sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))))
    bad = []
    for path in files:
        for line, scope, name in undefined(path):
            where = "" if scope == "top" else " in %s() (line %d)" % (scope, line)
            bad.append("%s: %s is never defined%s" % (os.path.relpath(path, ROOT), name, where))
    if bad:
        print("\n".join(bad))
        sys.exit(1)


if __name__ == "__main__":
    main()
