#!/usr/bin/env python3
"""AgentParcel 3.5.1: PowerShell zip split and byte-part checksums, cross-checked with Python."""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "src", "agentparcel", "core.py")
REBUILD = os.path.join(ROOT, "src", "agentparcel", "rebuild.py")
PS = os.path.join(ROOT, "tests", "test_351.ps1")


def load_core():
    spec = importlib.util.spec_from_file_location("zs351", CORE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def run_ps(args):
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-File", PS] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout


def main():
    if shutil.which("pwsh") is None:
        print("SKIP test_351.py: pwsh is not installed")
        return 0
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("PASS", name)
        else:
            print("FAIL", name, detail)
            failures.append(name)

    code, out = run_ps([])
    print(out, end="" if out.endswith("\n") or not out else "\n")
    check("powershell regression script", code == 0, out)
    bytedir = ""
    for line in out.splitlines():
        if line.startswith("BYTEDIR "):
            bytedir = line.split(" ", 1)[1].strip()
    if bytedir and os.path.isdir(bytedir):
        zs = load_core()
        report = zs.verify_parts([bytedir])
        check("python verifies a powershell byte set", report["ok"], report.get("message", ""))
        rebuilt = zs.rebuild([bytedir], output_dir=os.path.join(os.path.dirname(bytedir), "py-rebuilt"))
        original = os.path.join(os.path.dirname(bytedir), "sample.exe")
        check("python rebuilds a powershell byte set", sha(rebuilt["output"]) == sha(original))
        # rebuild.py writes next to the parts, into a copy so it does not collide with names.
        copy = os.path.join(os.path.dirname(bytedir), "bytes-for-script")
        if os.path.isdir(copy):
            shutil.rmtree(copy)
        shutil.copytree(bytedir, copy)
        proc = subprocess.run([sys.executable, REBUILD, copy], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        made = os.path.join(copy, "sample.exe")
        check("rebuild.py rebuilds a powershell byte set", proc.returncode == 0 and sha(made) == sha(original), proc.stdout)

        forward = os.path.join(os.path.dirname(bytedir), "py-split")
        py_split = zs.split_any_file(original, output_dir=forward, limit=60000, include_apps=False)
        part = os.path.join(py_split["output_dir"], "sample.exe_part01")
        vcode, vout = run_ps(["-Action", "VerifyDir", "-InputPath", part, "-WorkDir", os.path.join(os.path.dirname(bytedir), "ps-verify")])
        check("powershell verifies a python byte set", vcode == 0 and "VERIFY_OK" in vout, vout)
        rcode, rout = run_ps(["-Action", "RebuildDir", "-InputPath", part, "-WorkDir", os.path.join(os.path.dirname(bytedir), "ps-rebuild")])
        rebuilt_ps = rout.strip().splitlines()[-1] if rout.strip() else ""
        check("powershell rebuilds a python byte set", rcode == 0 and rebuilt_ps and sha(rebuilt_ps) == sha(original), rout)
    else:
        check("powershell left a byte directory", False, out)

    if failures:
        print("FAILED", len(failures))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
