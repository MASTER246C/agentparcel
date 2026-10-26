#!/usr/bin/env python3
"""
AgentParcel for macOS and Linux  (agentparcel.py, see VERSION below)

Split a .zip into smaller standalone .zip parts (default <= 19.5 MB each) and rebuild the
original zip from them. Uses exactly the same part label / manifest format as the Windows
version (AgentParcel.ps1 3.x), so parts made on Windows can be rebuilt here and vice versa.

  GUI:   python3 agentparcel.py                      (or the AgentParcel.command / agentparcel.sh launchers)
  Split: python3 agentparcel.py --no-gui [--limit-mb 19.5] [--no-unpack-inner] [--output-dir DIR] FILE.zip
  Join:  python3 agentparcel.py --join PART_OR_FOLDER [MORE_PARTS...] [--output-dir DIR]

Standard library only, plus the optional cryptography package when parts are encrypted.
Python 3.9 or newer.
"""
import sys

if sys.version_info < (3, 9):
    sys.stderr.write("AgentParcel needs Python 3.9 or newer (this is Python %d.%d).\n"
                     "Install a newer Python from https://www.python.org/downloads/\n" % sys.version_info[:2])
    sys.exit(1)

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
import zlib

_VERSION_MARKER = "@@ZS_VERSION@@"


def _resolved_version(marker):
    # build.py replaces the marker in release zips. A checkout or a wheel keeps the marker
    # and reads src/VERSION, then the installed package version.
    if not str(marker).startswith("@@"):
        return str(marker)
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in ("VERSION", os.path.join("..", "VERSION"), os.path.join("..", "..", "src", "VERSION")):
        path = os.path.normpath(os.path.join(here, rel))
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read().strip()
            if text and not text.startswith("@@"):
                return text
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("agentparcel")
    except Exception:
        return "0.0.0"


VERSION = _resolved_version(_VERSION_MARKER)
TOOL = "agentparcel.py " + VERSION
APPS_NAME = "AgentParcel-apps.zip"
# The _zipsplitter_* file names and "zipsplitter-*" format ids are the on-disk format from when
# AgentParcel was called ZipSplitter. They are kept on purpose so ZipSplitter 3.x can still rebuild
# AgentParcel parts (and skip AgentParcel-apps.zip) and AgentParcel reads every older set.
APPS_MARKER = "_zipsplitter_apps.json"
MANIFEST_NAME = "_zipsplitter_manifest.json"
STUB_NAME = "_zipsplitter_part.json"
BYTES_MANIFEST = "_agentparcel_bytes.json"
ZIPSET_MANIFEST = "_agentparcel_zipset.json"
HOWTO_NAME = "HOW-TO-REBUILD.txt"
REBUILD_SCRIPT_NAME = "rebuild.py"
COPY_BUF = 1 << 20
ZIP64_FORCE = 0x7FFF0000          # entries this big (or bigger) are written with zip64 headers
DEFAULT_LIMIT = int(19.5 * 1024 * 1024)
ZLIB_LEVEL = 6
# scrypt parameters stored in the manifest (never the password) so a later release can change them.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 32

# part_bytes is what AgentParcel writes. advertised_bytes is the published cap we stay under.
# Every named cap is decimal (20 MB = 20,000,000). Limits change; confirm the current one.
PRESET_ORDER = ("custom", "chatgpt-dot", "chat-512", "discord", "email", "github-release")
PRESETS = {
    "custom": {
        "part_bytes": None,
        "advertised_bytes": None,
        "title": "Custom",
        "note": "Use the size you type. The default is 19.5 MiB (20,447,232 bytes).",
        "source": "AgentParcel's own default, the same 19.5 MiB cap as 3.4.0.",
    },
    "chatgpt-dot": {
        "part_bytes": 19000000,
        "advertised_bytes": 20000000,
        "title": "ChatGPT Dot (20 MB)",
        "note": "Part cap 19,000,000 bytes, under a 20,000,000 byte upload cap.",
        "source": "ChatGPT Dot was treated as a 20 MB (20,000,000 byte) upload cap when AgentParcel was started. The limit can change.",
    },
    "chat-512": {
        "part_bytes": 500000000,
        "advertised_bytes": 512000000,
        "title": "Chat 512 MB",
        "note": "Part cap 500,000,000 bytes, under a 512,000,000 byte chat upload cap.",
        "source": "Some chat products document a 512 MB upload cap. This preset uses 512,000,000 advertised bytes. Products differ, and the limit can change.",
    },
    "discord": {
        "part_bytes": 24000000,
        "advertised_bytes": 25000000,
        "title": "Discord (25 MB)",
        "note": "Part cap 24,000,000 bytes for the free 25 MB limit. Nitro is higher and is not this preset.",
        "source": "Discord's non-Nitro attachment limit is taken as 25 MB (25,000,000 bytes). Nitro allows larger files. Discord has changed this number before.",
    },
    "email": {
        "part_bytes": 24000000,
        "advertised_bytes": 25000000,
        "title": "Email (25 MB)",
        "note": "Part cap 24,000,000 bytes, under a common 25 MB attachment cap.",
        "source": "Many mailboxes, including Gmail, cap a message around 25 MB (25,000,000 bytes). Other providers use 10 MB or 20 MB, and headers count toward the cap. The limit can change.",
    },
    "github-release": {
        "part_bytes": 1900000000,
        "advertised_bytes": 2000000000,
        "title": "GitHub release (2 GB)",
        "note": "Part cap 1,900,000,000 bytes, under a 2 GB release-asset limit.",
        "source": "GitHub documents a 2 GB maximum for one release asset file. This preset treats that as 2,000,000,000 bytes. The limit can change.",
    },
}


def limit_from_preset(name, custom_bytes):
    key = (name or "custom").strip().lower()
    if key not in PRESETS:
        raise ZsError("Unknown preset %r. Choose one of: %s." % (name, ", ".join(PRESET_ORDER)))
    part = PRESETS[key]["part_bytes"]
    if part is None:
        return int(custom_bytes), key
    return int(part), key


def _password_bytes(password):
    if isinstance(password, bytes):
        raw = password
    elif isinstance(password, str) and password != "":
        raw = password.encode("utf-8")
    else:
        raise ZsError("A password is required. It is not stored in the part set.")
    return raw


def _load_crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError:
        raise ZsError(
            "Encryption needs the optional cryptography package. Install it with: pip install agentparcel[crypto]"
        )
    return AESGCM, Scrypt


def _kdf_params(enc):
    return {
        "n": int(enc.get("n", SCRYPT_N)),
        "r": int(enc.get("r", SCRYPT_R)),
        "p": int(enc.get("p", SCRYPT_P)),
        "length": int(enc.get("length", SCRYPT_LEN)),
    }


def derive_key(password, enc):
    _AESGCM, Scrypt = _load_crypto()
    params = _kdf_params(enc)
    kdf = Scrypt(salt=bytes.fromhex(enc["salt"]), length=params["length"], n=params["n"], r=params["r"], p=params["p"])
    return kdf.derive(_password_bytes(password))


def _aad(set_id, part_number, original_name):
    return ("%s|%d|%s" % (set_id, int(part_number), original_name or "")).encode("utf-8")


def _encoded_len(raw, compress, encrypt):
    blob = zlib.compress(raw, ZLIB_LEVEL) if compress else raw
    return len(blob) + (16 if encrypt else 0)


def _encode_blob(raw, compress, aesgcm, nonce, aad):
    blob = zlib.compress(raw, ZLIB_LEVEL) if compress else raw
    if aesgcm is not None:
        blob = aesgcm.encrypt(nonce, blob, aad)
    return blob


def decode_part_payload(blob, manifest, part, password, cache):
    enc = manifest.get("encryption")
    comp = manifest.get("compression")
    if enc:
        if not part.get("nonce"):
            raise ZsError("Part %s is encrypted but the manifest has no nonce." % part.get("part"))
        if cache.get("aes") is None:
            AESGCM, _Scrypt = _load_crypto()
            cache["aes"] = AESGCM(derive_key(password, enc))
        try:
            blob = cache["aes"].decrypt(bytes.fromhex(part["nonce"]), blob, _aad(
                manifest.get("setId"), part.get("part"), manifest.get("originalName")))
        except ZsError:
            raise
        except Exception:
            raise ZsError("Could not decrypt part %s (%s). The password may be wrong." % (
                part.get("part"), part.get("name")))
    if comp:
        algo = str(comp.get("algorithm") or "")
        if algo != "zlib":
            raise ZsError("Unsupported compression: %s" % algo)
        blob = zlib.decompress(blob)
    return blob


# The block between the two marker lines is generated by build.py: it carries the release files
# (Windows, Mac and Linux versions) used to write AgentParcel-apps.zip. Do not edit it by hand.
#==ZS-PAYLOAD-BEGIN==
PAYLOAD = ""
#==ZS-PAYLOAD-END==


class ZsError(Exception):
    """A user-facing error (bad input, missing parts, verification failure...)."""

    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data or {}


class Cancelled(BaseException):
    """The user or the MCP client stopped the job. Message is exactly 'Cancelled'."""

    def __init__(self):
        super().__init__("Cancelled")


# ============================================================================
# CORE: shared helpers
# ============================================================================

class Progress:
    def __init__(self, callback=None, should_cancel=None):
        self.cb = callback
        self.should_cancel = should_cancel
        self.total = 1.0
        self.done = 0.0
        self.last = -1
        self.msg = ""

    def add(self, n):
        self.done += n
        self.report()

    def report(self, msg=None):
        if self.should_cancel and self.should_cancel():
            raise Cancelled()
        if msg:
            self.msg = msg
        pct = int(max(0, min(100, math.floor(100.0 * self.done / max(1.0, self.total)))))
        if self.cb and (pct != self.last or msg):
            self.last = pct
            self.cb(pct, self.msg)


def overhead(name):
    # local header (30) + central dir record (46) + name twice + room for zip64 extras / descriptor
    return 30 + 46 + 2 * len(name.encode("utf-8")) + 96


def new_compressor():
    # Exactly what zipfile uses for ZIP_DEFLATED with the default level.
    return zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)


def deflated_len(data):
    co = new_compressor()
    return len(co.compress(data)) + len(co.flush())


def time_str(date_time):
    try:
        return "%04d-%02d-%02d %02d:%02d:%02d" % tuple(date_time[:6])
    except Exception:
        return ""


def parse_time(value):
    try:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", str(value))
        if m:
            t = tuple(int(x) for x in m.groups())
            if 1980 <= t[0] <= 2107:
                return t
    except Exception:
        pass
    return time.localtime()[:6]


def is_dir_name(name):
    return name.endswith("/") or name.endswith("\\")


def make_info(name, date_time, compress=True, external_attr=None):
    zi = zipfile.ZipInfo(name, date_time=tuple(date_time))
    if is_dir_name(name):
        zi.compress_type = zipfile.ZIP_STORED
        zi.external_attr = (0o40755 << 16) | 0x10
    else:
        zi.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
        zi.external_attr = external_attr if external_attr else (0o100644 << 16)
    return zi


def copy_stream(src, dst, prog, hasher=None):
    n = 0
    while True:
        chunk = src.read(COPY_BUF)
        if not chunk:
            break
        if hasher is not None:
            hasher.update(chunk)
        if dst is not None:
            dst.write(chunk)
        n += len(chunk)
        prog.add(len(chunk))
    return n


def unique_path(wanted):
    if not os.path.exists(wanted):
        return wanted
    d, fn = os.path.split(wanted)
    stem, ext = os.path.splitext(fn)
    n = 2
    while True:
        cand = os.path.join(d, "%s (%d)%s" % (stem, n, ext))
        if not os.path.exists(cand):
            return cand
        n += 1


def jdump(obj):
    # Compact, ASCII-only JSON (non-ASCII as \\uXXXX), same style as the Windows version.
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"))


def read_json_entry(zf, name):
    with zf.open(name) as f:
        return json.loads(f.read().decode("utf-8-sig"))


def rejoin_text(name, pieces, first_part, last_part):
    win = name.replace("/", "\\")
    lines = [
        "This file was too large for one zip part, so it was cut into raw pieces:",
        "  " + name,
        "Pieces: %d  (stored in %s .. %s)" % (len(pieces), first_part, last_part),
        "",
        'Easiest: open AgentParcel, choose "Rebuild from parts" and drop the parts in.',
        "By hand: extract ALL the part zips into the same folder, then in that folder run",
        "",
        "  macOS / Linux (Terminal):",
        "    cat " + " ".join(shlex.quote(p) for p in pieces) + " > " + shlex.quote(name),
        "",
        "  Windows (Command Prompt):",
        "    copy /b " + "+".join('"%s"' % p.replace("/", "\\") for p in pieces) + ' "' + win + '"',
        "",
        "After checking the rebuilt file, the .### piece files can be deleted.",
        "",
    ]
    return "\n".join(lines)


# ============================================================================
# CORE: apps bundle (AgentParcel-apps.zip with the Windows, Mac and Linux releases)
# ============================================================================

def fill_payload(core, b64, nl, lang):
    """Puts the payload into a program's source. Same algorithm as Set-ZsPayloadText in AgentParcel.ps1."""
    begin = "#==ZS-PAYLOAD-BEGIN==" + nl
    end = "#==ZS-PAYLOAD-END=="
    i = core.find(begin)
    j = core.find(end, max(i, 0))
    if i < 0 or j < i:
        raise ZsError("payload markers not found")
    body = nl.join(b64[k:k + 76] for k in range(0, len(b64), 76))
    if lang == "ps":
        block = "$script:ZsPayload = @'" + nl + body + nl + "'@" + nl
    else:
        block = 'PAYLOAD = """' + nl + body + nl + '"""' + nl
    return core[:i + len(begin)] + block + core[j:]


def payload_b64():
    return "".join(PAYLOAD.split())


def get_payload_files():
    b64 = payload_b64()
    if not b64:
        return None
    import base64
    data = zlib.decompress(base64.b64decode(b64), -15)
    return json.loads(data.decode("utf-8"))["files"]


def is_apps_bundle_name(filename):
    # ZipSplitter-apps*.zip = bundles written by ZipSplitter 3.x (the old name of AgentParcel)
    return re.match(r"^(AgentParcel|ZipSplitter)-apps.*\.zip$", filename, re.IGNORECASE) is not None


def write_apps_bundle(out_dir, limit):
    """Returns (path or None, size, note)."""
    try:
        files = get_payload_files()
    except Exception:
        files = None
    if not files:
        return None, 0, "Apps bundle not included: this copy of AgentParcel has no embedded apps (development copy)."
    b64 = payload_b64()
    ps = fill_payload(files["AgentParcel.ps1"], b64, "\r\n", "ps")
    py = fill_payload(files["agentparcel.py"], b64, "\n", "py")
    f644, f755 = 0o100644 << 16, 0o100755 << 16
    entries = [
        ("HOW TO REBUILD.txt", files["HOW TO REBUILD.txt"], f644),
        ("LICENSE.txt", files["LICENSE.txt"], f644),
        ("Windows/AgentParcel.ps1", ps, f644),
        ("Windows/AgentParcel.bat", files["AgentParcel.bat"], f644),
        ("Windows/README.txt", files["README-windows.txt"], f644),
        ("Windows/Install-Python-for-AgentParcel.bat", files["Install-Python-for-AgentParcel.bat"], f644),
        ("Windows/AgentParcel.ico", base64.b64decode(files["icon-AgentParcel.ico.b64"]), f644),
        ("mac/agentparcel.py", py, f755),
        ("mac/AgentParcel.command", files["AgentParcel.command"], f755),
        ("mac/README.txt", files["README-mac-linux.txt"], f644),
        ("linux/agentparcel.py", py, f755),
        ("linux/agentparcel.sh", files["agentparcel.sh"], f755),
        ("linux/agentparcel.desktop", files["agentparcel.desktop"], f644),
        ("linux/agentparcel.png", base64.b64decode(files["icon-agentparcel-64.png.b64"]), f644),
        ("linux/README.txt", files["README-mac-linux.txt"], f644),
        ("mcp/agentparcel_mcp.py", files["agentparcel_mcp.py"], f755),
        ("mcp/agentparcel.py", py, f755),
        ("mcp/README.txt", files["README-mcp.txt"], f644),
        (APPS_MARKER, jdump({"format": "zipsplitter-apps", "version": VERSION}), f644),
    ]
    path = unique_path(os.path.join(out_dir, APPS_NAME))
    now = time.localtime()[:6]
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as zf:
        for d in ("Windows/", "mac/", "linux/", "mcp/"):
            zi = zipfile.ZipInfo(d, date_time=now)
            zi.create_system = 3
            zi.external_attr = (0o40755 << 16) | 0x10
            zf.writestr(zi, b"")
        for name, text, mode in entries:
            zi = zipfile.ZipInfo(name, date_time=now)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3
            zi.external_attr = mode
            zf.writestr(zi, text if isinstance(text, bytes) else text.encode("utf-8"))
    size = os.path.getsize(path)
    if size > limit:
        os.remove(path)
        return None, 0, "Apps bundle not included: it is %.2f MB, bigger than the size limit." % (size / 1048576.0)
    return path, size, None


# ============================================================================
# CORE: SPLIT
# ============================================================================

class Item:
    __slots__ = ("kind", "name", "zf", "zi", "comp", "cost", "length", "data", "is_manifest", "date_time")

    def __init__(self, kind, name, zf=None, zi=None, comp=0, cost=0, length=0, data=None, is_manifest=False, date_time=None):
        self.kind, self.name, self.zf, self.zi = kind, name, zf, zi
        self.comp, self.cost, self.length, self.data = comp, cost, length, data
        self.is_manifest = is_manifest
        self.date_time = date_time if date_time is not None else (zi.date_time if zi is not None else time.localtime()[:6])


def write_part(path, items, prog):
    """Writes one part zip. Item kinds: dir | file | bytes | blob."""
    if os.path.exists(path):
        os.remove(path)
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for it in items:
            if it.kind == "dir":
                zf.writestr(make_info(it.name, it.date_time), b"")
            elif it.kind == "file":
                ext = it.zi.external_attr if (it.zi.external_attr >> 16) else None
                zi = make_info(it.name, it.date_time, external_attr=ext)
                with it.zf.open(it.zi) as src, zf.open(zi, "w", force_zip64=it.length >= ZIP64_FORCE) as dst:
                    copy_stream(src, dst, prog)
            elif it.kind in ("bytes", "blob"):
                zi = make_info(it.name, it.date_time)
                with zf.open(zi, "w", force_zip64=len(it.data) >= ZIP64_FORCE) as dst:
                    dst.write(it.data)
    return os.path.getsize(path)


def append_text_entry(path, name, text):
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr(make_info(name, time.localtime()[:6]), text.encode("utf-8"))
    return os.path.getsize(path)


class Splitter:
    def __init__(self, source, output_dir=None, limit=DEFAULT_LIMIT, unpack_inner=True, progress=None, include_apps=True, should_cancel=None, set_id=None, created=None):
        self.source = os.path.abspath(source)
        self.include_apps = bool(include_apps)
        self.output_dir = output_dir
        self.limit = int(limit)
        self.unpack = bool(unpack_inner)
        self.prog = Progress(progress, should_cancel)
        self.fixed_set_id = set_id
        self.fixed_created = created
        self._owned = []
        self._created_dir = False
        self._out_dir = None
        self.m_entries = []
        self.m_archives = []
        self.counter = 0
        self.opened = []
        self.unpacked = []
        self.failed = []
        self.tempdir = None

    def _discard_owned(self):
        for path in self._owned:
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        self._owned = []
        directory = self._out_dir
        if self._created_dir and directory and os.path.isdir(directory):
            try:
                if not os.listdir(directory):
                    os.rmdir(directory)
            except OSError:
                pass

    # ---- phase 1 ----
    def add_archive_items(self, zf, prefix, items, budget, unpack, depth, archive_id):
        infos = zf.infolist()
        names = [i.filename.replace("\\", "/").lower() for i in infos]
        for zi in infos:
            name = prefix + zi.filename
            if is_dir_name(zi.filename):
                items.append(Item("dir", name, zf, zi, 0, overhead(name), 0))
                self.m_entries.append({"archive": archive_id, "name": zi.filename, "type": "dir", "stored": name,
                                       "time": time_str(zi.date_time)})
                continue
            if unpack and depth < 20 and zi.filename.lower().endswith(".zip"):
                if self.expand_inner(zf, zi, name, names, items, budget, depth, archive_id):
                    continue
            self.prog.report("Analyzing " + name)
            co = new_compressor()
            h = hashlib.sha256()
            comp = 0
            with zf.open(zi) as f:
                while True:
                    chunk = f.read(COPY_BUF)
                    if not chunk:
                        break
                    h.update(chunk)
                    comp += len(co.compress(chunk))
                    self.prog.add(len(chunk))
            comp += len(co.flush())
            cost = comp + overhead(name)
            kind = "chunked" if cost > budget else "file"
            items.append(Item(kind, name, zf, zi, comp, cost, zi.file_size))
            self.m_entries.append({"archive": archive_id, "name": zi.filename, "type": "file", "stored": name,
                                   "size": zi.file_size, "sha256": h.hexdigest(), "split": kind == "chunked",
                                   "time": time_str(zi.date_time)})

    def expand_inner(self, zf, zi, name, sibling_names, items, budget, depth, parent_id):
        folder = name[:-4]
        rel = zi.filename.replace("\\", "/")
        rel_folder = (rel[:-4] + "/").lower()
        clash = any(n.startswith(rel_folder) for n in sibling_names)
        prefix = folder + ("_unzipped/" if clash else "/")
        self.prog.report("Unpacking " + name)
        tmp = os.path.join(self.tempdir, uuid.uuid4().hex + ".zip")
        save_e, save_a = len(self.m_entries), len(self.m_archives)
        self.counter += 1
        my_id = self.counter
        adjust = 0.0
        inner = None
        sub = []
        try:
            h = hashlib.sha256()
            with zf.open(zi) as src, open(tmp, "xb") as out:
                copy_stream(src, out, self.prog, h)
            zip_sha = h.hexdigest()
            inner = zipfile.ZipFile(tmp, "r")
            inner_total = float(sum(i.file_size for i in inner.infolist()))
            adjust = 2.0 * inner_total - float(zi.file_size)
            self.prog.total += adjust
            self.m_archives.append({"id": my_id, "parent": parent_id, "depth": depth + 1, "entry": zi.filename, "folder": prefix})
            self.add_archive_items(inner, prefix, sub, budget, True, depth + 1, my_id)
            if not sub:
                sub.append(Item("dir", prefix, None, None, 0, overhead(prefix), 0, date_time=zi.date_time))
        except Exception as ex:  # corrupt / encrypted / unsupported inner zip -> keep it as a plain file
            if inner is not None:
                inner.close()
            try:
                os.remove(tmp)
            except OSError:
                pass
            self.prog.total -= adjust
            del self.m_entries[save_e:]
            del self.m_archives[save_a:]
            self.failed.append("%s  (%s)" % (name, ex))
            return False
        self.opened.append(inner)
        items.extend(sub)
        self.unpacked.append(name)
        self.m_entries.append({"archive": parent_id, "name": zi.filename, "type": "zip", "zip": my_id, "folder": prefix,
                               "size": zi.file_size, "sha256": zip_sha, "time": time_str(zi.date_time)})
        return True

    # ---- main ----
    def run(self):
        src = self.source
        if not os.path.isfile(src):
            raise ZsError("File not found: " + src)
        base = os.path.splitext(os.path.basename(src))[0]
        out_dir = self.output_dir
        if not out_dir:
            out_dir = os.path.join(os.path.dirname(src), base + "_split")
            n = 2
            while os.path.isdir(out_dir) and os.listdir(out_dir):
                out_dir = os.path.join(os.path.dirname(src), "%s_split (%d)" % (base, n))
                n += 1
        existed = os.path.isdir(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        out_dir = os.path.abspath(out_dir)
        self._out_dir = out_dir
        self._created_dir = not existed

        limit = self.limit
        fixed = 22 + 56 + 20
        stub_reserve = 4096
        budget = limit - fixed - 32768 - stub_reserve
        chunk_budget = limit - fixed - 131072 - stub_reserve
        if budget < 65536:
            raise ZsError("Limit is too small (minimum is about 0.2 MB).")

        set_id = self.fixed_set_id or uuid.uuid4().hex
        temp_parts = []
        split_files = []
        self.tempdir = tempfile.mkdtemp(prefix="AgentParcel_")
        archive = None
        try:
            try:
                archive = zipfile.ZipFile(src, "r")
            except zipfile.BadZipFile as ex:
                raise ZsError("Not a valid zip file: %s (%s)" % (os.path.basename(src), ex))
            self.prog.total = max(1.0, 2.0 * sum(i.file_size for i in archive.infolist()))
            items = []
            self.m_archives.append({"id": 0, "parent": -1, "depth": 0, "entry": "", "folder": ""})
            self.add_archive_items(archive, "", items, budget, self.unpack, 0, 0)

            manifest = {
                "format": "zipsplitter-manifest", "version": 1, "setId": set_id, "tool": TOOL,
                "created": self.fixed_created or time.strftime("%Y-%m-%d %H:%M:%S"), "originalName": os.path.basename(src),
                "originalSize": os.path.getsize(src), "limitBytes": limit, "unpackInner": self.unpack,
            }
            text = jdump(manifest)[:-1]
            text += ',\n"archives":[\n' + ",\n".join(jdump(a) for a in self.m_archives) + "\n]"
            text += ',\n"entries":[\n' + ",\n".join(jdump(e) for e in self.m_entries) + "\n]}\n"
            m_bytes = text.encode("utf-8")
            m_cost = deflated_len(m_bytes) + overhead(MANIFEST_NAME)
            if m_cost > budget:
                raise ZsError("Too many files: the manifest alone is bigger than one part. Use a larger size limit.")
            pending = [Item("blob", MANIFEST_NAME, cost=m_cost, data=m_bytes, is_manifest=True)]
            pending.extend(items)
            pending.append(Item("blob", MANIFEST_NAME, cost=m_cost, data=m_bytes, is_manifest=True))
            pending.reverse()            # use as a stack: pending[-1] is the next item

            part_no = 0
            while pending:
                nxt = pending[-1]
                if nxt.kind == "chunked":
                    pending.pop()
                    part_no = self._write_pieces(nxt, out_dir, part_no, chunk_budget, temp_parts, split_files)
                    continue
                part_items = []
                used = 0
                has_manifest = False
                while pending and pending[-1].kind != "chunked":
                    cand = pending[-1]
                    if cand.is_manifest and has_manifest:
                        pending.pop()        # never twice in one part
                        continue
                    if part_items and used + cand.cost > budget:
                        break
                    used += cand.cost
                    has_manifest = has_manifest or cand.is_manifest
                    part_items.append(pending.pop())
                if not part_items:
                    continue
                part_no += 1
                tmp = os.path.join(out_dir, "~zs_part%d.tmp" % part_no)
                while True:
                    before = self.prog.done
                    self.prog.report("Writing part %d (%d entries)" % (part_no, len(part_items)))
                    size = write_part(tmp, part_items, self.prog)
                    if size <= limit - stub_reserve:
                        break
                    # estimate was off: move the last entry back and try again
                    self.prog.done = before
                    os.remove(tmp)
                    last = part_items.pop()
                    if not part_items:
                        if last.is_manifest:
                            raise ZsError("Manifest does not fit in one part.")
                        last.kind = "chunked"
                    pending.append(last)
                    if not part_items:
                        break
                if not part_items:
                    part_no -= 1
                    continue
                temp_parts.append(tmp)
        except BaseException:
            for t in temp_parts:
                try:
                    os.remove(t)
                except OSError:
                    pass
            self._discard_owned()
            raise
        finally:
            for z in self.opened:
                try:
                    z.close()
                except Exception:
                    pass
            if archive is not None:
                archive.close()
            shutil.rmtree(self.tempdir, ignore_errors=True)

        digits = max(2, len(str(len(temp_parts))))
        final_names = ["%s_part%s.zip" % (base, str(k + 1).zfill(digits)) for k in range(len(temp_parts))]
        results = []
        owned = []
        apps = None
        try:
            for info in split_files:
                first = final_names[info["parts"][0] - 1]
                last = final_names[info["parts"][-1] - 1]
                note = rejoin_text(info["name"], info["pieces"], first, last)
                info["note"] = note
                for it in info["text_items"]:
                    if it.kind == "blob" and it.name.endswith(".REJOIN.txt"):
                        it.data = note.encode("utf-8")
                write_part(info["text_part"], info["text_items"], Progress(should_cancel=self.prog.should_cancel))
            for k, tmp in enumerate(temp_parts):
                dest = os.path.join(out_dir, final_names[k])
                if os.path.exists(dest):
                    raise ZsError("The output folder already contains " + final_names[k] + " - choose an empty folder.")
                os.rename(tmp, dest)
                owned.append(dest)
                stub = jdump({"format": "zipsplitter-part", "version": 1, "setId": set_id, "part": k + 1,
                              "partCount": len(temp_parts), "originalName": os.path.basename(src), "tool": TOOL})
                size = append_text_entry(dest, STUB_NAME, stub)
                if size > limit:
                    raise ZsError("Internal error: %s exceeded the limit after adding the part label." % final_names[k])
                results.append((dest, size))
            if split_files:
                note_path = os.path.join(out_dir, "REJOIN_INSTRUCTIONS.txt")
                with open(note_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("Some files were too large for a single %.2f MB zip and were cut into pieces.\n" % (limit / 1048576.0))
                    f.write('AgentParcel ("Rebuild from parts") joins them automatically. To do it by hand:\n\n')
                    for info in split_files:
                        f.write(info["note"] + "----------------------------------------\n")
                owned.append(note_path)
            if self.include_apps:
                self.prog.report("Adding " + APPS_NAME + "...")
                try:
                    apps = write_apps_bundle(out_dir, limit)
                except Exception as ex:
                    apps = (None, 0, "Apps bundle could not be created: %s" % ex)
                if apps and apps[0]:
                    owned.append(apps[0])
            kit = write_zip_kit(out_dir, os.path.basename(src), results, limit, set_id, self.prog)
            owned.extend(kit)
            self._owned.extend(owned)
        except BaseException:
            self._owned.extend(owned)
            self._discard_owned()
            raise

        self.prog.done = self.prog.total
        self.prog.report("Done.")
        return {"output_dir": out_dir, "parts": results, "split_files": split_files, "unpacked": list(self.unpacked),
                "failed": list(self.failed), "set_id": set_id, "limit": limit, "apps": apps, "mode": "zip"}

    def _write_pieces(self, item, out_dir, part_no, chunk_budget, temp_parts, split_files):
        ratio = max(0.05, float(item.comp) / max(1.0, float(item.length)))
        raw = int(math.floor(chunk_budget / ratio * 0.97))
        raw = min(raw, max(64 * 1024 * 1024, chunk_budget))
        raw = max(raw, 65536)
        width = max(3, len(str(int(math.ceil(item.length / float(raw) * 1.5 + 1)))))
        info = {"name": item.name, "pieces": [], "parts": [], "text_part": None, "text_items": None}
        buf = bytearray()
        eof = False
        piece = 0
        with item.zf.open(item.zi) as src:
            while True:
                while not eof and len(buf) < raw + 1:
                    d = src.read(min(COPY_BUF, raw + 1 - len(buf)))
                    if not d:
                        eof = True
                    else:
                        buf += d
                if not buf:
                    break
                take = min(len(buf), raw)
                while True:
                    pname = "%s.%s" % (item.name, str(piece + 1).zfill(width))
                    c = deflated_len(memoryview(buf)[:take])
                    if c + overhead(pname) <= chunk_budget or take <= 65536:
                        break
                    take = int(take * 0.9)
                    raw = take
                piece += 1
                is_last = eof and take == len(buf)
                part_no += 1
                tmp = os.path.join(out_dir, "~zs_part%d.tmp" % part_no)
                part_items = [Item("bytes", pname, data=bytes(buf[:take]), date_time=item.zi.date_time)]
                info["pieces"].append(pname)
                info["parts"].append(part_no)
                if is_last:
                    part_items.append(Item("blob", item.name + ".REJOIN.txt", data=b"@@REJOIN@@"))
                    info["text_part"] = tmp
                    info["text_items"] = part_items
                self.prog.report("Writing part %d (piece %d of %s)" % (part_no, piece, item.name))
                size = write_part(tmp, part_items, self.prog)
                if size > self.limit:
                    raise ZsError("Internal error: piece part exceeded the limit (%d bytes)." % size)
                temp_parts.append(tmp)
                self.prog.add(take)
                del buf[:take]
                if is_last:
                    break
        split_files.append(info)
        return part_no


def format_split_summary(r):
    lines = ["Created %d zip part(s) in:" % len(r["parts"]), "  " + r["output_dir"]]
    for p, s in r["parts"]:
        lines.append("  %s  %.2f MB" % (os.path.basename(p), s / 1048576.0))
    if r["unpacked"]:
        lines += ["", "Unpacked %d zip(s) found inside the zip; their contents are in folders named after them." % len(r["unpacked"]),
                  '"Rebuild from parts" turns them back into the original inner zips.']
    if r["failed"]:
        lines += ["", "Could not open %d inner zip(s) (corrupt or encrypted?); kept them as plain files:" % len(r["failed"])]
        lines += ["  " + f for f in r["failed"]]
    if r["split_files"]:
        lines += ["", "NOTE: %d file(s) were too big for one part and were cut into pieces (.001, .002, ...):" % len(r["split_files"])]
        lines += ["  %s  (%d pieces)" % (s["name"], len(s["pieces"])) for s in r["split_files"]]
        lines.append('"Rebuild from parts" joins them automatically (or see REJOIN_INSTRUCTIONS.txt).')
    if r.get("mode") == "bytes":
        lines += ["", "Byte split: the parts are raw pieces of the original file.",
                  "HOW-TO-REBUILD.txt and rebuild.py in that folder rebuild it without AgentParcel."]
    elif os.path.isfile(os.path.join(r["output_dir"], HOWTO_NAME)):
        lines += ["", "HOW-TO-REBUILD.txt and rebuild.py are in that folder."]
    if r.get("apps"):
        path, size, note = r["apps"]
        if path:
            lines += ["", "Included %s (%d KB): AgentParcel for Windows, Mac and Linux, so the" % (os.path.basename(path), round(size / 1024.0)),
                      "recipient can rebuild. Send it along with the parts (it is not a part)."]
        elif note:
            lines += ["", "NOTE: " + note]
    return "\n".join(lines) + "\n"


# ============================================================================
# CORE: JOIN (rebuild)
# ============================================================================

PART_RX = re.compile(r"^(?P<base>.+)_part(?P<n>\d+)\.zip$", re.IGNORECASE)
PIECE_RX = re.compile(r"^(?P<f>.+)\.(?P<n>\d{3,})$")


def part_info(filename):
    m = PART_RX.match(filename)
    if not m:
        return None
    return {"base": m.group("base"), "number": int(m.group("n"))}


def find_part_set(inputs):
    """Expands folders, and a single part into all of its siblings (<name>_partNN.zip)."""
    files = []
    for p in inputs:
        if not p:
            continue
        p = p.strip().strip('"')
        if os.path.isdir(p):
            files += sorted((os.path.join(p, f) for f in os.listdir(p)
                             if f.lower().endswith(".zip") and not is_apps_bundle_name(f)
                             and os.path.isfile(os.path.join(p, f))), key=lambda s: s.lower())
        elif os.path.isfile(p):
            files.append(os.path.abspath(p))
        else:
            raise ZsError("Not found: " + p)
    out, seen = [], set()
    # several items = exactly these parts; one item (the apps bundle does not count) = find its siblings
    explicit = len([p for p in inputs if p and not is_apps_bundle_name(os.path.basename(p.strip().strip('"')))]) > 1
    for f in files:
        key = os.path.abspath(f)
        if key not in seen:
            seen.add(key)
            out.append(key)
        if not explicit:
            pi = part_info(os.path.basename(f))
            if pi:
                d = os.path.dirname(key)
                for s in sorted(os.listdir(d), key=lambda s: s.lower()):
                    si = part_info(s)
                    sp = os.path.join(d, s)
                    if si and si["base"].lower() == pi["base"].lower() and os.path.isfile(sp) and sp not in seen:
                        seen.add(sp)
                        out.append(sp)
    return out


def looks_like_parts(inputs):
    """Used by the GUI / launchers to choose between Split and Rebuild."""
    for p in inputs:
        if not p:
            continue
        p = p.strip().strip('"')
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, BYTES_MANIFEST)):
            return True
        if os.path.isfile(p) and os.path.basename(p) == BYTES_MANIFEST:
            return True
        if os.path.isfile(p) and os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(p)), BYTES_MANIFEST)):
            return True
    inputs = [p for p in inputs if not is_apps_bundle_name(os.path.basename(p))]
    zips = 0
    for p in inputs:
        if os.path.isdir(p):
            return True
        if not os.path.isfile(p):
            continue
        zips += 1
        try:
            with zipfile.ZipFile(p) as z:
                if STUB_NAME in z.namelist():
                    return True
        except Exception:
            pass
    if zips > 1:
        return all(part_info(os.path.basename(p)) for p in inputs)
    return False


def join_output_path(output_dir, parts_dir, original_name, rebuilt_suffix=True):
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return unique_path(os.path.join(os.path.abspath(output_dir), original_name))
    stem = os.path.splitext(original_name)[0]
    return unique_path(os.path.join(parts_dir, stem + "_rebuilt.zip"))


class Joiner:
    def __init__(self, inputs, output_dir=None, progress=None, should_cancel=None):
        self.inputs = list(inputs)
        self.output_dir = output_dir
        self.prog = Progress(progress, should_cancel)
        self.warnings = []
        self.index = {}
        self.by_archive = {}
        self.verified = 0
        self.inner_zips = 0
        self.tempdir = None

    def _find_stored(self, stored):
        if stored in self.index:
            return [self.index[stored]]
        for w in (3, 4, 5, 6):
            if (stored + "." + "1".zfill(w)) in self.index:
                lst, k = [], 1
                while (stored + "." + str(k).zfill(w)) in self.index:
                    lst.append(self.index[stored + "." + str(k).zfill(w)])
                    k += 1
                return lst
        return []

    def _write_archive(self, archive_id, out):
        for rec in self.by_archive.get(archive_id, []):
            name = rec["name"]
            typ = rec.get("type")
            if typ == "dir":
                out.writestr(make_info(name, parse_time(rec.get("time"))), b"")
            elif typ == "file":
                srcs = self._find_stored(rec["stored"])
                if not srcs:
                    raise ZsError("Missing from the parts: " + rec["stored"])
                self.prog.report("Rebuilding " + rec["stored"])
                size = int(rec.get("size", 0))
                zi = make_info(name, parse_time(rec.get("time")))
                h = hashlib.sha256()
                n = 0
                with out.open(zi, "w", force_zip64=size >= ZIP64_FORCE) as dst:
                    for zf, szi in srcs:
                        with zf.open(szi) as s:
                            n += copy_stream(s, dst, self.prog, h)
                if n != size or h.hexdigest() != str(rec.get("sha256", "")).lower():
                    raise ZsError("Verification failed for %s (got %d bytes, expected %d). The parts may be damaged "
                                  "or from different sets." % (rec["stored"], n, size))
                self.verified += 1
            elif typ == "zip":
                self.prog.report("Re-zipping " + name)
                tmp = os.path.join(self.tempdir, uuid.uuid4().hex + ".zip")
                with zipfile.ZipFile(tmp, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as inner:
                    self._write_archive(int(rec["zip"]), inner)
                zsize = os.path.getsize(tmp)
                zi = make_info(name, parse_time(rec.get("time")))
                with open(tmp, "rb") as s, out.open(zi, "w", force_zip64=zsize >= ZIP64_FORCE) as dst:
                    copy_stream(s, dst, self.prog)
                os.remove(tmp)
                self.inner_zips += 1

    def run(self):
        files = find_part_set(self.inputs)
        if not files:
            raise ZsError("No .zip parts found.")
        self.prog.report("Checking %d part(s)..." % len(files))
        opened = []
        self.tempdir = tempfile.mkdtemp(prefix="AgentParcel_")
        try:
            parts = []
            for f in files:
                try:
                    z = zipfile.ZipFile(f, "r")
                except Exception as ex:
                    raise ZsError("Not a readable zip: %s (%s)" % (os.path.basename(f), ex))
                if APPS_MARKER in z.NameToInfo:     # the apps bundle is not a part
                    z.close()
                    continue
                opened.append(z)
                stub = None
                if STUB_NAME in z.NameToInfo:
                    try:
                        stub = read_json_entry(z, STUB_NAME)
                    except Exception:
                        stub = None
                parts.append({"path": f, "zip": z, "stub": stub, "info": part_info(os.path.basename(f))})
            if not parts:
                raise ZsError("No parts found (only the AgentParcel-apps.zip bundle).")
            parts_dir = os.path.dirname(parts[0]["path"])
            labelled = [p for p in parts if p["stub"]]
            if labelled:
                return self._run_manifest(parts, labelled, parts_dir)
            return self._run_legacy(parts, parts_dir, [p["path"] for p in parts])
        finally:
            for z in opened:
                try:
                    z.close()
                except Exception:
                    pass
            shutil.rmtree(self.tempdir, ignore_errors=True)

    def _finish(self, tmp_out, out_path):
        # never overwrite: pick a fresh name if something appeared meanwhile
        if os.path.exists(out_path):
            out_path = unique_path(out_path)
        os.rename(tmp_out, out_path)
        return out_path

    def _run_manifest(self, parts, labelled, parts_dir):
        first = labelled[0]["stub"]
        set_id = str(first.get("setId"))
        part_count = int(first.get("partCount", 0))
        orig = str(first.get("originalName", "rebuilt.zip"))
        use = {}
        for p in parts:
            fn = os.path.basename(p["path"])
            if not p["stub"]:
                self.warnings.append("Ignored (not a AgentParcel part): " + fn)
                continue
            if str(p["stub"].get("setId")) != set_id:
                self.warnings.append("Ignored (belongs to a different split set): " + fn)
                continue
            num = int(p["stub"].get("part", 0))
            if num in use:
                self.warnings.append("Ignored duplicate of part %d: %s" % (num, fn))
                continue
            use[num] = p
        missing = [k for k in range(1, part_count + 1) if k not in use]
        if missing:
            stem = os.path.splitext(orig)[0]
            w = max(2, len(str(part_count)))
            names_list = ["%s_part%s.zip" % (stem, str(k).zfill(w)) for k in missing]
            names = ", ".join(names_list)
            still = _still_needed_text(missing, names_list, [])
            raise ZsError('Missing %d of %d parts of "%s": part %s\n(%s)\n%s' % (
                len(missing), part_count, orig, ", ".join(str(k) for k in missing), names, still), {
                    "missing_parts": list(missing),
                    "missing_names": names_list,
                    "part_count": part_count,
                    "original_name": orig,
                    "still_needed": still,
                })
        manifest = None
        for k in range(1, part_count + 1):
            z = use[k]["zip"]
            if MANIFEST_NAME in z.NameToInfo:
                manifest = read_json_entry(z, MANIFEST_NAME)
                break
        if manifest is None:
            raise ZsError("The manifest (_zipsplitter_manifest.json) was not found in any part.")
        if int(manifest.get("version", 1)) > 1:
            self.warnings.append("Parts were made by a newer AgentParcel (manifest version %s)." % manifest.get("version"))
        for k in range(1, part_count + 1):
            z = use[k]["zip"]
            for zi in z.infolist():
                if zi.filename not in self.index:
                    self.index[zi.filename] = (z, zi)
        depth_of = {int(a["id"]): int(a.get("depth", 0)) for a in manifest.get("archives", [])}
        total = 0.0
        for rec in manifest.get("entries", []):
            aid = int(rec["archive"])
            self.by_archive.setdefault(aid, []).append(rec)
            if rec.get("type") == "file":
                total += float(rec.get("size", 0)) * (1 + depth_of.get(aid, 0))
        self.prog.total = max(1.0, total)
        out_path = join_output_path(self.output_dir, parts_dir, orig)
        tmp_out = os.path.join(os.path.dirname(out_path), "~zs_rebuild_%s.tmp" % uuid.uuid4().hex)
        try:
            with zipfile.ZipFile(tmp_out, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as out:
                self._write_archive(0, out)
            out_path = self._finish(tmp_out, out_path)
        finally:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        self.prog.done = self.prog.total
        self.prog.report("Done.")
        return {"output": out_path, "mode": "manifest", "parts": part_count, "verified": self.verified,
                "inner_zips": self.inner_zips, "entries": len(manifest.get("entries", [])), "joined": 0,
                "warnings": self.warnings, "size": os.path.getsize(out_path)}

    def _run_legacy(self, parts, parts_dir, files):
        self.warnings.append("These parts were made by an older AgentParcel (no manifest): files cannot be verified, "
                             "and inner zips that were unpacked stay as folders (they cannot be turned back into zips).")
        numbered = sorted([p for p in parts if p["info"]], key=lambda p: p["info"]["number"])
        if numbered:
            nums = set(p["info"]["number"] for p in numbered)
            max_n = numbered[-1]["info"]["number"]
            missing = [k for k in range(1, max_n + 1) if k not in nums]
            if missing:
                raise ZsError("Missing part(s): %s (found up to part %d; for old-style parts a missing LAST part "
                              "cannot be detected)." % (", ".join(str(k) for k in missing), max_n))
            self.warnings.append("Old-style parts carry no part count, so a missing last part (after part %d) "
                                 "cannot be detected." % max_n)
            ordered = numbered + [p for p in parts if not p["info"]]
            base = numbered[0]["info"]["base"]
        else:
            ordered = parts
            base = os.path.splitext(os.path.basename(files[0]))[0]
        index, order, total = {}, [], 0.0
        for p in ordered:
            for zi in p["zip"].infolist():
                if zi.filename not in index:
                    index[zi.filename] = (p["zip"], zi)
                    order.append(zi.filename)
                    total += zi.file_size
        self.prog.total = max(1.0, total)
        out_path = join_output_path(self.output_dir, parts_dir, base + ".zip")
        tmp_out = os.path.join(os.path.dirname(out_path), "~zs_rebuild_%s.tmp" % uuid.uuid4().hex)
        joined = count = 0
        try:
            with zipfile.ZipFile(tmp_out, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as out:
                for nm in order:
                    if nm.endswith(".REJOIN.txt"):
                        fb = nm[:-11]
                        if any((fb + "." + "1".zfill(w)) in index for w in (3, 4, 5, 6)):
                            continue
                    m = PIECE_RX.match(nm)
                    if m and (m.group("f") + ".REJOIN.txt") in index:
                        if int(m.group("n")) != 1:
                            continue
                        fname, w = m.group("f"), len(m.group("n"))
                        self.prog.report("Re-joining " + fname)
                        zi = make_info(fname, index[nm][1].date_time)
                        with out.open(zi, "w", force_zip64=True) as dst:
                            k = 1
                            while (fname + "." + str(k).zfill(w)) in index:
                                zf, szi = index[fname + "." + str(k).zfill(w)]
                                with zf.open(szi) as s:
                                    copy_stream(s, dst, self.prog)
                                k += 1
                        joined += 1
                        count += 1
                        continue
                    zf, szi = index[nm]
                    if is_dir_name(nm):
                        out.writestr(make_info(nm, szi.date_time), b"")
                    else:
                        zi = make_info(nm, szi.date_time)
                        with zf.open(szi) as s, out.open(zi, "w", force_zip64=szi.file_size >= ZIP64_FORCE) as dst:
                            copy_stream(s, dst, self.prog)
                    count += 1
            out_path = self._finish(tmp_out, out_path)
        finally:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        self.prog.done = self.prog.total
        self.prog.report("Done.")
        return {"output": out_path, "mode": "legacy", "parts": len(ordered), "verified": 0, "inner_zips": 0,
                "entries": count, "joined": joined, "warnings": self.warnings, "size": os.path.getsize(out_path)}


def format_join_summary(r):
    kind = "file" if r["mode"] == "bytes" else "zip"
    lines = ["Rebuilt %s:" % kind, "  %s  (%.2f MB)" % (r["output"], r["size"] / 1048576.0),
             "From %d part(s), %d entries." % (r["parts"], r["entries"])]
    if r["mode"] == "bytes":
        lines.append("SHA-256 of the rebuilt file matches the manifest.")
    elif r["mode"] == "manifest":
        lines.append("All %d files verified (size + SHA-256 match the original)." % r["verified"])
        if r["inner_zips"]:
            lines.append("Re-created %d inner zip(s)." % r["inner_zips"])
    elif r["joined"]:
        lines.append("Re-joined %d file(s) from .001/.002 pieces." % r["joined"])
    for w in r["warnings"]:
        lines += ["", "NOTE: " + w]
    return "\n".join(lines) + "\n"


# ============================================================================
# Command line
# ============================================================================

def cli_progress():
    tty = sys.stderr.isatty()
    state = {"last": ""}

    def cb(pct, msg):
        line = "%3d%%  %s" % (pct, msg)
        if tty:
            sys.stderr.write("\r" + line[:110].ljust(110))
            sys.stderr.flush()
        elif msg != state["last"]:
            state["last"] = msg
    return cb


def cli_done():
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 110 + "\r")
        sys.stderr.flush()


def cli_password(confirm):
    env = os.environ.get("AGENTPARCEL_PASSWORD")
    if env:
        return env
    import getpass
    first = getpass.getpass("AgentParcel password: ")
    if confirm:
        second = getpass.getpass("AgentParcel password again: ")
        if first != second:
            raise ZsError("The passwords did not match.")
    if first == "":
        raise ZsError("A password is required. It is not stored in the part set.")
    return first


def run_split_cli(paths, args):
    limit, preset_key = limit_from_preset(
        getattr(args, "preset", None) or "custom", int(math.floor(float(args.limit_mb) * 1024 * 1024)))
    compress = bool(getattr(args, "compress", False))
    password = cli_password(True) if getattr(args, "encrypt", False) else None
    for p in paths:
        raw = bool(getattr(args, "split_bytes", False)) or compress or bool(password) or not p.lower().endswith(".zip")
        if raw and (compress or password) and p.lower().endswith(".zip") and not getattr(args, "split_bytes", False):
            sys.stderr.write("Compression and encryption apply to byte parts, so this zip is byte-split.\n")
        if raw:
            r = split_any_file(p, args.output_dir, limit, cli_progress(), include_apps=not args.no_include_apps,
                               compress=compress, password=password, preset=preset_key)
        else:
            r = Splitter(p, args.output_dir, limit, not args.no_unpack_inner, cli_progress(),
                         include_apps=not args.no_include_apps).run()
        cli_done()
        print(format_split_summary(r))


def run_join_cli(paths, args):
    password = None
    manifest = locate_byte_manifest(paths)
    if manifest and _load_manifest(manifest).get("encryption"):
        password = cli_password(False)
    r = rebuild(paths, args.output_dir, cli_progress(), password=password)
    cli_done()
    print(format_join_summary(r))


def run_verify_cli(paths):
    report = verify_parts(paths, cli_progress())
    cli_done()
    print(report["message"])
    return 0 if report["ok"] else 1


def run_auto_cli(paths, args):
    if looks_like_parts(paths):
        run_join_cli(paths, args)
    else:
        run_split_cli(paths, args)


def interactive_text_mode(args, reason):
    print("AgentParcel (text mode) - %s" % reason)
    print("Drag a .zip (to split it) or the part zips / their folder (to rebuild) into this window,")
    print("then press Enter. (Leave empty and press Enter to quit.)")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            return 0
        if not line:
            return 0
        try:
            paths = shlex.split(line)
        except ValueError:
            paths = [line]
        paths = [os.path.expanduser(p) for p in paths]
        try:
            run_auto_cli(paths, args)
        except ZsError as ex:
            cli_done()
            print("ERROR: %s" % ex)
        except Exception as ex:
            cli_done()
            print("ERROR: %s: %s" % (type(ex).__name__, ex))
        print("Drop another item and press Enter, or just press Enter to quit.")


# ============================================================================
# Byte-split any file, verify, and the standalone rebuild kit
# ============================================================================

def sha256_file(path, prog=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(COPY_BUF)
            if not block:
                break
            h.update(block)
            if prog is not None:
                prog.add(len(block))
    return h.hexdigest()


def rebuild_script_text():
    files = None
    try:
        files = get_payload_files()
    except Exception:
        files = None
    if files and files.get("rebuild.py"):
        text = files["rebuild.py"]
        return text.replace("\r\n", "\n") if isinstance(text, str) else text.decode("utf-8").replace("\r\n", "\n")
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "rebuild.py"), os.path.join(here, "..", "rebuild.py")):
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().replace("\r\n", "\n")
    raise ZsError("rebuild.py was not found next to AgentParcel.")


def _ps_rebuild_snippet(original):
    # A short PowerShell equivalent of rebuild.py for a byte-split set. It checks each part.
    return (
        "$m = Get-Content -Raw -LiteralPath '.\\_agentparcel_bytes.json' | ConvertFrom-Json\n"
        "$dest = Join-Path (Get-Location) $m.originalName\n"
        "$out = [System.IO.File]::Open($dest, 'CreateNew')\n"
        "try {\n"
        "  foreach ($p in ($m.parts | Sort-Object part)) {\n"
        "    $in = [System.IO.File]::OpenRead((Join-Path (Get-Location) $p.name))\n"
        "    $h = [System.Security.Cryptography.SHA256]::Create()\n"
        "    $buf = New-Object byte[] 1048576\n"
        "    while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {\n"
        "      [void]$h.TransformBlock($buf, 0, $n, $null, 0)\n"
        "      $out.Write($buf, 0, $n)\n"
        "    }\n"
        "    [void]$h.TransformFinalBlock(@(), 0, 0)\n"
        "    $hex = ([System.BitConverter]::ToString($h.Hash)).Replace('-', '').ToLowerInvariant()\n"
        "    $in.Close()\n"
        "    if ($hex -ne $p.sha256) { throw ('Corrupt part ' + $p.part + ' (' + $p.name + ')') }\n"
        "  }\n"
        "} finally { $out.Close() }\n"
    )


def how_to_text(mode, original, part_count, directory, compression=None, encryption=None):
    lines = [
        "HOW TO REBUILD",
        "==============",
        "This folder was made by AgentParcel %s." % VERSION,
        "Original file: %s" % original,
        "Parts: %d" % part_count,
        "",
    ]
    if mode == "bytes":
        if encryption:
            lines += [
                "These numbered parts are encrypted with AES-256-GCM.",
                "The password is not stored in this folder.",
                "python3 rebuild.py cannot decrypt them and will not write a file.",
                "",
                "Rebuild with AgentParcel (the app, or: python3 agentparcel.py --join \"%s\")." % directory,
                "Install the cryptography package first: pip install agentparcel[crypto]",
                "Give the same password when asked. AgentParcel checks the SHA-256 of the original file.",
            ]
            if compression:
                lines += ["", "Each part is also compressed with zlib before encryption."]
        elif compression:
            lines += [
                "These numbered parts are pieces of that one file, compressed with zlib (one part at a time).",
                "Put every part in this folder, then rebuild it (SHA-256 checked) with either:",
                "",
                "  python3 rebuild.py",
                "",
                "or, from another directory:",
                "",
                "  python3 rebuild.py \"%s\"" % directory,
                "",
                "Python 3.9 or newer is enough. rebuild.py uses the standard library to decompress.",
                "No extra packages. The script will not overwrite a file that is already there.",
                "",
                "AgentParcel can also rebuild this folder: open the app, Rebuild from parts,",
                "and choose this folder. Or call the MCP tool rebuild.",
            ]
        else:
            lines += [
                "These numbered parts are raw pieces of that one file, in order.",
                "Put every part in this folder, then rebuild it (SHA-256 checked) with either:",
                "",
                "  python3 rebuild.py",
                "",
                "or, from another directory:",
                "",
                "  python3 rebuild.py \"%s\"" % directory,
                "",
                "Python 3.9 or newer is enough. No packages to install.",
                "The script writes the original file next to the parts and will not overwrite",
                "a file that is already there.",
                "",
                "PowerShell equivalent (checks each part, then writes the original):",
                "",
                _ps_rebuild_snippet(original),
                "AgentParcel can also rebuild this folder: open the app, Rebuild from parts,",
                "and choose this folder. Or call the MCP tool rebuild.",
            ]
    else:
        lines += [
            "These are zip parts. Each one is a normal zip, and the set manifest is inside",
            "the parts (_zipsplitter_part.json / _zipsplitter_manifest.json).",
            "python3 rebuild.py checks that every part file's SHA-256 matches",
            "_agentparcel_zipset.json. It does not reassemble the original zip.",
            "",
            "To get the original zip back, use AgentParcel:",
            "  Windows: AgentParcel.bat  ->  Rebuild from parts",
            "  macOS:   AgentParcel.command",
            "  Linux:   ./agentparcel.sh",
            "  or:      python3 agentparcel.py --join \"%s\"" % directory,
            "",
            "Every file inside is checked (size + SHA-256). If a part is missing, AgentParcel",
            "names that part and does not write a partial zip.",
            "Send AgentParcel-apps.zip along if it is here. It is not a part.",
        ]
    lines += [
        "",
        "Do not rename the part files. Do not skip a number.",
        "",
    ]
    return "\n".join(lines)


def write_text_owned(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def write_kit_files(directory, mode, original, part_count, compression=None, encryption=None):
    howto = write_text_owned(directory, HOWTO_NAME, how_to_text(
        mode, original, part_count, directory, compression, encryption))
    script = write_text_owned(directory, REBUILD_SCRIPT_NAME, rebuild_script_text())
    try:
        os.chmod(script, 0o755)
    except OSError:
        pass
    return [howto, script]


def write_zip_kit(out_dir, original, results, limit, set_id, prog):
    parts = []
    for i, (path, size) in enumerate(results):
        prog.report("Checksum part %d" % (i + 1))
        parts.append({
            "part": i + 1,
            "name": os.path.basename(path),
            "size": int(size if size is not None else os.path.getsize(path)),
            "sha256": sha256_file(path, prog),
        })
    manifest = {
        "format": "agentparcel-zipset",
        "version": 1,
        "originalName": original,
        "partCount": len(parts),
        "limitBytes": int(limit),
        "setId": set_id,
        "tool": TOOL,
        "parts": parts,
    }
    path = write_text_owned(out_dir, ZIPSET_MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=True))
    return [path] + write_kit_files(out_dir, "zip", original, len(parts))


def _part_names(original, count):
    digits = max(2, len(str(count)))
    return ["%s_part%s" % (original, str(i).zfill(digits)) for i in range(1, count + 1)]


def _take_encoded_chunk(src, pos, size, limit, compress, encrypt):
    """Return the next raw slice whose encoded form fits in `limit` bytes."""
    remaining = size - pos
    if remaining <= 0:
        if _encoded_len(b"", compress, encrypt) > limit:
            raise ZsError("The part size limit is too small for one encoded part.")
        return b""

    def encoded_ok(n):
        src.seek(pos)
        raw = src.read(n)
        if len(raw) != n:
            return None
        if _encoded_len(raw, compress, encrypt) <= limit:
            return raw
        return None

    if encoded_ok(1) is None:
        raise ZsError("One byte does not fit in the part size limit after compression or encryption.")
    guess = min(remaining, max(1, limit - (16 if encrypt else 0)))
    chosen = None
    while True:
        src.seek(pos)
        raw = src.read(guess)
        guess = len(raw)
        if _encoded_len(raw, compress, encrypt) <= limit:
            chosen = raw
            break
        if guess <= 1:
            raise ZsError("One byte does not fit in the part size limit after compression or encryption.")
        nxt = int(guess * limit / _encoded_len(raw, compress, encrypt)) - 16
        if nxt >= guess:
            nxt = guess - 1
        guess = max(1, nxt)
    if len(chosen) < remaining:
        enc = _encoded_len(chosen, compress, encrypt)
        if enc < limit:
            bigger = min(remaining, max(len(chosen) + 1, int(len(chosen) * limit / max(1, enc))))
            if bigger > len(chosen):
                src.seek(pos)
                trial = src.read(bigger)
                if _encoded_len(trial, compress, encrypt) <= limit:
                    chosen = trial
                else:
                    lo, hi = len(chosen), len(trial)
                    while lo + 1 < hi:
                        mid = (lo + hi) // 2
                        got = encoded_ok(mid)
                        if got is not None:
                            lo = mid
                            chosen = got
                        else:
                            hi = mid
    return chosen


def split_any_file(source, output_dir=None, limit=DEFAULT_LIMIT, progress=None, include_apps=True,
                   should_cancel=None, compress=False, password=None, preset=None):
    """Split any file into numbered parts of at most `limit` encoded bytes. The original bytes come back exactly."""
    prog = Progress(progress, should_cancel)
    source = os.path.abspath(source)
    if not os.path.isfile(source):
        raise ZsError("File not found: " + source)
    limit = int(limit)
    preset_key = "custom"
    if preset:
        limit, preset_key = limit_from_preset(preset, limit)
    if limit < 1:
        raise ZsError("Limit is too small.")
    compress = bool(compress)
    if password is not None and password != "":
        _password_bytes(password)
    else:
        password = None
    original = os.path.basename(source)
    size = os.path.getsize(source)
    base_dir = os.path.dirname(source)
    if not output_dir:
        output_dir = os.path.join(base_dir, original + "_split")
        n = 2
        while os.path.isdir(output_dir) and os.listdir(output_dir):
            output_dir = os.path.join(base_dir, "%s_split (%d)" % (original, n))
            n += 1
    existed = os.path.isdir(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)
    owned = []
    whole = hashlib.sha256()
    prog.total = max(1.0, float(size))
    set_id = uuid.uuid4().hex
    parts_meta = []
    comp_meta = {"algorithm": "zlib", "level": ZLIB_LEVEL, "scope": "part"} if compress else None
    enc_meta = None
    aesgcm = None
    try:
        if password:
            AESGCM, _scrypt = _load_crypto()
            enc_meta = {
                "algorithm": "AES-256-GCM",
                "kdf": "scrypt",
                "salt": os.urandom(16).hex(),
                "n": SCRYPT_N,
                "r": SCRYPT_R,
                "p": SCRYPT_P,
                "length": SCRYPT_LEN,
            }
            aesgcm = AESGCM(derive_key(password, enc_meta))
        if not compress and not password:
            part_count = max(1, int(math.ceil(size / float(limit)))) if size else 1
            names = _part_names(original, part_count)
            with open(source, "rb") as src:
                for index, name in enumerate(names, start=1):
                    prog.report("Writing part %d of %d" % (index, part_count))
                    dest = os.path.join(output_dir, name)
                    if os.path.exists(dest):
                        raise ZsError("The output folder already contains " + name)
                    part_hash = hashlib.sha256()
                    remaining = limit
                    written = 0
                    with open(dest, "wb") as out:
                        owned.append(dest)
                        while remaining > 0:
                            block = src.read(min(COPY_BUF, remaining))
                            if not block:
                                break
                            out.write(block)
                            part_hash.update(block)
                            whole.update(block)
                            written += len(block)
                            remaining -= len(block)
                            prog.add(len(block))
                    parts_meta.append({
                        "part": index,
                        "name": name,
                        "size": written,
                        "sha256": part_hash.hexdigest(),
                        "offset": sum(p["size"] for p in parts_meta),
                    })
                    if size and written == 0:
                        break
        else:
            pending = []
            pos = 0
            index = 1
            with open(source, "rb") as src:
                while pos < size or (size == 0 and not pending):
                    prog.report("Writing part %d" % index)
                    raw = _take_encoded_chunk(src, pos, size, limit, compress, bool(password))
                    nonce = os.urandom(12) if password else None
                    aad = _aad(set_id, index, original) if password else None
                    blob = _encode_blob(raw, compress, aesgcm, nonce, aad)
                    if len(blob) > limit:
                        raise ZsError("Internal error: encoded part %d is larger than the limit." % index)
                    tmp = os.path.join(output_dir, ".agentparcel-part-%d" % index)
                    with open(tmp, "wb") as out:
                        out.write(blob)
                    owned.append(tmp)
                    rec = {"tmp": tmp, "rawSize": len(raw), "size": len(blob),
                           "sha256": hashlib.sha256(blob).hexdigest(), "offset": pos}
                    if nonce is not None:
                        rec["nonce"] = nonce.hex()
                    pending.append(rec)
                    whole.update(raw)
                    prog.add(len(raw))
                    pos += len(raw)
                    index += 1
                    if size == 0:
                        break
            names = _part_names(original, len(pending))
            for rec, name in zip(pending, names):
                dest = os.path.join(output_dir, name)
                if os.path.exists(dest):
                    raise ZsError("The output folder already contains " + name)
                tmp = rec.pop("tmp")
                os.rename(tmp, dest)
                owned.remove(tmp)
                owned.append(dest)
                meta = {"part": len(parts_meta) + 1, "name": name, "size": rec["size"], "sha256": rec["sha256"],
                        "offset": rec["offset"], "rawSize": rec["rawSize"]}
                if "nonce" in rec:
                    meta["nonce"] = rec["nonce"]
                parts_meta.append(meta)
        manifest = {
            "format": "agentparcel-bytes",
            "version": 1,
            "originalName": original,
            "originalSize": size,
            "sha256": whole.hexdigest(),
            "limitBytes": limit,
            "partCount": len(parts_meta),
            "setId": set_id,
            "tool": TOOL,
            "parts": parts_meta,
        }
        if preset_key != "custom":
            manifest["preset"] = preset_key
        if comp_meta:
            manifest["compression"] = comp_meta
        if enc_meta:
            manifest["encryption"] = enc_meta
        manifest_path = write_text_owned(output_dir, BYTES_MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=True))
        owned.append(manifest_path)
        owned.extend(write_kit_files(output_dir, "bytes", original, len(parts_meta), comp_meta, enc_meta))
        apps = None
        if include_apps:
            prog.report("Adding " + APPS_NAME + "...")
            try:
                apps = write_apps_bundle(output_dir, max(limit, 1 << 62))
            except Exception as ex:
                apps = (None, 0, "Apps bundle could not be created: %s" % ex)
            if apps and apps[0]:
                owned.append(apps[0])
        prog.done = prog.total
        prog.report("Done.")
        results = [(os.path.join(output_dir, p["name"]), p["size"]) for p in parts_meta]
        return {
            "output_dir": output_dir, "parts": results, "split_files": [], "unpacked": [], "failed": [],
            "set_id": set_id, "limit": limit, "apps": apps, "mode": "bytes",
            "sha256": manifest["sha256"], "manifest": manifest_path,
            "preset": preset_key, "compressed": bool(comp_meta), "encrypted": bool(enc_meta),
        }
    except BaseException:
        for path in owned:
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        if not existed:
            try:
                if os.path.isdir(output_dir) and not os.listdir(output_dir):
                    os.rmdir(output_dir)
            except OSError:
                pass
        raise


def _locate_named(inputs, filename):
    for raw in inputs:
        if not raw:
            continue
        path = os.path.abspath(raw.strip().strip('"'))
        if os.path.isdir(path):
            cand = os.path.join(path, filename)
            if os.path.isfile(cand):
                return cand
        elif os.path.isfile(path):
            if os.path.basename(path) == filename:
                return path
            cand = os.path.join(os.path.dirname(path), filename)
            if os.path.isfile(cand):
                return cand
    return None


def locate_byte_manifest(inputs):
    return _locate_named(inputs, BYTES_MANIFEST)


def _load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def _still_needed_text(missing, missing_names, corrupt):
    bits = []
    for i, number in enumerate(missing):
        name = missing_names[i] if i < len(missing_names) else ""
        bits.append(("part %s %s" % (number, name)).strip())
    for item in corrupt:
        bits.append(("part %s %s" % (item.get("part"), item.get("name") or "")).strip())
    if not bits:
        return ""
    return "Still needed: " + ", ".join(bits)


def _verify_report(fmt, original, part_count, missing, missing_names, corrupt, present):
    ok = not missing and not corrupt
    lines = []
    if ok:
        lines.append("OK: all %d part(s) of %s are present and match the manifest." % (part_count, original))
    if missing:
        lines.append("Missing part(s): %s" % ", ".join(str(n) for n in missing))
        if missing_names:
            lines.append("(" + ", ".join(missing_names) + ")")
    if corrupt:
        for item in corrupt:
            lines.append("Corrupt part %s (%s): %s" % (item.get("part"), item.get("name"), item.get("reason")))
    still = "" if ok else _still_needed_text(missing, missing_names, corrupt)
    if still:
        lines.append(still)
    return {
        "ok": ok,
        "format": fmt,
        "original_name": original,
        "part_count": part_count,
        "missing": list(missing),
        "missing_names": list(missing_names),
        "corrupt": list(corrupt),
        "present": list(present),
        "still_needed": still,
        "message": "\n".join(lines),
    }


def verify_bytes_at(manifest_path, progress=None, should_cancel=None):
    prog = Progress(progress, should_cancel)
    folder = os.path.dirname(manifest_path)
    manifest = _load_manifest(manifest_path)
    parts = sorted(manifest.get("parts") or [], key=lambda p: int(p["part"]))
    part_count = int(manifest.get("partCount") or len(parts))
    original = str(manifest.get("originalName") or "")
    by_num = {int(p["part"]): p for p in parts}
    missing, missing_names, corrupt, present = [], [], [], []
    width = max(2, len(str(part_count or 1)))
    prog.total = max(1.0, float(manifest.get("originalSize") or 1))
    for number in range(1, part_count + 1):
        prog.report("Checking part %d" % number)
        meta = by_num.get(number)
        name = meta["name"] if meta else "%s_part%s" % (original, str(number).zfill(width))
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            missing.append(number)
            missing_names.append(name)
            continue
        present.append(number)
        size = os.path.getsize(path)
        digest = sha256_file(path, prog)
        if meta is None or size != int(meta["size"]) or digest != str(meta["sha256"]).lower():
            corrupt.append({"part": number, "name": name, "reason": "SHA-256 or size does not match the manifest"})
    return _verify_report("agentparcel-bytes", original, part_count, missing, missing_names, corrupt, present)


def _stored_sources(index, stored):
    if stored in index:
        return [index[stored]]
    for width in (3, 4, 5, 6):
        first = stored + "." + "1".zfill(width)
        if first in index:
            found, k = [], 1
            while (stored + "." + str(k).zfill(width)) in index:
                found.append(index[stored + "." + str(k).zfill(width)])
                k += 1
            return found
    return []


def verify_zipset_files(manifest_path, progress=None, should_cancel=None):
    """Checksum the zip part files listed in _agentparcel_zipset.json. Does not open the zips."""
    prog = Progress(progress, should_cancel)
    folder = os.path.dirname(manifest_path)
    manifest = _load_manifest(manifest_path)
    parts = sorted(manifest.get("parts") or [], key=lambda p: int(p["part"]))
    part_count = int(manifest.get("partCount") or len(parts))
    original = str(manifest.get("originalName") or "")
    missing, missing_names, corrupt, present = [], [], [], []
    prog.total = max(1.0, float(sum(int(p.get("size") or 0) for p in parts)))
    for part in parts:
        number = int(part["part"])
        name = str(part["name"])
        prog.report("Checking part %d" % number)
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            missing.append(number)
            missing_names.append(name)
            continue
        present.append(number)
        digest = sha256_file(path, prog)
        if os.path.getsize(path) != int(part["size"]) or digest != str(part["sha256"]).lower():
            corrupt.append({"part": number, "name": name, "reason": "SHA-256 or size does not match the manifest"})
    return _verify_report("agentparcel-zipset", original, part_count, missing, missing_names, corrupt, present)


def verify_zip_set(inputs, progress=None, should_cancel=None):
    prog = Progress(progress, should_cancel)
    files = find_part_set(inputs)
    if not files:
        side = _locate_named(inputs, ZIPSET_MANIFEST)
        if side:
            return verify_zipset_files(side, progress, should_cancel)
        raise ZsError("No parts found.")
    opened = []
    try:
        parts = []
        unreadable = []
        for path in files:
            prog.report("Opening " + os.path.basename(path))
            try:
                zf = zipfile.ZipFile(path, "r")
            except Exception:
                info = part_info(os.path.basename(path))
                number = info["number"] if info else None
                unreadable.append({
                    "part": number,
                    "name": os.path.basename(path),
                    "reason": "not a readable zip",
                })
                continue
            if APPS_MARKER in zf.namelist():
                zf.close()
                continue
            opened.append(zf)
            stub = None
            if STUB_NAME in zf.namelist():
                try:
                    stub = read_json_entry(zf, STUB_NAME)
                except Exception:
                    stub = None
            parts.append({"path": path, "zip": zf, "stub": stub, "info": part_info(os.path.basename(path))})
        if not parts:
            if unreadable:
                return _verify_report("zipsplitter-manifest", "", 0, [], [], unreadable, [])
            raise ZsError("No parts found (only the AgentParcel-apps.zip bundle).")
        labelled = [p for p in parts if p["stub"]]
        if not labelled:
            present = []
            for p in parts:
                if p["info"]:
                    present.append(p["info"]["number"])
            report = _verify_report("legacy", "", max(present or [0]), [], [], list(unreadable), sorted(present))
            if report["ok"]:
                report["message"] = ("Present part(s): %s. These parts have no manifest, so checksums cannot be checked."
                                     % ", ".join(str(n) for n in report["present"]))
            return report
        first = labelled[0]["stub"]
        set_id = str(first.get("setId"))
        part_count = int(first.get("partCount") or 0)
        original = str(first.get("originalName") or "")
        use = {}
        for p in parts:
            if not p["stub"] or str(p["stub"].get("setId")) != set_id:
                continue
            number = int(p["stub"].get("part") or 0)
            if number and number not in use:
                use[number] = p
        stem = os.path.splitext(original)[0]
        width = max(2, len(str(part_count or 1)))
        missing = [k for k in range(1, part_count + 1) if k not in use]
        missing_names = ["%s_part%s.zip" % (stem, str(k).zfill(width)) for k in missing]
        present = sorted(use)
        manifest = None
        for number in present:
            zf = use[number]["zip"]
            if MANIFEST_NAME in zf.namelist():
                try:
                    manifest = read_json_entry(zf, MANIFEST_NAME)
                except Exception:
                    corrupt_early = {
                        "part": number,
                        "name": os.path.basename(use[number]["path"]),
                        "reason": "not a readable zip",
                    }
                    manifest = None
                    # keep looking; a later part may still hold a readable copy
                    use[number]["_unreadable"] = corrupt_early
                else:
                    break
        corrupt = []
        for number, p in use.items():
            if p.get("_unreadable") and manifest is None:
                corrupt.append(p["_unreadable"])
        if manifest is None and not corrupt:
            corrupt.append({"part": None, "name": MANIFEST_NAME, "reason": "manifest was not found in any present part"})
        elif manifest is not None:
            index = {}
            part_of = {}
            for number, p in use.items():
                for zi in p["zip"].infolist():
                    if zi.filename not in index:
                        index[zi.filename] = (p["zip"], zi)
                        part_of[zi.filename] = number
            prog.total = max(1.0, float(sum(int(r.get("size") or 0) for r in manifest.get("entries", []) if r.get("type") == "file")))
            for rec in manifest.get("entries", []):
                if rec.get("type") != "file":
                    continue
                stored = rec.get("stored")
                prog.report("Checking " + str(stored))
                sources = _stored_sources(index, stored)
                if not sources:
                    if not missing:
                        corrupt.append({"part": None, "name": stored, "reason": "file data is missing from the parts"})
                    continue
                h = hashlib.sha256()
                total = 0
                holders = []
                broken = False
                for zf, zi in sources:
                    holders.append(part_of.get(zi.filename))
                    try:
                        src = zf.open(zi)
                    except Exception:
                        broken = True
                        break
                    with src:
                        while True:
                            block = src.read(COPY_BUF)
                            if not block:
                                break
                            h.update(block)
                            total += len(block)
                            prog.add(len(block))
                if broken:
                    number = holders[0] if holders else None
                    corrupt.append({
                        "part": number,
                        "name": os.path.basename(use[number]["path"]) if number in use else stored,
                        "reason": "not a readable zip",
                    })
                    continue
                expect_size = int(rec.get("size") or 0)
                expect_hash = str(rec.get("sha256") or "").lower()
                if total != expect_size or h.hexdigest() != expect_hash:
                    number = holders[0] if holders else None
                    corrupt.append({
                        "part": number,
                        "name": os.path.basename(use[number]["path"]) if number in use else stored,
                        "reason": "SHA-256 or size does not match the manifest for " + str(stored),
                    })
        corrupt.extend(unreadable)
        sidecar = os.path.join(os.path.dirname(parts[0]["path"]), ZIPSET_MANIFEST)
        if os.path.isfile(sidecar):
            side = _load_manifest(sidecar)
            by_name = {os.path.basename(p["path"]): p for p in parts}
            for rec in side.get("parts") or []:
                prog.report("Checksum " + str(rec.get("name")))
                name = str(rec.get("name"))
                path = os.path.join(os.path.dirname(parts[0]["path"]), name)
                if not os.path.isfile(path):
                    continue
                digest = sha256_file(path, prog)
                if os.path.getsize(path) != int(rec.get("size") or -1) or digest != str(rec.get("sha256") or "").lower():
                    holder = by_name.get(name)
                    number = int(holder["stub"]["part"]) if holder and holder.get("stub") else rec.get("part")
                    corrupt.append({"part": number, "name": name, "reason": "part file SHA-256 or size does not match _agentparcel_zipset.json"})
        return _verify_report("zipsplitter-manifest", original, part_count, missing, missing_names, corrupt, present)
    finally:
        for zf in opened:
            try:
                zf.close()
            except Exception:
                pass


def verify_parts(inputs, progress=None, should_cancel=None):
    """Check parts without writing anything. Missing and corrupt parts are listed; this does not raise for them."""
    manifest = locate_byte_manifest(inputs)
    if manifest:
        return verify_bytes_at(manifest, progress, should_cancel)
    return verify_zip_set(inputs, progress, should_cancel)


def _part_plain_length(part):
    if "rawSize" in part and part["rawSize"] is not None:
        return int(part["rawSize"])
    return int(part["size"])


def rebuild_bytes(manifest_path, output_dir=None, progress=None, should_cancel=None, password=None):
    prog = Progress(progress, should_cancel)
    folder = os.path.dirname(manifest_path)
    manifest = _load_manifest(manifest_path)
    parts = sorted(manifest.get("parts") or [], key=lambda p: int(p["part"]))
    bad = verify_bytes_at(manifest_path, progress, should_cancel)
    if not bad["ok"]:
        raise ZsError(bad["message"], {
            "missing_parts": bad["missing"],
            "missing_names": bad["missing_names"],
            "corrupt_parts": bad["corrupt"],
            "part_count": bad["part_count"],
            "original_name": bad["original_name"],
            "still_needed": bad.get("still_needed") or "",
        })
    if manifest.get("encryption") and not password:
        raise ZsError(
            "This part set is encrypted (AES-256-GCM). A password is required. "
            "The password is not stored in the folder. "
            "Install the cryptography package if it is missing: pip install agentparcel[crypto]")
    original = str(manifest["originalName"])
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        dest = unique_path(os.path.join(os.path.abspath(output_dir), original))
    else:
        dest = unique_path(os.path.join(folder, original))
    tmp = dest + ".partial"
    prog.total = max(1.0, float(manifest.get("originalSize") or 1))
    prog.done = 0
    whole = hashlib.sha256()
    encoded = bool(manifest.get("encryption") or manifest.get("compression"))
    cache = {}
    try:
        with open(tmp, "wb") as out:
            for part in parts:
                prog.report("Rebuilding part %s" % part["part"])
                path = os.path.join(folder, part["name"])
                if not encoded:
                    with open(path, "rb") as src:
                        while True:
                            block = src.read(COPY_BUF)
                            if not block:
                                break
                            out.write(block)
                            whole.update(block)
                            prog.add(len(block))
                else:
                    with open(path, "rb") as src:
                        blob = src.read()
                    raw = decode_part_payload(blob, manifest, part, password, cache)
                    out.write(raw)
                    whole.update(raw)
                    prog.add(len(raw))
        digest = whole.hexdigest()
        if digest != str(manifest["sha256"]).lower() or os.path.getsize(tmp) != int(manifest["originalSize"]):
            raise ZsError("Rebuilt file does not match the manifest SHA-256.")
        os.rename(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    prog.report("Done.")
    return {
        "output": dest, "mode": "bytes", "parts": len(parts), "verified": 1, "inner_zips": 0,
        "entries": 1, "joined": 0, "warnings": [], "size": os.path.getsize(dest),
    }


def rebuild(inputs, output_dir=None, progress=None, should_cancel=None, password=None):
    """Rebuild either a byte-split file or a zip part set."""
    manifest = locate_byte_manifest(inputs)
    if manifest:
        return rebuild_bytes(manifest, output_dir, progress, should_cancel, password=password)
    return Joiner(inputs, output_dir, progress, should_cancel).run()


def _write_manifest(path, manifest):
    write_text_owned(os.path.dirname(path), os.path.basename(path), json.dumps(manifest, indent=2, ensure_ascii=True))


def _targets_from_report(report, part_numbers):
    if part_numbers is None:
        targets = list(report["missing"])
        for item in report["corrupt"]:
            number = item.get("part")
            if number and int(number) not in targets:
                targets.append(int(number))
        return targets
    return [int(n) for n in part_numbers]


def _regenerate_bytes(original, manifest_path, part_numbers, password, progress, should_cancel):
    prog = Progress(progress, should_cancel)
    folder = os.path.dirname(manifest_path)
    manifest = _load_manifest(manifest_path)
    if os.path.basename(original) != str(manifest.get("originalName")):
        raise ZsError("The original file name does not match this part set (%s)." % manifest.get("originalName"))
    if sha256_file(original) != str(manifest.get("sha256") or "").lower() or os.path.getsize(original) != int(manifest.get("originalSize") or -1):
        raise ZsError("The original file does not match this part set (size or SHA-256).")
    if manifest.get("encryption") and not password:
        raise ZsError(
            "This part set is encrypted. Pass the same password to regenerate parts. "
            "The password is not stored in the folder.")
    report = verify_bytes_at(manifest_path, progress, should_cancel)
    targets = _targets_from_report(report, part_numbers)
    part_count = int(manifest.get("partCount") or len(manifest.get("parts") or []))
    for number in targets:
        if number < 1 or number > part_count:
            raise ZsError("Part %s is not in this set (1-%d)." % (number, part_count))
    by_num = {int(p["part"]): p for p in manifest.get("parts") or []}
    regenerated = []
    if not targets:
        return {
            "ok": True, "mode": "bytes", "output_dir": folder, "regenerated": [],
            "still_needed": "", "missing": [], "corrupt": [],
            "message": "Nothing to regenerate. All parts match the manifest.",
        }
    compress = bool(manifest.get("compression"))
    aesgcm = None
    if manifest.get("encryption"):
        AESGCM, _scrypt = _load_crypto()
        aesgcm = AESGCM(derive_key(password, manifest["encryption"]))
    manifest_changed = False
    prog.total = max(1.0, float(len(targets)))
    prog.done = 0
    with open(original, "rb") as src:
        for number in targets:
            prog.report("Regenerating part %d" % number)
            part = by_num.get(number)
            if part is None:
                raise ZsError("Part %d is not listed in the manifest." % number)
            raw_len = _part_plain_length(part)
            src.seek(int(part.get("offset") or 0))
            raw = src.read(raw_len)
            if len(raw) != raw_len:
                raise ZsError("The original file is shorter than part %d needs." % number)
            if compress or manifest.get("encryption"):
                nonce = os.urandom(12) if manifest.get("encryption") else None
                aad = _aad(manifest.get("setId"), number, manifest.get("originalName")) if nonce else None
                blob = _encode_blob(raw, compress, aesgcm, nonce, aad)
            else:
                blob = raw
                nonce = None
            dest = os.path.join(folder, part["name"])
            tmp = dest + ".new"
            with open(tmp, "wb") as out:
                out.write(blob)
            os.replace(tmp, dest)
            digest = hashlib.sha256(blob).hexdigest()
            if part.get("sha256") != digest or int(part.get("size") or -1) != len(blob) or (
                    nonce and part.get("nonce") != nonce.hex()):
                part["size"] = len(blob)
                part["sha256"] = digest
                if nonce:
                    part["nonce"] = nonce.hex()
                manifest_changed = True
            regenerated.append({"part": number, "name": part["name"], "path": dest})
            prog.add(1)
    if manifest_changed:
        _write_manifest(manifest_path, manifest)
    after = verify_bytes_at(manifest_path, progress, should_cancel)
    lines = ["Regenerated " + ", ".join("part %s (%s)" % (item["part"], item["name"]) for item in regenerated) + "."]
    if after["ok"]:
        lines.append("All parts are now present and match the manifest.")
    else:
        lines.append(after["message"])
    return {
        "ok": after["ok"],
        "mode": "bytes",
        "output_dir": folder,
        "regenerated": regenerated,
        "still_needed": after.get("still_needed") or "",
        "missing": after["missing"],
        "corrupt": after["corrupt"],
        "message": "\n".join(lines),
    }


def _zip_payload_sig(path):
    sig = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.filename in (STUB_NAME, MANIFEST_NAME, APPS_MARKER):
                continue
            sig.append((info.filename, info.file_size, info.CRC & 0xFFFFFFFF))
    return tuple(sig)


def _zipset_facts(inputs):
    files = []
    try:
        files = find_part_set(inputs)
    except ZsError:
        files = []
    side_path = _locate_named(inputs, ZIPSET_MANIFEST)
    side = _load_manifest(side_path) if side_path else None
    folder = None
    if side_path:
        folder = os.path.dirname(side_path)
    elif files:
        folder = os.path.dirname(files[0])
    facts = {"folder": folder, "sidecar": side_path, "side": side, "created": None, "unpack": True,
             "limit": None, "set_id": None, "original": None, "original_size": None, "part_count": None}
    if side:
        facts["limit"] = side.get("limitBytes")
        facts["set_id"] = side.get("setId")
        facts["original"] = side.get("originalName")
        facts["part_count"] = side.get("partCount")
    for path in files:
        try:
            with zipfile.ZipFile(path) as zf:
                stub = read_json_entry(zf, STUB_NAME) if STUB_NAME in zf.namelist() else None
                manifest = None
                if MANIFEST_NAME in zf.namelist():
                    try:
                        manifest = read_json_entry(zf, MANIFEST_NAME)
                    except Exception:
                        manifest = None
        except Exception:
            continue
        if stub:
            facts["set_id"] = facts["set_id"] or stub.get("setId")
            facts["original"] = facts["original"] or stub.get("originalName")
            facts["part_count"] = facts["part_count"] or stub.get("partCount")
        if manifest:
            facts["created"] = manifest.get("created")
            facts["limit"] = facts["limit"] or manifest.get("limitBytes")
            facts["original"] = facts["original"] or manifest.get("originalName")
            facts["original_size"] = manifest.get("originalSize")
            if "unpackInner" in manifest:
                facts["unpack"] = bool(manifest.get("unpackInner"))
            facts["set_id"] = facts["set_id"] or manifest.get("setId")
            break
    if facts["original_size"] is None and side is None:
        for path in files:
            try:
                with zipfile.ZipFile(path) as zf:
                    if MANIFEST_NAME in zf.namelist():
                        manifest = read_json_entry(zf, MANIFEST_NAME)
                        facts["original_size"] = manifest.get("originalSize")
                        facts["created"] = facts["created"] or manifest.get("created")
                        break
            except Exception:
                continue
    return facts


def _regenerate_zip(original, inputs, part_numbers, progress, should_cancel):
    prog = Progress(progress, should_cancel)
    facts = _zipset_facts(inputs)
    folder = facts["folder"]
    if not folder or not facts["part_count"] or not facts["original"]:
        raise ZsError("No zip part set found to regenerate.")
    part_count = int(facts["part_count"])
    original_name = str(facts["original"])
    if os.path.basename(original) != original_name:
        raise ZsError("The original file name does not match this part set (%s)." % original_name)
    if facts["original_size"] is not None and os.path.getsize(original) != int(facts["original_size"]):
        raise ZsError("The original file size does not match this part set.")
    if not facts["limit"]:
        raise ZsError("This part set does not record a size limit, so a matching part cannot be rebuilt. Split the whole zip again.")
    limit = int(facts["limit"])
    report = verify_zip_set(inputs, progress, should_cancel)
    for item in report["corrupt"]:
        if not item.get("part"):
            raise ZsError("A part is corrupt but its number is unknown. Split the whole zip again.\n" + report["message"])
    targets = _targets_from_report(report, part_numbers)
    for number in targets:
        if number < 1 or number > part_count:
            raise ZsError("Part %s is not in this set (1-%d)." % (number, part_count))
    if not targets:
        return {
            "ok": True, "mode": "zip", "output_dir": folder, "regenerated": [],
            "still_needed": "", "missing": [], "corrupt": [],
            "message": "Nothing to regenerate. All parts match.",
        }
    stem = os.path.splitext(original_name)[0]
    width = max(2, len(str(part_count)))
    names = ["%s_part%s.zip" % (stem, str(n).zfill(width)) for n in range(1, part_count + 1)]
    temp_parent = tempfile.mkdtemp(prefix="AgentParcel-regen-")
    regenerated = []
    try:
        fresh_dir = os.path.join(temp_parent, "fresh")
        os.makedirs(fresh_dir)
        fresh = Splitter(original, fresh_dir, limit, facts["unpack"], progress, include_apps=False,
                         should_cancel=should_cancel, set_id=facts["set_id"], created=facts["created"]).run()
        new_paths = [p[0] for p in fresh["parts"]]
        if len(new_paths) != part_count:
            raise ZsError(
                "A fresh split produced %d parts, but this set has %d. "
                "The layout does not match, so the missing parts were not replaced. Split the whole zip again."
                % (len(new_paths), part_count))
        target_set = set(targets)
        for number in range(1, part_count + 1):
            if number in target_set:
                continue
            old = os.path.join(folder, names[number - 1])
            if not os.path.isfile(old):
                raise ZsError(
                    "Part %d is also missing. Include it, or split the whole zip again. Nothing was replaced." % number)
            try:
                old_sig = _zip_payload_sig(old)
            except Exception:
                raise ZsError(
                    "Part %d is not readable. Include it, or split the whole zip again. Nothing was replaced." % number)
            if old_sig != _zip_payload_sig(new_paths[number - 1]):
                raise ZsError(
                    "Part %d does not match a fresh split of the original, so the missing parts cannot be replaced "
                    "safely. Split the whole zip again. Nothing was replaced." % number)
        for number in targets:
            dest = os.path.join(folder, names[number - 1])
            tmp = dest + ".new"
            shutil.copyfile(new_paths[number - 1], tmp)
            os.replace(tmp, dest)
            regenerated.append({"part": number, "name": names[number - 1], "path": dest})
        if facts["sidecar"] and os.path.isfile(facts["sidecar"]):
            side = _load_manifest(facts["sidecar"])
            by_part = {int(p["part"]): p for p in side.get("parts") or []}
            for item in regenerated:
                rec = by_part.get(item["part"])
                if rec is None:
                    continue
                rec["name"] = item["name"]
                rec["size"] = os.path.getsize(item["path"])
                rec["sha256"] = sha256_file(item["path"])
            _write_manifest(facts["sidecar"], side)
    finally:
        shutil.rmtree(temp_parent, ignore_errors=True)
    after = verify_zip_set([folder], progress, should_cancel)
    lines = ["Regenerated " + ", ".join("part %s (%s)" % (item["part"], item["name"]) for item in regenerated) + "."]
    if after["ok"]:
        lines.append("All parts are now present and match the manifest.")
    else:
        lines.append(after["message"])
    return {
        "ok": after["ok"], "mode": "zip", "output_dir": folder, "regenerated": regenerated,
        "still_needed": after.get("still_needed") or "", "missing": after["missing"],
        "corrupt": after["corrupt"], "message": "\n".join(lines),
    }


def regenerate_parts(original, inputs, part_numbers=None, password=None, progress=None, should_cancel=None):
    """Rewrite only the requested parts (default: missing and corrupt) from the original file.

    Parts that already match are left as they are. The password is never written down.
    """
    original = os.path.abspath(original)
    if not os.path.isfile(original):
        raise ZsError("File not found: " + original)
    if isinstance(inputs, str):
        inputs = [inputs]
    manifest_path = locate_byte_manifest(inputs)
    if manifest_path:
        return _regenerate_bytes(original, manifest_path, part_numbers, password, progress, should_cancel)
    return _regenerate_zip(original, inputs, part_numbers, progress, should_cancel)


# ============================================================================
# GUI (tkinter)
# ============================================================================

def gui_unavailable_reason():
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "no graphical display found"
    try:
        import tkinter  # noqa: F401
    except Exception:
        hint = "install the 'python3-tk' package" if sys.platform.startswith("linux") else \
            "install Python from python.org (includes Tk) or 'brew install python-tk'"
        return "tkinter is not installed (%s)" % hint
    return None


def open_folder(path):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # noqa
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def run_gui(args, start_items):
    import queue
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    dnd = None
    try:
        import tkinterdnd2  # optional, not part of the standard library
        root = tkinterdnd2.TkinterDnD.Tk()
        dnd = tkinterdnd2
    except Exception:
        root = tk.Tk()
    root.title("AgentParcel " + VERSION)
    try:  # window / taskbar icon from the payload (Tk 8.6+ reads PNG)
        _pf = get_payload_files() or {}
        _icons = [tk.PhotoImage(master=root, data=_pf[k]) for k in ("icon-agentparcel-64.png.b64", "icon-agentparcel-32.png.b64") if k in _pf]
        if _icons:
            root.iconphoto(True, *_icons)
            root._agentparcel_icons = _icons
    except Exception:
        pass
    style = ttk.Style(root)
    if sys.platform.startswith("linux") and "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Drop.TLabel", font=("TkDefaultFont", 12), anchor="center", justify="center",
                    relief="solid", borderwidth=1, padding=12)
    style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))
    PAD = 4
    BTN_W = 13

    events = queue.Queue()
    state = {"busy": False, "last_out": None, "cancel": threading.Event()}

    outer = ttk.Frame(root, padding=10)
    outer.pack(fill="both", expand=True)
    nb = ttk.Notebook(outer)
    nb.pack(fill="x")
    tab_split = ttk.Frame(nb, padding=10)
    tab_join = ttk.Frame(nb, padding=10)
    nb.add(tab_split, text="Split a zip")
    nb.add(tab_join, text="Rebuild from parts")

    def drop_label(parent, text):
        lab = ttk.Label(parent, text=text, style="Drop.TLabel", anchor="center", justify="center", wraplength=600)

        def rewrap(e):
            if e.width > 150:   # ignore the 1-pixel size of a tab that has not been shown yet
                lab.configure(wraplength=e.width - 30)
        lab.bind("<Configure>", rewrap)
        return lab

    # ---- split tab ----
    drop_label(tab_split, "Choose a .zip, or any file to split into numbered byte parts"
               + (" - or drag it here" if dnd else " (Browse...)")).grid(
        row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    path_var = tk.StringVar()
    ttk.Entry(tab_split, textvariable=path_var).grid(row=1, column=0, sticky="ew", padx=(0, PAD))
    btn_browse = ttk.Button(tab_split, text="Browse...", width=BTN_W)
    btn_browse.grid(row=1, column=1, sticky="e")
    preset_row = ttk.Frame(tab_split)
    preset_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 2))
    ttk.Label(preset_row, text="Size preset:").pack(side="left")
    preset_var = tk.StringVar(value=getattr(args, "preset", None) or "custom")
    preset_box = ttk.Combobox(preset_row, textvariable=preset_var, values=PRESET_ORDER, state="readonly", width=18)
    preset_box.pack(side="left", padx=(PAD, 0))
    opt = ttk.Frame(tab_split)
    opt.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 2))
    ttk.Label(opt, text="Max size per zip (MB):").pack(side="left")
    limit_var = tk.StringVar(value=("%g" % args.limit_mb))
    limit_box = ttk.Spinbox(opt, from_=1, to=100000, increment=0.5, textvariable=limit_var, width=8)
    limit_box.pack(side="left", padx=(PAD, 0))
    preset_note = ttk.Label(tab_split, text="", wraplength=640, justify="left")
    preset_note.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 2))
    unpack_var = tk.BooleanVar(value=not args.no_unpack_inner)
    chk_unpack = ttk.Checkbutton(tab_split, text="Unpack zips inside the zip (recommended)", variable=unpack_var)
    chk_unpack.grid(row=5, column=0, columnspan=2, sticky="w", pady=2)
    apps_var = tk.BooleanVar(value=not args.no_include_apps)
    chk_apps = ttk.Checkbutton(tab_split, text="Include AgentParcel apps (Windows, Mac, Linux) so the recipient can rebuild",
                               variable=apps_var)
    chk_apps.grid(row=6, column=0, columnspan=2, sticky="w", pady=2)
    raw_var = tk.BooleanVar(value=False)
    chk_raw = ttk.Checkbutton(tab_split, text="Byte-split this file (exact bytes, any file type)", variable=raw_var)
    chk_raw.grid(row=7, column=0, columnspan=2, sticky="w", pady=2)
    compress_var = tk.BooleanVar(value=False)
    chk_compress = ttk.Checkbutton(tab_split, text="Compress byte parts (zlib, optional)", variable=compress_var)
    chk_compress.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
    encrypt_var = tk.BooleanVar(value=False)
    chk_encrypt = ttk.Checkbutton(tab_split, text="Encrypt byte parts (AES-256-GCM, optional)", variable=encrypt_var)
    chk_encrypt.grid(row=9, column=0, columnspan=2, sticky="w", pady=2)
    btn_split = ttk.Button(tab_split, text="Split", width=BTN_W, style="Accent.TButton")
    btn_split.grid(row=10, column=1, sticky="e", pady=(6, 0))
    tab_split.columnconfigure(0, weight=1)

    # ---- join tab ----
    drop_label(tab_join, "Add the part zips, their folder, or just one part (the other parts are found automatically)"
               + (" - or drag them here" if dnd else "")).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    list_frame = ttk.Frame(tab_join)
    list_frame.grid(row=1, column=0, sticky="nsew", padx=(0, PAD))
    parts_list = tk.Listbox(list_frame, height=5, activestyle="none")
    sb = ttk.Scrollbar(list_frame, orient="vertical", command=parts_list.yview)
    parts_list.configure(yscrollcommand=sb.set)
    parts_list.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    side = ttk.Frame(tab_join)
    side.grid(row=1, column=1, sticky="n")
    btn_add = ttk.Button(side, text="Add parts...", width=BTN_W)
    btn_add.pack(fill="x")
    btn_addf = ttk.Button(side, text="Add folder...", width=BTN_W)
    btn_addf.pack(fill="x", pady=PAD)
    btn_clear = ttk.Button(side, text="Clear", width=BTN_W)
    btn_clear.pack(fill="x")
    save = ttk.Frame(tab_join)
    save.grid(row=2, column=0, sticky="ew", pady=(8, 0), padx=(0, PAD))
    ttk.Label(save, text="Save to (optional):").pack(side="left")
    out_var = tk.StringVar()
    ttk.Entry(save, textvariable=out_var).pack(side="left", fill="x", expand=True, padx=(PAD, 0))
    btn_out = ttk.Button(tab_join, text="Browse...", width=BTN_W)
    btn_out.grid(row=2, column=1, sticky="e", pady=(8, 0))
    join_row = ttk.Frame(tab_join)
    join_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(6, 0))
    btn_verify = ttk.Button(join_row, text="Verify", width=BTN_W)
    btn_verify.pack(side="left", padx=(0, PAD))
    btn_resend = ttk.Button(join_row, text="Resend", width=BTN_W)
    btn_resend.pack(side="left", padx=(0, PAD))
    btn_join = ttk.Button(join_row, text="Rebuild", width=BTN_W, style="Accent.TButton")
    btn_join.pack(side="left")
    tab_join.columnconfigure(0, weight=1)

    # ---- shared bottom ----
    bar = ttk.Progressbar(outer, maximum=100)
    bar.pack(fill="x", pady=(10, 4))
    row = ttk.Frame(outer)
    row.pack(fill="x")
    status_var = tk.StringVar()
    ttk.Label(row, textvariable=status_var, anchor="w").pack(side="left", fill="x", expand=True)
    btn_stop = ttk.Button(row, text="Stop", width=BTN_W, state="disabled")
    btn_stop.pack(side="right")
    btn_open = ttk.Button(row, text="Open folder", width=BTN_W, state="disabled")
    btn_open.pack(side="right", padx=(0, PAD))
    log_frame = ttk.Frame(outer)
    log_frame.pack(fill="both", expand=True, pady=(4, 0))
    log = tk.Text(log_frame, height=9, wrap="word", state="disabled", relief="solid", borderwidth=1)
    lsb = ttk.Scrollbar(log_frame, orient="vertical", command=log.yview)
    log.configure(yscrollcommand=lsb.set)
    log.pack(side="left", fill="both", expand=True)
    lsb.pack(side="right", fill="y")

    controls = [btn_browse, preset_box, limit_box, chk_unpack, chk_apps, chk_raw, chk_compress, chk_encrypt,
                btn_split, btn_add, btn_addf, btn_clear, btn_out, btn_join, btn_verify, btn_resend]

    def set_log(text):
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.insert("end", text)
        log.configure(state="disabled")

    def refresh_preset(*_a):
        key = preset_var.get() or "custom"
        info = PRESETS.get(key) or PRESETS["custom"]
        preset_note.configure(text=info["note"] + " " + info["source"])
        if state["busy"]:
            return
        limit_box.configure(state=("disabled" if key != "custom" else "normal"))

    def set_busy(on):
        state["busy"] = on
        for c in controls:
            c.configure(state=("disabled" if on else "normal"))
        if not on:
            preset_box.configure(state="readonly")
            refresh_preset()
        btn_stop.configure(state=("normal" if on else "disabled"))
        if on:
            btn_open.configure(state="disabled")

    preset_var.trace_add("write", refresh_preset)
    refresh_preset()

    def worker(kind, job):
        try:
            result = job(lambda pct, msg: events.put(("progress", pct, msg)))
            events.put(("done", kind, result))
        except Cancelled:
            events.put(("cancelled", kind))
        except ZsError as ex:
            events.put(("error", kind, str(ex)))
        except Exception as ex:
            events.put(("error", kind, "%s: %s" % (type(ex).__name__, ex)))

    def poll():
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == "progress":
                    bar["value"] = ev[1]
                    status_var.set("%d%%  %s" % (ev[1], ev[2]))
                elif ev[0] == "done":
                    set_busy(False)
                    bar["value"] = 100
                    r = ev[2]
                    if ev[1] == "split":
                        state["last_out"] = r["output_dir"]
                        set_log(format_split_summary(r))
                        status_var.set("Done - some big files were cut into pieces (Rebuild joins them)." if r["split_files"]
                                       else "Done - %d part(s) created." % len(r["parts"]))
                    elif ev[1] == "verify":
                        set_log(r["message"] + "\n")
                        status_var.set("Verified - all parts match." if r["ok"] else "Verify found missing or corrupt parts.")
                        if state.get("verify_from"):
                            src = state["verify_from"]
                            state["last_out"] = src if os.path.isdir(src) else os.path.dirname(src)
                    elif ev[1] == "regen":
                        set_log(r["message"] + "\n")
                        status_var.set("Re-sent the missing parts." if r["ok"] else "Some parts are still needed.")
                        state["last_out"] = r.get("output_dir")
                    else:
                        state["last_out"] = os.path.dirname(r["output"])
                        set_log(format_join_summary(r))
                        status_var.set("Done - rebuilt " + os.path.basename(r["output"]))
                    btn_open.configure(state="normal")
                elif ev[0] == "cancelled":
                    set_busy(False)
                    bar["value"] = 0
                    status_var.set("Cancelled")
                    set_log("Cancelled\n")
                elif ev[0] == "error":
                    set_busy(False)
                    status_var.set("Failed.")
                    log.configure(state="normal")
                    log.insert("end", "\nERROR: " + ev[2] + "\n")
                    log.configure(state="disabled")
                    messagebox.showerror("AgentParcel", {"split": "Split", "verify": "Verify", "regen": "Re-send"}.get(ev[1], "Rebuild") + " failed:\n" + ev[2])
        except queue.Empty:
            pass
        root.after(100, poll)

    def gui_password(confirm):
        from tkinter import simpledialog
        first = simpledialog.askstring("AgentParcel", "Password (it is not saved):", show="*", parent=root)
        if not first:
            if first == "":
                messagebox.showinfo("AgentParcel", "A password is required.")
            return None
        if confirm:
            second = simpledialog.askstring("AgentParcel", "Password again:", show="*", parent=root)
            if second != first:
                messagebox.showinfo("AgentParcel", "The passwords did not match.")
                return None
        return first

    def password_for_items(items):
        manifest = locate_byte_manifest(items)
        if not manifest:
            return None
        data = _load_manifest(manifest)
        if not data.get("encryption"):
            return None
        return gui_password(False) or False

    def start_split():
        if state["busy"]:
            return
        p = path_var.get().strip().strip('"')
        if not p:
            messagebox.showinfo("AgentParcel", "Choose a file first.")
            return
        if not os.path.isfile(p):
            messagebox.showinfo("AgentParcel", "File not found:\n" + p)
            return
        try:
            custom = int(math.floor(float(limit_var.get()) * 1024 * 1024))
            lim, preset_key = limit_from_preset(preset_var.get() or "custom", custom)
        except ValueError:
            messagebox.showinfo("AgentParcel", "The size limit must be a number (MB).")
            return
        except ZsError as ex:
            messagebox.showinfo("AgentParcel", str(ex))
            return
        compress = bool(compress_var.get())
        password = None
        if encrypt_var.get():
            password = gui_password(True)
            if not password:
                return
        raw = bool(raw_var.get()) or compress or bool(password) or not (p.lower().endswith(".zip") and zipfile.is_zipfile(p))
        size = os.path.getsize(p)
        if size <= lim and not messagebox.askyesno(
                "AgentParcel", "This file is already %.2f MB, which is under the limit. Split it anyway?" % (size / 1048576.0)):
            return
        lead = "Byte-splitting " if raw else "Splitting "
        if preset_key != "custom":
            lead = "Preset %s (%d bytes). %s" % (preset_key, lim, lead)
        set_log(lead + p + "\n")
        bar["value"] = 0
        unpack, apps = bool(unpack_var.get()), bool(apps_var.get())

        def maker(cb, stop, password=password, preset_key=preset_key, compress=compress, lim=lim):
            if raw:
                return split_any_file(p, None, lim, cb, include_apps=apps, should_cancel=stop,
                                      compress=compress, password=password, preset=preset_key)
            return Splitter(p, None, lim, unpack, cb, include_apps=apps, should_cancel=stop).run()

        begin("split", maker)

    def add_parts(items):
        have = set(parts_list.get(0, "end"))
        manifest = locate_byte_manifest(items)
        if manifest:
            folder = os.path.dirname(manifest)
            if folder not in have:
                parts_list.insert("end", folder)
                have.add(folder)
        try:
            found = find_part_set(items)
        except ZsError as ex:
            if not manifest:
                messagebox.showinfo("AgentParcel", str(ex))
            return
        for f in found:
            if f not in have and not is_apps_bundle_name(os.path.basename(f)):
                parts_list.insert("end", f)

    def start_join():
        if state["busy"]:
            return
        items = list(parts_list.get(0, "end"))
        if not items:
            messagebox.showinfo("AgentParcel", "Add the part zips first (one part is enough).")
            return
        od = out_var.get().strip().strip('"') or None
        password = password_for_items(items)
        if password is False:
            return
        set_log("Rebuilding from %d part(s)...\n" % len(items))
        bar["value"] = 0
        begin("join", lambda cb, stop, password=password: rebuild(items, od, cb, stop, password=password))

    def start_verify():
        if state["busy"]:
            return
        items = list(parts_list.get(0, "end"))
        if not items:
            messagebox.showinfo("AgentParcel", "Add the parts or their folder first.")
            return
        state["verify_from"] = items[0]
        set_log("Verifying %d item(s)...\n" % len(items))
        bar["value"] = 0
        begin("verify", lambda cb, stop: verify_parts(items, cb, stop))

    def start_resend():
        if state["busy"]:
            return
        items = list(parts_list.get(0, "end"))
        if not items:
            messagebox.showinfo("AgentParcel", "Add the parts or their folder first.")
            return
        original = filedialog.askopenfilename(title="Choose the original file", filetypes=[("All files", "*")])
        if not original:
            return
        password = password_for_items(items)
        if password is False:
            return
        set_log("Re-sending missing or corrupt parts...\n")
        bar["value"] = 0
        begin("regen", lambda cb, stop, password=password, original=original: regenerate_parts(
            original, items, None, password, cb, stop))

    def begin(kind, maker):
        state["cancel"].clear()
        set_busy(True)
        threading.Thread(target=worker, args=(kind, lambda cb: maker(cb, lambda: state["cancel"].is_set())),
                         daemon=True).start()

    def start_from_items(items, force_join=False):
        items = [i for i in items if i]
        if not items:
            return
        if force_join or looks_like_parts(items):
            nb.select(tab_join)
            parts_list.delete(0, "end")
            add_parts(items)
            if parts_list.size():
                start_join()
        else:
            nb.select(tab_split)
            path_var.set(items[0])
            start_split()

    def browse():
        f = filedialog.askopenfilename(title="Choose a file to split", filetypes=[("All files", "*"), ("Zip files", "*.zip")])
        if f:
            path_var.set(f)

    def add_files():
        fs = filedialog.askopenfilenames(title="Choose the part zips", filetypes=[("Zip parts", "*.zip"), ("All files", "*")])
        if fs:
            add_parts(list(fs))

    def add_folder():
        d = filedialog.askdirectory(title="Choose the folder that contains the part zips")
        if d:
            add_parts([d])

    def choose_out():
        d = filedialog.askdirectory(title="Where should the rebuilt zip be saved?")
        if d:
            out_var.set(d)

    btn_browse.configure(command=browse)
    btn_split.configure(command=start_split)
    btn_add.configure(command=add_files)
    btn_addf.configure(command=add_folder)
    btn_clear.configure(command=lambda: parts_list.delete(0, "end"))
    btn_out.configure(command=choose_out)
    btn_join.configure(command=start_join)
    btn_verify.configure(command=start_verify)
    btn_resend.configure(command=start_resend)
    btn_stop.configure(command=lambda: state["cancel"].set() or status_var.set("Cancelling..."))
    btn_open.configure(command=lambda: state["last_out"] and open_folder(state["last_out"]))

    if dnd is not None:
        def on_drop(event):
            if not state["busy"]:
                start_from_items(list(root.tk.splitlist(event.data)), nb.index(nb.select()) == 1)
        for w in (root, tab_split, tab_join, parts_list, log):
            try:
                w.drop_target_register(dnd.DND_FILES)
                w.dnd_bind("<<Drop>>", on_drop)
            except Exception:
                pass

    def on_close():
        if state["busy"] and not messagebox.askyesno("AgentParcel", "A job is still running. Quit anyway?"):
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    # size the window from its content: everything visible at the minimum size, a roomy default size
    # (minimum = everything visible with a 3-line log; default = a roomier log, capped to the screen)
    log.configure(height=3)
    root.update_idletasks()
    req_w, req_h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.minsize(req_w, req_h)
    log.configure(height=10)
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(max(root.winfo_reqwidth(), 720), sw - 40), min(root.winfo_reqheight(), sh - 80)
    root.geometry("%dx%d" % (w, h))
    root.after(100, poll)
    if start_items:
        root.after(300, lambda: start_from_items(start_items))
    if os.environ.get("AGENTPARCEL_GUI_SMOKE"):
        # test hook: build the window, report, close
        def smoke():
            root.update_idletasks()
            print("GUI OK: %s, tabs=%s, min %dx%d, window %dx%d" % (root.title(), [nb.tab(t, "text") for t in nb.tabs()],
                                                                   req_w, req_h, root.winfo_width(), root.winfo_height()))
            root.destroy()
        root.after(int(os.environ.get("AGENTPARCEL_GUI_SMOKE_MS", "500")), smoke)
    root.mainloop()
    return 0


# ============================================================================
# main
# ============================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentparcel", description="Split a zip or any file into smaller parts, or rebuild it from the parts.")
    ap.add_argument("paths", nargs="*", help="a .zip to split (or parts / a folder of parts to rebuild)")
    ap.add_argument("--join", nargs="+", metavar="PART_OR_FOLDER", help="rebuild the original from these parts / this folder (zip parts or a byte-split)")
    ap.add_argument("--verify", nargs="+", metavar="PART_OR_FOLDER", help="check that every part is present and matches the manifest; write nothing")
    ap.add_argument("--split-bytes", action="store_true", help="split the file as raw bytes even if it is a .zip")
    ap.add_argument("--preset", default="custom", choices=list(PRESET_ORDER),
                    help="part size preset: custom, chatgpt-dot (19,000,000 bytes), chat-512, discord, email, github-release. Limits can change.")
    ap.add_argument("--compress", action="store_true", help="compress each byte part with zlib (off by default)")
    ap.add_argument("--encrypt", action="store_true",
                    help="encrypt byte parts with AES-256-GCM. Password from AGENTPARCEL_PASSWORD or a prompt, never from the command line.")
    ap.add_argument("--regenerate", nargs="+", metavar="PART_OR_FOLDER",
                    help="rewrite only missing or corrupt parts, using --original")
    ap.add_argument("--original", help="original file for --regenerate")
    ap.add_argument("--part-number", action="append", type=int, dest="part_numbers",
                    help="part number to regenerate (repeatable). Default: every missing or corrupt part")
    ap.add_argument("--limit-mb", type=float, default=19.5, help="max size of each part in MB when preset is custom (default 19.5)")
    ap.add_argument("--output-dir", help="where to put the parts / the rebuilt zip")
    ap.add_argument("--no-unpack-inner", action="store_true", help="keep zips inside the zip as plain files")
    ap.add_argument("--include-apps", action="store_true", help="write AgentParcel-apps.zip next to the parts (default)")
    ap.add_argument("--no-include-apps", action="store_true", help="do not write AgentParcel-apps.zip")
    ap.add_argument("--no-gui", action="store_true", help="command-line only (with paths: split them)")
    ap.add_argument("--version", action="version", version="AgentParcel " + VERSION)
    args = ap.parse_args(argv)

    if sys.version_info < (3, 11):
        sys.stderr.write("Note: Python %d.%d works, but 3.11+ is recommended for very large (zip64, >4 GB) archives.\n" % sys.version_info[:2])

    try:
        if args.regenerate:
            if not args.original:
                ap.error("--regenerate needs --original FILE")
            items = list(args.regenerate) + list(args.paths)
            password = None
            manifest = locate_byte_manifest(items)
            if manifest and _load_manifest(manifest).get("encryption"):
                password = cli_password(False)
            report = regenerate_parts(args.original, items, args.part_numbers, password, cli_progress())
            cli_done()
            print(report["message"])
            return 0 if report["ok"] else 2
        if args.verify:
            return run_verify_cli(list(args.verify) + list(args.paths))
        if args.join:
            run_join_cli(list(args.join) + list(args.paths), args)
            return 0
        if args.no_gui:
            if not args.paths:
                ap.error("give the path of a .zip file")
            run_split_cli(args.paths, args)
            return 0
        reason = gui_unavailable_reason()
        if reason is None:
            try:
                return run_gui(args, args.paths)
            except Exception as ex:   # e.g. TclError: no display
                reason = "the window could not be opened (%s)" % ex
        sys.stderr.write("GUI not available: %s. Using text mode.\n" % reason)
        if args.paths:
            run_auto_cli(args.paths, args)
            return 0
        return interactive_text_mode(args, reason)
    except ZsError as ex:
        cli_done()
        sys.stderr.write("ERROR: %s\n" % ex)
        return 2
    except KeyboardInterrupt:
        cli_done()
        sys.stderr.write("Cancelled.\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
