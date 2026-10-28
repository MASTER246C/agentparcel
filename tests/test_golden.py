#!/usr/bin/env python3
"""Cross-engine golden tests for the shared part format.

Parts written by AgentParcel.core.ps1 are verified and rebuilt by src/agentparcel/core.py,
and parts written by core.py are verified and rebuilt by AgentParcel.core.ps1.

Committed fixtures under tests/golden/ let the Python engine check a PowerShell part set
on machines without PowerShell. When pwsh (or --powershell) is available, the same script
also rebuilds the committed Python part set with PowerShell and runs a fresh round trip
in both directions. Without PowerShell, that half is skipped and the Python half still runs.
"""
import argparse
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "src", "agentparcel", "core.py")
DRIVE = os.path.join(ROOT, "tests", "golden_drive.ps1")
GOLDEN = os.path.join(ROOT, "tests", "golden")
KIT_NAMES = ("HOW-TO-REBUILD.txt", "rebuild.py")
BYTE_LIMIT = 32000
BYTE_SIZE = 100000
ZIP_LIMIT = 200000
ZIP_SIZE = 450000


def load_core():
    spec = importlib.util.spec_from_file_location("zs_golden", CORE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pattern(size, seed):
    """Incompressible-enough bytes so a zip split cannot collapse into one part."""
    x = seed & 0x7FFFFFFF
    out = bytearray(size)
    for i in range(size):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def zip_files(path):
    with zipfile.ZipFile(path) as zf:
        found = {}
        for info in zf.infolist():
            if info.is_dir() or info.filename.endswith("/"):
                continue
            found[info.filename] = zf.read(info.filename)
        return found


def strip_kit(folder):
    for name in KIT_NAMES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            os.remove(path)


def write_originals(directory):
    os.makedirs(directory, exist_ok=True)
    raw = os.path.join(directory, "sample.bin")
    with open(raw, "wb") as f:
        f.write(pattern(BYTE_SIZE, 0xA6E17))
    zpath = os.path.join(directory, "notes.zip")
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("notes/readme.txt", pattern(ZIP_SIZE, 0xBEE5))
        zf.writestr("notes/small.txt", b"golden")
    return raw, zpath


def part_zips(folder):
    return [name for name in os.listdir(folder) if name.lower().endswith(".zip") and "_part" in name.lower()]


def run_ps(exe, args):
    proc = subprocess.run(
        [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", DRIVE] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def ps_line(stdout, prefix):
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return line.split(" ", 1)[1].strip()
    return ""


def resolve_powershell(explicit):
    if explicit:
        return shutil.which(explicit) or (explicit if os.path.isfile(explicit) else None)
    return shutil.which("pwsh")


def python_split(zs, raw, zpath, directory):
    byte_dir = os.path.join(directory, "bytes")
    zip_dir = os.path.join(directory, "zip")
    zs.split_any_file(raw, output_dir=byte_dir, limit=BYTE_LIMIT, include_apps=False)
    zs.Splitter(zpath, output_dir=zip_dir, limit=ZIP_LIMIT, unpack_inner=False, include_apps=False).run()
    strip_kit(byte_dir)
    strip_kit(zip_dir)
    return byte_dir, zip_dir


def ps_split(exe, raw, zpath, directory):
    byte_dir = os.path.join(directory, "bytes")
    zip_dir = os.path.join(directory, "zip")
    os.makedirs(byte_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)
    code, out, err = run_ps(exe, ["-Action", "SplitBytes", "-InputPath", raw, "-OutputDir", byte_dir, "-Limit", str(BYTE_LIMIT)])
    if code != 0 or not ps_line(out, "SPLIT "):
        raise RuntimeError("powershell byte split failed\n%s\n%s" % (out, err))
    code, out, err = run_ps(exe, ["-Action", "SplitZip", "-InputPath", zpath, "-OutputDir", zip_dir, "-Limit", str(ZIP_LIMIT)])
    if code != 0 or not ps_line(out, "SPLIT "):
        raise RuntimeError("powershell zip split failed\n%s\n%s" % (out, err))
    strip_kit(byte_dir)
    strip_kit(zip_dir)
    return byte_dir, zip_dir


def publish_tree(src, dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def write_fixtures(zs, exe):
    if not exe:
        raise SystemExit("writing fixtures needs pwsh (or --powershell) so both engines can run")
    parent = tempfile.mkdtemp(prefix="ap-golden-write-")
    try:
        raw, zpath = write_originals(os.path.join(parent, "original"))
        py_root = os.path.join(parent, "from-python")
        ps_root = os.path.join(parent, "from-powershell")
        os.makedirs(py_root)
        os.makedirs(ps_root)
        python_split(zs, raw, zpath, py_root)
        ps_split(exe, raw, zpath, ps_root)
        for label, root in (("python", py_root), ("powershell", ps_root)):
            zips = part_zips(os.path.join(root, "zip"))
            parts = [n for n in os.listdir(os.path.join(root, "bytes")) if "_part" in n]
            if len(zips) < 2 or len(parts) < 2:
                raise SystemExit("%s fixtures are not multi-part (bytes %s, zip %s)" % (label, parts, zips))
        publish_tree(os.path.join(parent, "original"), os.path.join(GOLDEN, "original"))
        publish_tree(py_root, os.path.join(GOLDEN, "from-python"))
        publish_tree(ps_root, os.path.join(GOLDEN, "from-powershell"))
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    print("WROTE", GOLDEN)


def check_python_side(zs, folder, raw, zpath, check):
    report = zs.verify_parts([os.path.join(folder, "bytes")])
    check("python verifies %s byte parts" % os.path.basename(folder), report["ok"], report.get("message", ""))
    rebuilt = zs.rebuild([os.path.join(folder, "bytes")], output_dir=os.path.join(folder, "rebuilt-bytes"))
    check("python rebuilds %s byte parts" % os.path.basename(folder), sha(rebuilt["output"]) == sha(raw), rebuilt["output"])
    zreport = zs.verify_parts([os.path.join(folder, "zip")])
    check("python verifies %s zip parts" % os.path.basename(folder), zreport["ok"], zreport.get("message", ""))
    try:
        joined = zs.rebuild([os.path.join(folder, "zip")], output_dir=os.path.join(folder, "rebuilt-zip"))
        same = zip_files(joined["output"]) == zip_files(zpath)
        check("python rebuilds %s zip parts" % os.path.basename(folder), same, joined["output"])
    except Exception as ex:
        check("python rebuilds %s zip parts" % os.path.basename(folder), False, "%s: %s" % (type(ex).__name__, ex))


def check_ps_side(exe, folder, raw, zpath, check):
    code, out, err = run_ps(exe, ["-Action", "Verify", "-InputPath", os.path.join(folder, "bytes")])
    check("powershell verifies %s byte parts" % os.path.basename(folder), code == 0 and "VERIFY_OK" in out, out + err)
    out_dir = os.path.join(folder, "ps-rebuilt-bytes")
    code, out, err = run_ps(exe, ["-Action", "Rebuild", "-InputPath", os.path.join(folder, "bytes"), "-OutputDir", out_dir])
    rebuilt = ps_line(out, "REBUILD ")
    check(
        "powershell rebuilds %s byte parts" % os.path.basename(folder),
        code == 0 and rebuilt and os.path.isfile(rebuilt) and sha(rebuilt) == sha(raw),
        out + err,
    )
    code, out, err = run_ps(exe, ["-Action", "Verify", "-InputPath", os.path.join(folder, "zip")])
    check("powershell verifies %s zip parts" % os.path.basename(folder), code == 0 and "VERIFY_OK" in out, out + err)
    out_dir = os.path.join(folder, "ps-rebuilt-zip")
    code, out, err = run_ps(exe, ["-Action", "Rebuild", "-InputPath", os.path.join(folder, "zip"), "-OutputDir", out_dir])
    rebuilt = ps_line(out, "REBUILD ")
    same = False
    detail = out + err
    if code == 0 and rebuilt and os.path.isfile(rebuilt):
        try:
            same = zip_files(rebuilt) == zip_files(zpath)
        except Exception as ex:
            detail = "%s\n%s: %s" % (detail, type(ex).__name__, ex)
    check("powershell rebuilds %s zip parts" % os.path.basename(folder), same, detail)


def live_round_trip(zs, exe, check):
    work = tempfile.mkdtemp(prefix="ap-golden-live-")
    try:
        raw, zpath = write_originals(os.path.join(work, "original"))
        ps_made = os.path.join(work, "made-by-ps")
        py_made = os.path.join(work, "made-by-py")
        os.makedirs(ps_made)
        os.makedirs(py_made)
        try:
            ps_split(exe, raw, zpath, ps_made)
        except Exception as ex:
            check("powershell live split", False, str(ex))
            return
        check("powershell live split", len(part_zips(os.path.join(ps_made, "zip"))) >= 2, "")
        check_python_side(zs, ps_made, raw, zpath, check)
        python_split(zs, raw, zpath, py_made)
        check("python live split", len(part_zips(os.path.join(py_made, "zip"))) >= 2, "")
        check_ps_side(exe, py_made, raw, zpath, check)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--powershell", default="", help="PowerShell executable. Default: pwsh on PATH, or skip that half.")
    ap.add_argument("--require-powershell", action="store_true", help="fail when the PowerShell executable is missing")
    ap.add_argument("--write-fixtures", action="store_true", help="regenerate tests/golden from both engines")
    args = ap.parse_args(argv)
    zs = load_core()
    exe = resolve_powershell(args.powershell)
    if args.write_fixtures:
        write_fixtures(zs, exe)
        return 0
    if args.powershell and not exe:
        print("FAIL powershell executable not found:", args.powershell)
        return 1
    if args.require_powershell and not exe:
        print("FAIL powershell is required for this run and was not found")
        return 1

    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("PASS", name)
        else:
            print("FAIL", name, detail)
            failures.append(name)

    raw = os.path.join(GOLDEN, "original", "sample.bin")
    zpath = os.path.join(GOLDEN, "original", "notes.zip")
    ps_fix = os.path.join(GOLDEN, "from-powershell")
    py_fix = os.path.join(GOLDEN, "from-python")
    if not (os.path.isfile(raw) and os.path.isfile(zpath) and os.path.isdir(ps_fix) and os.path.isdir(py_fix)):
        print("FAIL golden fixtures are missing. Run: python3 tests/test_golden.py --write-fixtures")
        return 1
    # Copy fixtures so rebuild output is not written into the committed tree.
    work = tempfile.mkdtemp(prefix="ap-golden-fix-")
    try:
        ps_copy = os.path.join(work, "from-powershell")
        py_copy = os.path.join(work, "from-python")
        shutil.copytree(ps_fix, ps_copy)
        shutil.copytree(py_fix, py_copy)
        check_python_side(zs, ps_copy, raw, zpath, check)
        if exe:
            check_ps_side(exe, py_copy, raw, zpath, check)
            live_round_trip(zs, exe, check)
        else:
            print("SKIP powershell cross-check: pwsh is not installed")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print("FAILED", len(failures))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
