"""ucsm.py — run any of the skill's CLIs IN THE CURRENT PYTHON PROCESS.

Why: inside a Databricks notebook / Genie Code the workspace credentials belong to the notebook's own Python
process. A child process (`!python scripts/apply.py`, `subprocess`) cannot reuse them on serverless compute
("CONTEXT_UNAVAILABLE_FOR_REMOTE_CLIENT"), but the same script run in-process authenticates fine. Outside
Databricks (laptop, CI) children work too, using `--profile` or DATABRICKS_HOST/TOKEN — this runner is optional there.

    import sys; sys.path.insert(0, "<skill folder>/scripts")
    import ucsm
    ucsm.run("design.py", inv, "-o", out, "--catalog", "main")          # prints output, returns the exit code
    rc, out, err = ucsm.run_captured("decide.py", "summary", map_path)   # capture instead of print

`script` may be a bare name in this folder (design.py) or an absolute path (e.g. tests/live_smoke.py).
"""
import contextlib
import io
import os
import runpy
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def run_captured(script, *args):
    path = script if os.path.isabs(script) else os.path.join(HERE, script)
    argv0, cwd_path = sys.argv, list(sys.path)
    sys.argv = [path, *[str(a) for a in args]]
    for d in (HERE, os.path.join(HERE, "adapters")):
        if d not in sys.path:
            sys.path.insert(0, d)
    out, err, rc = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(path, run_name="__main__")
            except SystemExit as e:
                if isinstance(e.code, int):
                    rc = e.code
                elif e.code is not None:
                    err.write(str(e.code) + "\n")
                    rc = 1
            except Exception:
                err.write(traceback.format_exc())
                rc = 1
    finally:
        sys.argv = argv0
        sys.path[:] = cwd_path
    return rc, out.getvalue(), err.getvalue()


def run(script, *args):
    rc, out, err = run_captured(script, *args)
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr)
    return rc
