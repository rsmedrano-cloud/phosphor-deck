#!/usr/bin/env python3
"""A function that assigns a name the module defines as a function.

    python3 tests/shadow-check.py

Python then treats that name as local in the whole function, and a call to
the module's function earlier in it fails (UnboundLocalError): the wizard
once called `sh()` and later did `ed, sh = ...`. Compiling doesn't catch it.
"""
import ast, glob, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = []
for path in sorted(glob.glob(os.path.join(ROOT, "lib", "*.py"))) + [os.path.join(ROOT, "phosphor")]:
    tree = ast.parse(open(path).read())
    tops = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef): continue
        stores = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
        loads = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}
        for name in sorted(stores & tops & loads):
            bad.append("%s:%d %s() assigns %s, a function of the module" % (os.path.relpath(path, ROOT), fn.lineno, fn.name, name))
if bad:
    print("\n".join(bad)); sys.exit(1)
