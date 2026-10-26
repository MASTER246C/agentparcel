#!/usr/bin/env python3
"""AgentParcel 3.4.0: byte split, verify, standalone rebuild.py, and cancel cleanup."""
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
MCP = os.path.join(ROOT, "src", "agentparcel", "mcp.py")
REBUILD = os.path.join(ROOT, "src", "agentparcel", "rebuild.py")


def load_core():
    spec = importlib.util.spec_from_file_location("zs_core", CORE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    zs = load_core()
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("PASS", name)
        else:
            print("FAIL", name, detail)
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="ap34-") as tmp:
        raw = os.path.join(tmp, "clip.bin")
        payload = b"\x00\x01PDF-not-a-zip" + os.urandom(2500) + b"\xffTAIL"
        with open(raw, "wb") as f:
            f.write(payload)
        original = sha(raw)
        split = zs.split_any_file(raw, limit=1000, include_apps=False)
        folder = split["output_dir"]
        names = sorted(os.listdir(folder))
        check("byte parts and kit",
              os.path.isfile(os.path.join(folder, "_agentparcel_bytes.json"))
              and os.path.isfile(os.path.join(folder, "HOW-TO-REBUILD.txt"))
              and os.path.isfile(os.path.join(folder, "rebuild.py"))
              and any(n.startswith("clip.bin_part") for n in names),
              names)
        howto = open(os.path.join(folder, "HOW-TO-REBUILD.txt"), encoding="utf-8").read()
        check("howto mentions rebuild.py and powershell",
              "python3 rebuild.py" in howto and "PowerShell equivalent" in howto and "ConvertFrom-Json" in howto)
        part_files = [p for p, _s in split["parts"]]
        check("each part is under the cap", all(os.path.getsize(p) <= 1000 for p in part_files))
        check("part count", len(part_files) == 3, len(part_files))

        report = zs.verify_parts([folder])
        check("verify ok", report["ok"] and report["present"] == [1, 2, 3], report["message"])

        rebuilt = zs.rebuild([folder], os.path.join(tmp, "out"))
        check("rebuild bytes exact", sha(rebuilt["output"]) == original and rebuilt["mode"] == "bytes")

        os.remove(os.path.join(folder, "clip.bin_part02"))
        missing = zs.verify_parts([folder])
        check("verify missing part 2",
              (not missing["ok"]) and missing["missing"] == [2] and "clip.bin_part02" in missing["missing_names"],
              missing)
        try:
            zs.rebuild([folder])
            check("rebuild refuses missing", False, "no error")
        except zs.ZsError as ex:
            check("rebuild refuses missing", "Missing part" in str(ex) and ex.data.get("missing_parts") == [2], str(ex))

        # restore part 2 from a fresh split, then corrupt it
        fresh = zs.split_any_file(raw, limit=1000, include_apps=False)
        ff = fresh["output_dir"]
        target = os.path.join(ff, "clip.bin_part02")
        with open(target, "r+b") as f:
            f.seek(0)
            b0 = f.read(1)
            f.seek(0)
            f.write(bytes([(b0[0] ^ 0xFF)]))
        corrupt = zs.verify_parts([ff])
        check("verify corrupt part 2",
              (not corrupt["ok"]) and any(c.get("part") == 2 for c in corrupt["corrupt"]) and not corrupt["missing"],
              corrupt)
        proc = subprocess.run([sys.executable, os.path.join(ff, "rebuild.py"), ff],
                              capture_output=True, text=True)
        check("rebuild.py rejects corrupt", proc.returncode == 2 and "Corrupt part" in proc.stderr, proc.stderr)

        good = zs.split_any_file(raw, limit=1000, include_apps=False)
        gf = good["output_dir"]
        before = set(os.listdir(gf))
        proc = subprocess.run([sys.executable, os.path.join(gf, "rebuild.py")],
                              cwd=gf, capture_output=True, text=True)
        made = os.path.join(gf, "clip.bin")
        check("rebuild.py standalone",
              proc.returncode == 0 and os.path.isfile(made) and sha(made) == original and "SHA-256" in proc.stdout,
              proc.stderr + proc.stdout)
        # script must be the dependency-free copy, not an import of the app
        script = open(os.path.join(gf, "rebuild.py"), encoding="utf-8").read()
        check("rebuild.py is stdlib only", "import hashlib" in script and "import agentparcel" not in script)
        check("kit files unchanged by rebuild.py", before <= set(os.listdir(gf)))

        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] >= 3

        big = os.path.join(tmp, "big.bin")
        with open(big, "wb") as f:
            f.write(os.urandom(300000))
        parent = os.path.join(tmp, "cancel-parent")
        os.makedirs(parent)
        try:
            zs.split_any_file(big, parent, limit=8000, include_apps=False, should_cancel=stop)
            check("cancel raises", False, "returned")
        except zs.Cancelled as ex:
            check("cancel raises", str(ex) == "Cancelled", str(ex))
        leftover = []
        for dirpath, _dirs, files in os.walk(parent):
            leftover.extend(os.path.join(dirpath, name) for name in files)
        check("cancel removes partial output", leftover == [], leftover)

        keeper_dir = os.path.join(tmp, "keep")
        os.makedirs(keeper_dir)
        keeper = os.path.join(keeper_dir, "keep-me.txt")
        with open(keeper, "w", encoding="utf-8") as f:
            f.write("stay")
        calls["n"] = 0
        try:
            zs.split_any_file(big, keeper_dir, limit=8000, include_apps=False, should_cancel=stop)
        except zs.Cancelled:
            pass
        left = set(os.listdir(keeper_dir))
        check("cancel keeps unrelated files", left == {"keep-me.txt"}, left)

        # zip parts stay compatible and also get the kit
        zpath = os.path.join(tmp, "notes.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("notes/readme.txt", "hello agentparcel " * 50)
        zsplit = zs.Splitter(zpath, limit=1024 * 1024, include_apps=False).run()
        zdir = zsplit["output_dir"]
        part_zip = zsplit["parts"][0][0]
        with zipfile.ZipFile(part_zip) as zf:
            names = zf.namelist()
        check("zip markers kept",
              "_zipsplitter_part.json" in names and "_zipsplitter_manifest.json" in names, names)
        check("zip kit written",
              os.path.isfile(os.path.join(zdir, "_agentparcel_zipset.json"))
              and os.path.isfile(os.path.join(zdir, "HOW-TO-REBUILD.txt"))
              and os.path.isfile(os.path.join(zdir, "rebuild.py")))
        zverify = zs.verify_parts([zdir])
        check("verify zip set", zverify["ok"] and zverify["format"] == "zipsplitter-manifest", zverify["message"])
        os.remove(part_zip)
        zmiss = zs.verify_parts([zdir])
        check("verify zip missing", (not zmiss["ok"]) and 1 in zmiss["missing"], zmiss)
        # a set with the new sidecar removed still rebuilds (3.3.x shape)
        again = zs.Splitter(zpath, limit=1024 * 1024, include_apps=False).run()
        adir = again["output_dir"]
        for extra in ("HOW-TO-REBUILD.txt", "rebuild.py", "_agentparcel_zipset.json"):
            os.remove(os.path.join(adir, extra))
        joined = zs.rebuild([adir], os.path.join(tmp, "zip-out"))
        with zipfile.ZipFile(joined["output"]) as zf:
            body = zf.read("notes/readme.txt")
        check("zip rebuild without sidecar", body == b"hello agentparcel " * 50 and joined["mode"] == "manifest")

        # corrupt a zip part file's bytes and expect verify to say corrupt, not only missing
        third = zs.Splitter(zpath, limit=1024 * 1024, include_apps=False).run()
        tdir = third["output_dir"]
        zp = third["parts"][0][0]
        with open(zp, "r+b") as f:
            f.seek(0)
            first = f.read(1)
            f.seek(0)
            f.write(bytes([(first[0] ^ 0xFF)]))
        zbad = zs.verify_parts([tdir])
        check("verify corrupt zip part",
              (not zbad["ok"]) and zbad["corrupt"] and not zbad["missing"], zbad)

    # MCP tools, including cancellation that leaves no partial output
    mcp_script = r'''
import importlib.util, os, sys, tempfile, hashlib
os.environ["AGENTPARCEL_PY"] = sys.argv[1]
spec = importlib.util.spec_from_file_location("mcpmod", sys.argv[2])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
names = [t["name"] for t in mod.TOOLS]
need = ["inspect", "split_zip", "split_any_file", "split_files", "verify", "rebuild", "make_apps_bundle"]
missing = [n for n in need if n not in names]
if missing:
    raise SystemExit("missing tools " + ",".join(missing))
with tempfile.TemporaryDirectory(prefix="ap34mcp-") as tmp:
    src = os.path.join(tmp, "movie.bin")
    data = b"FRAME" + os.urandom(5000)
    open(src, "wb").write(data)
    job = mod.Job(None)
    res, text = mod.tool_split_any_file({"path": src, "max_bytes": 1200, "output_dir": tmp, "include_apps": False}, job)
    if not res["ok"] or res["mode"] != "bytes" or res["sha256"] != hashlib.sha256(data).hexdigest():
        raise SystemExit("split_any_file result bad")
    folder = res["output_dir"]
    v, vtext = mod.tool_verify({"parts": [folder]}, mod.Job(None))
    if not v["ok"] or v["missing_parts"]:
        raise SystemExit("verify failed " + vtext)
    rebuilt, _t = mod.tool_rebuild({"parts": [folder], "output_dir": tmp}, mod.Job(None))
    if open(rebuilt["output_path"], "rb").read() != data:
        raise SystemExit("mcp rebuild mismatch")
    os.remove(os.path.join(folder, res["parts"][1]["name"]))
    bad, badtext = mod.tool_verify({"parts": [folder]}, mod.Job(None))
    if bad["ok"] or 2 not in bad["missing_parts"]:
        raise SystemExit("mcp verify missed part " + badtext)
    job2 = mod.Job(None)
    job2.cancelled.set()
    src2 = os.path.join(tmp, "other.bin")
    open(src2, "wb").write(os.urandom(200000))
    parent = os.path.join(tmp, "cout")
    os.makedirs(parent)
    try:
        mod.tool_split_any_file({"path": src2, "max_bytes": 4096, "output_dir": parent, "include_apps": False}, job2)
        raise SystemExit("cancel did not raise")
    except mod.Cancelled:
        pass
    junk = []
    for dirpath, dirs, files in os.walk(parent):
        junk.extend(files)
    if junk:
        raise SystemExit("cancel left files " + ",".join(junk))
print("MCP_OK " + ",".join(names))
'''
    proc = subprocess.run([sys.executable, "-c", mcp_script, CORE, MCP], capture_output=True, text=True)
    blob = proc.stdout + proc.stderr
    check("mcp tools and cancel", proc.returncode == 0 and "MCP_OK" in blob, "exit %s\n%s" % (proc.returncode, blob))

    # the standalone script in src/ matches what a kit would run
    check("src rebuild.py exists", os.path.isfile(REBUILD))

    if failures:
        print("%d FAILED" % len(failures))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
