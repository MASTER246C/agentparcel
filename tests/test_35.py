#!/usr/bin/env python3
"""AgentParcel 3.5.0: presets, regenerate, zlib, AES-GCM, and 3.4.0 compatibility."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "src", "agentparcel", "core.py")
MCP = os.path.join(ROOT, "src", "agentparcel", "mcp.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    zs = load(CORE, "zs35")
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("PASS", name)
        else:
            print("FAIL", name, detail)
            failures.append(name)

    for key, info in zs.PRESETS.items():
        if info["part_bytes"] is None:
            continue
        check("preset under cap " + key, info["part_bytes"] < info["advertised_bytes"], info)
    check("preset names", set(zs.PRESET_ORDER) == set(zs.PRESETS))
    try:
        zs.limit_from_preset("nope", 1000)
        check("unknown preset", False, "no error")
    except zs.ZsError as ex:
        check("unknown preset", "chatgpt-dot" in str(ex))
    limit, key = zs.limit_from_preset("discord", 999)
    check("discord cap", limit == 24000000 and key == "discord", limit)
    limit, key = zs.limit_from_preset("custom", 12345)
    check("custom cap", limit == 12345 and key == "custom", limit)

    password = "s3cret-parcel"
    with tempfile.TemporaryDirectory(prefix="ap35-") as tmp:
        raw = os.path.join(tmp, "clip.bin")
        payload = b"PLAIN-3.4 " + os.urandom(8000)
        with open(raw, "wb") as f:
            f.write(payload)
        plain = zs.split_any_file(raw, limit=1000, include_apps=False)
        manifest = json.load(open(os.path.join(plain["output_dir"], "_agentparcel_bytes.json"), encoding="utf-8"))
        check("plain manifest has no compression key", "compression" not in manifest and "encryption" not in manifest and "preset" not in manifest)
        check("plain part size is raw size", manifest["parts"][0]["size"] <= 1000 and "rawSize" not in manifest["parts"][0])
        folder = plain["output_dir"]
        good_name = manifest["parts"][0]["name"]
        good_before = open(os.path.join(folder, good_name), "rb").read()
        missing_name = manifest["parts"][1]["name"]
        os.remove(os.path.join(folder, missing_name))
        try:
            zs.rebuild([folder])
            check("rebuild names still needed", False, "no error")
        except zs.ZsError as ex:
            check("rebuild names still needed", "Still needed:" in str(ex) and missing_name in str(ex), str(ex))
        regen = zs.regenerate_parts(raw, [folder])
        check("regenerate missing", regen["ok"] and any(item["name"] == missing_name for item in regen["regenerated"]), regen)
        good_after = open(os.path.join(folder, good_name), "rb").read()
        check("good part untouched", good_before == good_after)
        check("regenerated file matches", sha(zs.rebuild([folder], os.path.join(tmp, "out"))["output"]) == sha(raw))

        fresh = zs.split_any_file(raw, limit=1000, include_apps=False)
        ff = fresh["output_dir"]
        man2 = json.load(open(os.path.join(ff, "_agentparcel_bytes.json"), encoding="utf-8"))
        target = os.path.join(ff, man2["parts"][1]["name"])
        keep = open(os.path.join(ff, man2["parts"][0]["name"]), "rb").read()
        with open(target, "r+b") as f:
            f.seek(0)
            b0 = f.read(1)
            f.seek(0)
            f.write(bytes([b0[0] ^ 0x5A]))
        fixed = zs.regenerate_parts(raw, [ff], part_numbers=[2])
        check("regenerate corrupt part only", fixed["ok"] and [item["part"] for item in fixed["regenerated"]] == [2], fixed)
        check("other part untouched on corrupt regen", open(os.path.join(ff, man2["parts"][0]["name"]), "rb").read() == keep)

        preset_split = zs.split_any_file(raw, preset="chatgpt-dot", include_apps=False)
        pman = json.load(open(os.path.join(preset_split["output_dir"], "_agentparcel_bytes.json"), encoding="utf-8"))
        check("preset recorded", pman.get("preset") == "chatgpt-dot" and pman["limitBytes"] == 19000000, pman.get("limitBytes"))
        check("preset one part for small file", pman["partCount"] == 1, pman["partCount"])

        comp = zs.split_any_file(raw, limit=1500, include_apps=False, compress=True)
        cdir = comp["output_dir"]
        cman = json.load(open(os.path.join(cdir, "_agentparcel_bytes.json"), encoding="utf-8"))
        check("compression recorded", cman.get("compression", {}).get("algorithm") == "zlib" and password not in json.dumps(cman))
        check("compressed parts at or under cap", all(os.path.getsize(p) <= 1500 for p, _s in comp["parts"]))
        proc = subprocess.run([sys.executable, os.path.join(cdir, "rebuild.py")], cwd=cdir, capture_output=True, text=True)
        made = os.path.join(cdir, "clip.bin")
        check("rebuild.py decompresses", proc.returncode == 0 and os.path.isfile(made) and open(made, "rb").read() == payload,
              proc.stderr + proc.stdout)
        howto = open(os.path.join(cdir, "HOW-TO-REBUILD.txt"), encoding="utf-8").read()
        check("compressed howto", "zlib" in howto and "python3 rebuild.py" in howto)

        enc = zs.split_any_file(raw, limit=1800, include_apps=False, compress=True, password=password)
        edir = enc["output_dir"]
        eman = json.load(open(os.path.join(edir, "_agentparcel_bytes.json"), encoding="utf-8"))
        blob = json.dumps(eman)
        check("encryption recorded without password",
              eman.get("encryption", {}).get("algorithm") == "AES-256-GCM"
              and eman["encryption"].get("kdf") == "scrypt"
              and password not in blob and "salt" in eman["encryption"] and "nonce" in eman["parts"][0],
              eman.get("encryption"))
        check("encrypted parts under cap", all(os.path.getsize(p) <= 1800 for p, _s in enc["parts"]))
        rebuilt = zs.rebuild([edir], os.path.join(tmp, "enc-out"), password=password)
        check("decrypt round trip", open(rebuilt["output"], "rb").read() == payload)
        try:
            zs.rebuild([edir], os.path.join(tmp, "bad-pw"), password="wrong-password")
            check("wrong password refused", False, "no error")
        except zs.ZsError as ex:
            check("wrong password refused", "password" in str(ex).lower() and password not in str(ex), str(ex))
        before = set(os.listdir(edir))
        proc = subprocess.run([sys.executable, os.path.join(edir, "rebuild.py")], cwd=edir, capture_output=True, text=True)
        check("rebuild.py refuses encryption",
              proc.returncode == 2 and "AES-256-GCM" in proc.stderr and "cryptography" in proc.stderr
              and not os.path.isfile(os.path.join(edir, "clip.bin")) and set(os.listdir(edir)) == before,
              proc.stderr)
        ehowto = open(os.path.join(edir, "HOW-TO-REBUILD.txt"), encoding="utf-8").read()
        check("encrypted howto", "password is not stored" in ehowto and "cryptography" in ehowto)

        # drop one encrypted part and regenerate it; the untouched part keeps its bytes
        ename = eman["parts"][0]["name"]
        ekeep = open(os.path.join(edir, ename), "rb").read()
        os.remove(os.path.join(edir, eman["parts"][-1]["name"]))
        egen = zs.regenerate_parts(raw, [edir], password=password)
        check("regenerate encrypted missing", egen["ok"], egen.get("message"))
        check("encrypted good part untouched", open(os.path.join(edir, ename), "rb").read() == ekeep)
        check("encrypted set rebuilds after regen",
              open(zs.rebuild([edir], os.path.join(tmp, "enc2"), password=password)["output"], "rb").read() == payload)

        zpath = os.path.join(tmp, "notes.zip")
        body = os.urandom(700000)
        with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("notes/readme.txt", body)
        zsplit = zs.Splitter(zpath, limit=300000, include_apps=False).run()
        zdir = zsplit["output_dir"]
        check("zip has several parts", len(zsplit["parts"]) >= 2, len(zsplit["parts"]))
        if len(zsplit["parts"]) >= 2:
            gone = zsplit["parts"][1][0]
            os.remove(gone)
            zregen = zs.regenerate_parts(zpath, [zdir])
            check("regenerate zip part", zregen["ok"] and zregen["regenerated"], zregen.get("message"))
            joined = zs.rebuild([zdir], os.path.join(tmp, "zip-out"))
            with zipfile.ZipFile(joined["output"]) as zf:
                check("zip rebuild after regen", zf.read("notes/readme.txt") == body)

    os.environ["AGENTPARCEL_PY"] = CORE
    mcp = load(MCP, "mcp35")
    names = [t["name"] for t in mcp.TOOLS]
    check("mcp lists regenerate_parts", "regenerate_parts" in names and names.index("verify") < names.index("regenerate_parts"))
    schema = {t["name"]: t["inputSchema"] for t in mcp.TOOLS}
    check("preset on split_zip", "preset" in schema["split_zip"]["properties"])
    check("preset on split_any_file", "preset" in schema["split_any_file"]["properties"] and "compress" in schema["split_any_file"]["properties"])
    try:
        mcp.get_limit({"preset": "email", "max_bytes": 10})
        check("preset conflicts with max_bytes", False, "no error")
    except mcp.ToolError as ex:
        check("preset conflicts with max_bytes", "max_bytes" in str(ex), str(ex))
    check("email preset bytes", mcp.get_limit({"preset": "email"}) == 24000000)

    lic = open(os.path.join(ROOT, "LICENSE.txt"), encoding="utf-8").read()
    lic2 = open(os.path.join(ROOT, "src", "release", "LICENSE.txt"), encoding="utf-8").read()
    sentence = "ZipSplitter was only an internal working name, and AgentParcel is not affiliated with or derived from any other project of that name."
    check("license sentence", sentence in lic and lic == lic2 and "formerly named ZipSplitter" not in lic)
    mac = "Mac users: if you hit an issue or can help test, reach out via chriskalkowski.com."
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    notes = open(os.path.join(ROOT, "src", "release", "RELEASE-NOTES.md"), encoding="utf-8").read()
    mac_readme = open(os.path.join(ROOT, "src", "release", "README-macos.md"), encoding="utf-8").read()
    check("mac community note",
          mac in readme and mac in notes and mac in mac_readme and "community-tested/beta" in mac_readme.lower())

    if failures:
        print("%d FAILED" % len(failures))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
