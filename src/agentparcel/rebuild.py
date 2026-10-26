#!/usr/bin/env python3
"""Rebuild a file that AgentParcel split into raw byte parts. Python 3 stdlib only.

  python3 rebuild.py [folder]

The folder defaults to the directory that contains this script. A byte-split set
has _agentparcel_bytes.json plus <name>_part01, _part02, ... This checks every
part's SHA-256, writes the original file (it never overwrites an existing file),
and checks the whole file's SHA-256.

A zip part set has _agentparcel_zipset.json. This script only verifies those part
files. Rebuilding the original zip from them is done by AgentParcel, because the
file manifest lives inside the parts (_zipsplitter_manifest.json).
"""
import hashlib
import json
import os
import sys
import zlib

BYTES_NAME = "_agentparcel_bytes.json"
ZIPSET_NAME = "_agentparcel_zipset.json"
BUF = 1024 * 1024


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(BUF)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def unique_path(wanted):
    if not os.path.exists(wanted):
        return wanted
    directory, filename = os.path.split(wanted)
    stem, ext = os.path.splitext(filename)
    n = 2
    while True:
        cand = os.path.join(directory, "%s (%d)%s" % (stem, n, ext))
        if not os.path.exists(cand):
            return cand
        n += 1


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def verify_parts(folder, parts):
    missing = []
    corrupt = []
    for part in parts:
        name = part["name"]
        path = os.path.join(folder, name)
        number = int(part["part"])
        if not os.path.isfile(path):
            missing.append(number)
            continue
        size = os.path.getsize(path)
        digest = sha256_file(path)
        expect_size = int(part["size"])
        expect_hash = str(part["sha256"]).lower()
        if size != expect_size or digest != expect_hash:
            corrupt.append(number)
    return missing, corrupt


def report_bad(missing, corrupt, parts):
    names = {int(p["part"]): p.get("name") or "" for p in parts}
    lines = []
    if missing:
        lines.append("Missing part(s): %s" % ", ".join(str(n) for n in missing))
    if corrupt:
        lines.append("Corrupt part(s): %s" % ", ".join(str(n) for n in corrupt))
    bits = []
    for n in list(missing) + list(corrupt):
        bits.append(("part %s %s" % (n, names.get(int(n), ""))).strip())
    if bits:
        lines.append("Still needed: " + ", ".join(bits))
    text = "\n".join(lines)
    sys.stderr.write(text + "\n")
    return text


def _plain_blocks(path, manifest):
    comp = manifest.get("compression")
    if not comp:
        with open(path, "rb") as src:
            while True:
                block = src.read(BUF)
                if not block:
                    break
                yield block
        return
    algo = str(comp.get("algorithm") or "")
    if algo != "zlib":
        raise SystemExit("Unsupported compression: %s" % algo)
    dec = zlib.decompressobj()
    with open(path, "rb") as src:
        while True:
            block = src.read(BUF)
            if not block:
                break
            out = dec.decompress(block)
            if out:
                yield out
    tail = dec.flush()
    if tail:
        yield tail


def rebuild_bytes(folder, manifest):
    if manifest.get("encryption"):
        sys.stderr.write(
            "This part set is encrypted (AES-256-GCM). rebuild.py cannot decrypt it\n"
            "and will not write a file. The password is not stored in this folder.\n"
            "Install AgentParcel with the cryptography package and rebuild there:\n"
            "  pip install agentparcel[crypto]\n"
            "Then run AgentParcel (or: python3 agentparcel.py --join this-folder)\n"
            "and give the same password.\n"
        )
        return 2
    parts = sorted(manifest["parts"], key=lambda p: int(p["part"]))
    missing, corrupt = verify_parts(folder, parts)
    if missing or corrupt:
        report_bad(missing, corrupt, parts)
        return 2
    original = manifest["originalName"]
    dest = unique_path(os.path.join(folder, original))
    tmp = dest + ".partial"
    whole = hashlib.sha256()
    try:
        with open(tmp, "wb") as out:
            for part in parts:
                path = os.path.join(folder, part["name"])
                for block in _plain_blocks(path, manifest):
                    out.write(block)
                    whole.update(block)
        digest = whole.hexdigest()
        expect = str(manifest["sha256"]).lower()
        if digest != expect or os.path.getsize(tmp) != int(manifest["originalSize"]):
            raise SystemExit("Rebuilt file does not match the manifest SHA-256.")
        os.rename(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print("Rebuilt %s" % dest)
    print("SHA-256 %s" % digest)
    return 0


def verify_zipset(folder, manifest):
    parts = sorted(manifest["parts"], key=lambda p: int(p["part"]))
    missing, corrupt = verify_parts(folder, parts)
    if missing or corrupt:
        report_bad(missing, corrupt, parts)
        return 2
    print("All %d zip part file(s) match the manifest checksums." % len(parts))
    print("These are zip parts. Rebuild the original archive with AgentParcel")
    print("(Rebuild from parts). This script does not reassemble zip part sets.")
    return 0


def main(argv):
    folder = argv[1] if len(argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    folder = os.path.abspath(folder)
    bytes_path = os.path.join(folder, BYTES_NAME)
    zip_path = os.path.join(folder, ZIPSET_NAME)
    if os.path.isfile(bytes_path):
        return rebuild_bytes(folder, load_json(bytes_path))
    if os.path.isfile(zip_path):
        return verify_zipset(folder, load_json(zip_path))
    sys.stderr.write("No %s or %s in %s\n" % (BYTES_NAME, ZIPSET_NAME, folder))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
