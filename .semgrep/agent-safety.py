# Fixtures for agent-safety.yml (semgrep --test pairs by filename).
import os
import pickle
import subprocess

import yaml


def deserialize_bad(blob, stream):
    # ruleid: unsafe-yaml-load
    a = yaml.load(stream)
    # ruleid: unsafe-yaml-load
    b = yaml.unsafe_load(stream)
    # ruleid: unsafe-pickle-load
    c = pickle.loads(blob)
    # ruleid: unsafe-pickle-load
    with open("x.pkl", "rb") as f:
        d = pickle.load(f)
    return a, b, c, d


def deserialize_ok(stream):
    # ok: unsafe-yaml-load
    a = yaml.safe_load(stream)
    # ok: unsafe-yaml-load
    b = yaml.load(stream, Loader=yaml.SafeLoader)
    return a, b


def code_exec_bad(expr):
    # ruleid: no-eval-exec
    a = eval(expr)
    # ruleid: no-eval-exec
    exec(expr)
    return a


def shell_bad(name):
    # ruleid: no-os-popen
    return os.popen("ls " + name).read()


def shell_ok(name):
    # arg-list subprocess must NOT trip no-os-popen
    # ok: no-os-popen
    return subprocess.run(["ls", name], shell=False, check=True)
