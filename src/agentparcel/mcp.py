#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentParcel MCP server (version @@ZS_VERSION@@)

Lets AI agents that hit a file-upload size limit split big zips / files / folders into
standalone zip parts under a size limit, and rebuild the original from the parts, by calling
tools instead of writing their own scripts.

  * Model Context Protocol over stdio (newline-delimited JSON-RPC 2.0), no dependencies.
    Protocol versions 2025-06-18, 2025-03-26 and 2024-11-05.
  * Uses the AgentParcel engine in agentparcel.py (same folder, or $AGENTPARCEL_PY), so parts
    are 100% compatible with the AgentParcel apps for Windows, Mac and Linux.
  * stdout carries only protocol messages; logs go to stderr.
  * Optional sandbox (old name ZIPSPLITTER_MCP_ROOTS also accepted): AGENTPARCEL_MCP_ROOTS = list of folders (separated by ";" on Windows, ":" elsewhere) that all
    input and output paths must be inside.

Run:   python3 agentparcel_mcp.py            (the MCP client starts it; it then waits on stdin)
       python3 agentparcel_mcp.py --list-tools | --version | --help
Needs Python 3.9+.
"""
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import zipfile

SERVER_NAME = "agentparcel"
SERVER_VERSION = "@@ZS_VERSION@@"  # build.py fills this; a wheel uses the engine version below
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MIB = 1024 * 1024
DEFAULT_MB = 19.5
MIN_LIMIT = 256 * 1024

# --- keep stdout clean: protocol only -----------------------------------------------------------
_OUT = sys.stdout.buffer
sys.stdout = sys.stderr
_WLOCK = threading.Lock()


def log(msg):
    try:
        sys.stderr.write("[agentparcel-mcp] %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def send(msg):
    data = json.dumps(msg, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
    with _WLOCK:
        _OUT.write(data)
        _OUT.flush()


# --- load the AgentParcel engine (never duplicated here) -------------------------------------------
def _load_core():
    here = os.path.dirname(os.path.abspath(__file__))
    packaged = os.path.isfile(os.path.join(here, "__init__.py"))
    cands = []
    env = os.environ.get("AGENTPARCEL_PY") or os.environ.get("ZIPSPLITTER_PY")
    if env:
        cands.append(env)
    sibling = os.path.join(here, "agentparcel.py")
    if os.path.isfile(sibling) and not packaged:
        cands.append(sibling)
    if not packaged:
        cands.extend([
            os.path.join(here, "agentparcel.core.py"),
            os.path.join(here, "core.py"),
            os.path.join(here, "..", "mac-linux", "agentparcel.py"),
            os.path.join(here, "..", "agentparcel.py"),
        ])
    for c in cands:
        if c and os.path.isfile(c):
            spec = importlib.util.spec_from_file_location("agentparcel_engine", os.path.abspath(c))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod, os.path.abspath(c)
    try:
        from agentparcel import core as mod
        return mod, os.path.abspath(getattr(mod, "__file__", "") or "")
    except ImportError:
        pass
    log("ERROR: agentparcel.py not found next to agentparcel_mcp.py (or set AGENTPARCEL_PY).")
    sys.exit(2)


zs, CORE_PATH = _load_core()
if str(SERVER_VERSION).startswith("@@"):
    SERVER_VERSION = zs.VERSION


class ToolError(Exception):
    def __init__(self, message, data=None):
        Exception.__init__(self, message)
        self.data = data or {}


class Cancelled(BaseException):
    pass


# --- paths & sandbox --------------------------------------------------------------------------------
def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def allowed_roots():
    # ZIPSPLITTER_MCP_ROOTS: old name (ZipSplitter 3.x), still honoured if the new one is not set
    raw = (os.environ.get("AGENTPARCEL_MCP_ROOTS") or os.environ.get("ZIPSPLITTER_MCP_ROOTS") or "").strip()
    if not raw:
        return None
    return [_norm(os.path.expanduser(r.strip())) for r in raw.split(os.pathsep) if r.strip()]


def check_roots(path, what):
    roots = allowed_roots()
    if roots is None:
        return
    rp = _norm(path)
    for r in roots:
        base = r.rstrip("\\/")
        if rp == r or rp == base or rp.startswith(base + os.sep):
            return
    raise ToolError("%s is outside the folders this server may use (AGENTPARCEL_MCP_ROOTS): %s" % (what, path),
                    {"allowed_roots": roots})


def abs_path(p, what):
    if not isinstance(p, str) or not p.strip():
        raise ToolError("%s must be a non-empty string path." % what)
    p = os.path.expanduser(p.strip().strip('"'))
    if not os.path.isabs(p):
        raise ToolError("%s must be an absolute path (got %r). The server does not share the agent's working "
                        "directory, so relative paths are ambiguous." % (what, p))
    p = os.path.abspath(p)
    check_roots(p, what)
    return p


def existing(p, what, kind="any"):
    p = abs_path(p, what)
    if not os.path.exists(p):
        raise ToolError("%s does not exist: %s" % (what, p))
    if kind == "file" and not os.path.isfile(p):
        raise ToolError("%s must be a file, not a folder: %s" % (what, p))
    if kind == "dir" and not os.path.isdir(p):
        raise ToolError("%s must be a folder: %s" % (what, p))
    return p


def output_folder(value, default, create):
    if value in (None, ""):
        if default is None:
            return None
        check_roots(default, "output_dir")
        return default
    p = abs_path(value, "output_dir")
    if os.path.isdir(p):
        return p
    if os.path.exists(p):
        raise ToolError("output_dir is a file, not a folder: %s" % p)
    if not create:
        raise ToolError("output_dir does not exist: %s (pass create_output_dir=true to create it)." % p)
    os.makedirs(p)
    return p


def unique_dir(wanted):
    if not os.path.exists(wanted):
        return wanted
    n = 2
    while os.path.exists("%s (%d)" % (wanted, n)):
        n += 1
    return "%s (%d)" % (wanted, n)


def safe_name(name, fallback="files"):
    name = (name or "").strip()
    if name.lower().endswith(".zip"):
        name = name[:-4]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or fallback


def get_limit(args, minimum=None):
    if minimum is None:
        minimum = MIN_LIMIT
    preset = args.get("preset")
    if isinstance(preset, str):
        preset = preset.strip().lower()
    else:
        preset = None
    if preset not in (None, "", "custom"):
        if args.get("max_bytes") is not None:
            raise ToolError("Pass preset or max_bytes, not both. A named preset sets the part size.")
        try:
            limit, _key = zs.limit_from_preset(preset, 0)
        except zs.ZsError as ex:
            raise ToolError(str(ex))
        if limit < minimum:
            raise ToolError("The size limit is too small (minimum %d bytes)." % minimum)
        return limit
    if args.get("max_bytes") is not None:
        try:
            limit = int(args["max_bytes"])
        except (TypeError, ValueError):
            raise ToolError("max_bytes must be an integer.")
    else:
        try:
            mb = float(args.get("max_mb", DEFAULT_MB))
        except (TypeError, ValueError):
            raise ToolError("max_mb must be a number.")
        if not (mb > 0) or math.isinf(mb):
            raise ToolError("max_mb must be a positive number.")
        limit = int(math.floor(mb * MIB))
    if limit < minimum:
        raise ToolError("The size limit is too small (minimum %d bytes)." % minimum)
    return limit


def note_preset(res, args, limit):
    preset = args.get("preset")
    if not isinstance(preset, str):
        return
    preset = preset.strip().lower()
    if preset in ("", "custom"):
        return
    res["preset"] = preset
    res.setdefault("notes", []).insert(
        0, "Preset %s sets the part cap to %d bytes. Upload limits can change; confirm the current one." % (preset, limit))


def budget_for(limit):
    # same numbers the engine uses for one part's payload
    return limit - (22 + 56 + 20) - 32768 - 4096


def as_bool(args, key, default):
    v = args.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false", "1", "0", "yes", "no"):
        return v.lower() in ("true", "1", "yes")
    if v is None:
        return default
    raise ToolError("%s must be true or false." % key)


# --- jobs: progress notifications + cancellation ---------------------------------------------------
class Job:
    def __init__(self, token):
        self.token = token
        self.cancelled = threading.Event()
        self.last_sent = 0.0
        self.last_pct = -1.0
        self.best = 0.0

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def report(self, pct, msg):
        self.check()
        if self.token is None:
            return
        pct = max(self.best, min(100.0, float(pct)))
        now = time.time()
        if pct < 100.0 and pct - self.last_pct < 1.0 and now - self.last_sent < 1.0:
            return
        if pct <= self.last_pct and now - self.last_sent < 1.0:
            return
        self.best = pct
        self.last_pct = pct
        self.last_sent = now
        params = {"progressToken": self.token, "progress": round(pct, 1), "total": 100}
        if msg:
            params["message"] = str(msg)[:200]
        try:
            send({"jsonrpc": "2.0", "method": "notifications/progress", "params": params})
        except Exception:
            pass

    def phase(self, lo, hi):
        def cb(pct, msg):
            self.report(lo + (hi - lo) * max(0.0, min(100.0, float(pct))) / 100.0, msg)
        return cb


# --- result helpers --------------------------------------------------------------------------------
def rebuild_text(n_parts, pieces, apps_path):
    t = ("Every part is a normal standalone .zip (any unzip tool opens it on its own). To get the original back "
         "exactly, put all %d part(s) in one folder, then either call this server's `rebuild` tool with that folder, "
         "run `python3 agentparcel.py --join <folder>`, or use the AgentParcel app (Windows: AgentParcel.bat, "
         "Mac: AgentParcel.command, Linux: agentparcel.sh) -> \"Rebuild from parts\". Every file is verified "
         "with SHA-256." % n_parts)
    if pieces:
        t += (" Some files were too big for one part and were cut into .001/.002/... pieces; rebuild joins them "
              "(by hand: `cat f.001 f.002 > f` on Mac/Linux, `copy /b f.001+f.002 f` on Windows).")
    if apps_path:
        t += " Send AgentParcel-apps.zip along so a recipient without AgentParcel can rebuild (it is not a part)."
    return t


def split_result(r, source_path, source_bytes, extra=None):
    parts = []
    for i, (p, s) in enumerate(r["parts"]):
        parts.append({"part": i + 1, "path": p, "name": os.path.basename(p), "bytes": s})
    pieces = [{"name": s["name"], "pieces": len(s["pieces"])} for s in r["split_files"]]
    apps = None
    notes = []
    if r.get("apps"):
        path, size, note = r["apps"]
        if path:
            apps = {"path": path, "bytes": size}
        elif note:
            notes.append(note)
    if r["failed"]:
        notes.append("Inner zips that could not be opened were kept as plain files: " + "; ".join(r["failed"]))
    if pieces:
        notes.append("%d file(s) were bigger than one part and were cut into pieces." % len(pieces))
    other = []
    ri = os.path.join(r["output_dir"], "REJOIN_INSTRUCTIONS.txt")
    if os.path.isfile(ri):
        other.append(ri)
    res = {
        "ok": True,
        "output_dir": r["output_dir"],
        "set_id": r["set_id"],
        "part_count": len(parts),
        "max_bytes": r["limit"],
        "largest_part_bytes": max([p["bytes"] for p in parts] or [0]),
        "total_bytes": sum(p["bytes"] for p in parts),
        "parts": parts,
        "original": {"path": source_path, "bytes": source_bytes},
        "files_cut_into_pieces": pieces,
        "inner_zips_unpacked": len(r["unpacked"]),
        "apps_bundle": apps,
        "other_files": other,
        "notes": notes,
        "how_to_rebuild": rebuild_text(len(parts), pieces, apps and apps["path"]),
    }
    if extra:
        res.update(extra)
    return res


def split_summary(res):
    lines = ["Created %d part(s) (each <= %d bytes, largest %d) in %s" % (
        res["part_count"], res["max_bytes"], res["largest_part_bytes"], res["output_dir"])]
    lines += ["  %s  %d bytes" % (p["path"], p["bytes"]) for p in res["parts"]]
    if res.get("apps_bundle"):
        lines.append("Apps bundle (not a part): %s" % res["apps_bundle"]["path"])
    lines += ["Note: " + n for n in res["notes"]]
    lines.append(res["how_to_rebuild"])
    return "\n".join(lines)


def cleanup_empty(d):
    try:
        if d and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    except OSError:
        pass


def run_splitter(src, out_dir, limit, unpack, include_apps, cb, job=None):
    try:
        return zs.Splitter(src, out_dir, limit, unpack, cb, include_apps=include_apps,
                           should_cancel=(job.check if job else None)).run()
    except BaseException:
        cleanup_empty(out_dir)
        raise


# --- tools -----------------------------------------------------------------------------------------
def tool_split_zip(args, job):
    src = existing(args.get("path"), "path", "file")
    if not zipfile.is_zipfile(src):
        raise ToolError("Not a .zip file: %s. Use split_files for other files or folders." % src)
    limit = get_limit(args)
    parent = output_folder(args.get("output_dir"), os.path.dirname(src), as_bool(args, "create_output_dir", False))
    out_dir = unique_dir(os.path.join(parent, os.path.splitext(os.path.basename(src))[0] + "_split"))
    size = os.path.getsize(src)
    r = run_splitter(src, out_dir, limit, as_bool(args, "unpack_inner", True), as_bool(args, "include_apps", False),
                     job.phase(0, 100), job)
    res = split_result(r, src, size)
    note_preset(res, args, limit)
    if size <= limit:
        res["notes"].insert(0, "The zip was already under the limit (%d <= %d bytes); it was split anyway." % (size, limit))
    return res, split_summary(res)


def _collect(inputs, exclude):
    """Returns ([(abs_path or None for dir, arcname, size)], skipped[])."""
    entries, skipped, used = [], [], set()
    excl = [_norm(e) for e in exclude if e]

    def excluded(p):
        rp = _norm(p)
        return any(rp == e or rp.startswith(e.rstrip("\\/") + os.sep) for e in excl)

    def top_name(name):
        name = name or "root"
        cand, n = name, 2
        while cand.lower() in used:
            stem, ext = os.path.splitext(name)
            cand = "%s (%d)%s" % (stem, n, ext)
            n += 1
        used.add(cand.lower())
        return cand

    for p in inputs:
        base = os.path.basename(p.rstrip("\\/")) or os.path.splitdrive(p)[0].strip(":\\/") or "root"
        if os.path.isfile(p):
            entries.append((p, top_name(base), os.path.getsize(p)))
            continue
        top = top_name(base)
        entries.append((None, top + "/", 0))
        for root, dirs, files in os.walk(p, followlinks=False):
            keep = []
            for d in sorted(dirs):
                full = os.path.join(root, d)
                if excluded(full):
                    continue
                if os.path.islink(full):
                    skipped.append({"path": full, "reason": "symbolic link to a folder (not followed)"})
                    continue
                keep.append(d)
                rel = os.path.relpath(full, p).replace(os.sep, "/")
                entries.append((None, top + "/" + rel + "/", 0))
            dirs[:] = keep
            for f in sorted(files):
                full = os.path.join(root, f)
                if excluded(full):
                    continue
                if not os.path.isfile(full):
                    skipped.append({"path": full, "reason": "not a regular file (broken link, device, ...)"})
                    continue
                if os.path.islink(full):
                    try:
                        check_roots(os.path.realpath(full), "link target")
                    except ToolError:
                        skipped.append({"path": full, "reason": "symbolic link pointing outside the allowed folders"})
                        continue
                rel = os.path.relpath(full, p).replace(os.sep, "/")
                try:
                    size = os.path.getsize(full)
                except OSError as ex:
                    skipped.append({"path": full, "reason": str(ex)})
                    continue
                entries.append((full, top + "/" + rel, size))
    return entries, skipped


def _build_zip(entries, dest, job, skipped):
    total = float(sum(e[2] for e in entries)) or 1.0
    done = 0
    count = 0
    with zipfile.ZipFile(dest, "x", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path, arc, size in entries:
            job.check()
            if path is None:
                zi = zipfile.ZipInfo(arc, time.localtime()[:6])
                zi.external_attr = 0x10
                zf.writestr(zi, b"")
                continue
            try:
                zi = zipfile.ZipInfo.from_file(path, arc, strict_timestamps=False)
                zi.compress_type = zipfile.ZIP_STORED
                with open(path, "rb") as src, zf.open(zi, "w", force_zip64=size >= 2 ** 31) as dst:
                    while True:
                        chunk = src.read(zs.COPY_BUF)
                        if not chunk:
                            break
                        dst.write(chunk)
                        done += len(chunk)
                        job.report(30.0 * done / total, "Collecting " + arc)
                count += 1
            except (OSError, IOError) as ex:
                skipped.append({"path": path, "reason": str(ex)})
    return count


def tool_split_files(args, job):
    paths = args.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise ToolError("paths must be a list of absolute file and/or folder paths.")
    inputs = []
    for i, p in enumerate(paths):
        a = existing(p, "paths[%d]" % i)
        if a not in inputs:
            inputs.append(a)
    limit = get_limit(args)
    if args.get("archive_name"):
        name = safe_name(args.get("archive_name"))
    elif len(inputs) == 1:
        b = os.path.basename(inputs[0].rstrip("\\/"))
        name = safe_name(os.path.splitext(b)[0] if os.path.isfile(inputs[0]) else b)
    else:
        name = "files"
    parent = output_folder(args.get("output_dir"), os.path.dirname(inputs[0].rstrip("\\/")) or inputs[0],
                           as_bool(args, "create_output_dir", False))
    out_dir = unique_dir(os.path.join(parent, name + "_split"))
    tmp = tempfile.mkdtemp(prefix=".agentparcel-tmp-", dir=parent)
    try:
        entries, skipped = _collect(inputs, [out_dir, tmp])
        files = [e for e in entries if e[0] is not None]
        if not files and not entries:
            raise ToolError("Nothing to pack: the inputs contain no files.")
        tmpzip = os.path.join(tmp, name + ".zip")
        count = _build_zip(entries, tmpzip, job, skipped)
        r = run_splitter(tmpzip, out_dir, limit, as_bool(args, "unpack_inner", True),
                         as_bool(args, "include_apps", False), job.phase(30, 100), job)
        in_bytes = sum(e[2] for e in files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    res = split_result(r, None, in_bytes, {
        "archive_name": name + ".zip",
        "inputs": inputs,
        "files_packed": count,
        "input_bytes": in_bytes,
        "skipped": skipped,
    })
    del res["original"]
    note_preset(res, args, limit)
    if skipped:
        res["notes"].insert(0, "%d item(s) were skipped (see 'skipped')." % len(skipped))
    res["how_to_rebuild"] += (" Rebuilding gives %s.zip (the inputs zipped together, folders kept); use rebuild with "
                              "extract=true to get the files back as a folder." % name)
    return res, split_summary(res)


_MISSING_RX = re.compile(r"Missing (\d+) of (\d+) parts of \"(.*)\": part ([\d, ]+)\n\((.*?)\)", re.S)


def _safe_extract(zip_path, dest):
    os.makedirs(dest)
    n, skipped = 0, []
    base = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for zi in z.infolist():
            name = zi.filename.replace("\\", "/")
            parts = [x for x in name.split("/") if x not in ("", ".")]
            if not parts or ".." in parts or re.match(r"^[A-Za-z]:", parts[0]) or name.startswith("/"):
                skipped.append(zi.filename)
                continue
            target = os.path.join(base, *parts)
            if not os.path.realpath(target).startswith(base + os.sep):
                skipped.append(zi.filename)
                continue
            if name.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            target = zs.unique_path(target)
            with z.open(zi) as s, open(target, "xb") as d:
                shutil.copyfileobj(s, d, zs.COPY_BUF)
            n += 1
    return n, skipped


def tool_rebuild(args, job):
    parts = args.get("parts")
    if isinstance(parts, str):
        parts = [parts]
    if not isinstance(parts, list) or not parts:
        raise ToolError("parts must be a folder, one part, or a list of part paths (absolute).")
    items = [existing(p, "parts[%d]" % i) for i, p in enumerate(parts)]
    out = output_folder(args.get("output_dir"), None, as_bool(args, "create_output_dir", False))
    extract = as_bool(args, "extract", False)
    try:
        r = zs.rebuild(items, out, job.phase(0, 90 if extract else 100), job.check, password=_password_arg(args))
    except zs.ZsError as ex:
        data = dict(getattr(ex, "data", None) or {})
        if data.get("missing_parts") or data.get("corrupt_parts"):
            raise ToolError(str(ex), data)
        m = _MISSING_RX.search(str(ex))
        if m:
            raise ToolError(str(ex), {
                "missing_parts": [int(x) for x in m.group(4).split(",")],
                "missing_names": [x.strip() for x in m.group(5).split(",")],
                "part_count": int(m.group(2)), "original_name": m.group(3)})
        raise
    res = {
        "ok": True,
        "output_path": r["output"],
        "bytes": r["size"],
        "mode": r["mode"],
        "verified": r["mode"] in ("manifest", "bytes"),
        "parts_used": r["parts"],
        "entries": r["entries"],
        "files_verified": r["verified"],
        "inner_zips_recreated": r["inner_zips"],
        "pieces_joined": r["joined"],
        "warnings": list(r["warnings"]),
    }
    text = zs.format_join_summary(r).strip()
    if extract and r["mode"] == "bytes":
        res["warnings"].append("extract applies to a rebuilt zip. This set was a byte split, so the output file is already the original.")
        text += "\nextract was skipped: the output is already the original file."
    elif extract:
        job.report(90, "Extracting")
        dest = unique_dir(os.path.splitext(r["output"])[0])
        n, bad = _safe_extract(r["output"], dest)
        res["extracted_to"] = dest
        res["extracted_files"] = n
        if bad:
            res["warnings"].append("Skipped unsafe entry names while extracting: " + ", ".join(bad[:20]))
        text += "\nExtracted %d file(s) to %s" % (n, dest)
    return res, text


def _password_arg(args):
    if "password" not in args or args.get("password") in (None, ""):
        return None
    if not isinstance(args.get("password"), str):
        raise ToolError("password must be a string. It is not stored in the manifest.")
    return args.get("password")


def tool_split_any_file(args, job):
    src = existing(args.get("path"), "path", "file")
    limit = get_limit(args, 1)
    parent = output_folder(args.get("output_dir"), os.path.dirname(src), as_bool(args, "create_output_dir", False))
    out_dir = unique_dir(os.path.join(parent, os.path.basename(src) + "_split"))
    compress = as_bool(args, "compress", False)
    password = _password_arg(args)
    preset = args.get("preset") if isinstance(args.get("preset"), str) else None
    try:
        r = zs.split_any_file(src, out_dir, limit, job.phase(0, 100),
                              include_apps=as_bool(args, "include_apps", False), should_cancel=job.check,
                              compress=compress, password=password, preset=preset)
    except BaseException:
        cleanup_empty(out_dir)
        raise
    res = split_result(r, src, os.path.getsize(src))
    note_preset(res, args, limit)
    if compress:
        res["compression"] = "zlib"
        res["notes"].append("Each part is zlib-compressed. python3 rebuild.py in the folder decompresses it (stdlib only).")
    if password:
        res["encrypted"] = True
        res["notes"].append("Parts are encrypted with AES-256-GCM. The password is not in the manifest. "
                            "rebuild.py cannot decrypt them; use AgentParcel with the cryptography package.")
    res["mode"] = "bytes"
    res["sha256"] = r.get("sha256")
    for name in (zs.HOWTO_NAME, zs.REBUILD_SCRIPT_NAME, zs.BYTES_MANIFEST):
        path = os.path.join(r["output_dir"], name)
        if os.path.isfile(path) and path not in res["other_files"]:
            res["other_files"].append(path)
    res["how_to_rebuild"] = (
        "Byte split of %s into raw parts, each <= %d bytes. The rebuilt file matches SHA-256 %s. "
        "Call rebuild with this folder, or, with no AgentParcel install, run: python3 \"%s\". "
        "%s in the folder explains that, and includes a PowerShell equivalent."
        % (os.path.basename(src), limit, r.get("sha256"), os.path.join(r["output_dir"], zs.REBUILD_SCRIPT_NAME), zs.HOWTO_NAME))
    if os.path.getsize(src) <= limit:
        res["notes"].insert(0, "The file was already under the limit (%d <= %d bytes); it was split anyway." % (os.path.getsize(src), limit))
    return res, split_summary(res)


def tool_verify(args, job):
    parts = args.get("parts")
    if isinstance(parts, str):
        parts = [parts]
    if not isinstance(parts, list) or not parts:
        raise ToolError("parts must be a folder, one part, or a list of part paths (absolute).")
    items = [existing(p, "parts[%d]" % i) for i, p in enumerate(parts)]
    report = zs.verify_parts(items, job.phase(0, 100), job.check)
    data = {
        "ok": bool(report["ok"]),
        "format": report["format"],
        "original_name": report["original_name"],
        "part_count": report["part_count"],
        "missing_parts": list(report["missing"]),
        "missing_names": list(report["missing_names"]),
        "corrupt_parts": list(report["corrupt"]),
        "present_parts": list(report["present"]),
        "still_needed": report.get("still_needed") or "",
    }
    return data, report["message"] or ("OK" if report["ok"] else "Parts do not match.")


def tool_regenerate_parts(args, job):
    original = existing(args.get("original"), "original", "file")
    parts = args.get("parts")
    if isinstance(parts, str):
        parts = [parts]
    if not isinstance(parts, list) or not parts:
        raise ToolError("parts must be a folder, one part, or a list of part paths (absolute).")
    items = [existing(p, "parts[%d]" % i) for i, p in enumerate(parts)]
    numbers = args.get("part_numbers")
    if numbers is not None:
        if isinstance(numbers, int):
            numbers = [numbers]
        if not isinstance(numbers, list) or not all(isinstance(n, int) for n in numbers):
            raise ToolError("part_numbers must be a list of part numbers (integers). Omit it to regenerate every missing or corrupt part.")
    try:
        report = zs.regenerate_parts(original, items, numbers, password=_password_arg(args),
                                     progress=job.phase(0, 100), should_cancel=job.check)
    except zs.ZsError as ex:
        data = dict(getattr(ex, "data", None) or {})
        raise ToolError(str(ex), data)
    data = {
        "ok": bool(report["ok"]),
        "mode": report.get("mode"),
        "output_dir": report.get("output_dir"),
        "regenerated": report.get("regenerated") or [],
        "still_needed": report.get("still_needed") or "",
        "missing_parts": list(report.get("missing") or []),
        "corrupt_parts": list(report.get("corrupt") or []),
    }
    return data, report.get("message") or ""


def _byte_presence(manifest_path):
    folder = os.path.dirname(manifest_path)
    manifest = zs._load_manifest(manifest_path)
    present, missing, missing_names = [], [], []
    for part in manifest.get("parts") or []:
        number = int(part["part"])
        name = str(part["name"])
        path = os.path.join(folder, name)
        if os.path.isfile(path) and os.path.getsize(path) == int(part["size"]):
            present.append(number)
        else:
            missing.append(number)
            missing_names.append(name)
    return {
        "manifest": manifest_path,
        "original_name": manifest.get("originalName"),
        "original_bytes": manifest.get("originalSize"),
        "sha256": manifest.get("sha256"),
        "part_count": int(manifest.get("partCount") or len(manifest.get("parts") or [])),
        "present_parts": present,
        "missing_parts": missing,
        "missing_names": missing_names,
        "complete": not missing,
        "note": "Sizes were checked. Call verify to compare every part's SHA-256.",
    }


def tool_make_apps_bundle(args, job):
    out = output_folder(args.get("output_dir"), None, as_bool(args, "create_output_dir", False))
    if out is None:
        raise ToolError("output_dir is required.")
    limit = get_limit(args) if (args.get("max_mb") is not None or args.get("max_bytes") is not None) else 1 << 62
    path, size, note = zs.write_apps_bundle(out, limit)
    if not path:
        raise ToolError(note or "The apps bundle could not be created.")
    res = {"ok": True, "path": path, "bytes": size, "version": zs.VERSION,
           "contains": ["HOW TO REBUILD.txt", "Windows/ (AgentParcel.ps1, AgentParcel.bat)",
                        "mac/ (agentparcel.py, AgentParcel.command)", "linux/ (agentparcel.py, agentparcel.sh)",
                        "mcp/ (agentparcel_mcp.py, agentparcel.py)"],
           "note": "Not a part: rebuild ignores it. Send it with the parts so the recipient can rebuild."}
    return res, "Wrote %s (%d bytes)." % (path, size)


def _estimate(compressed_bytes, n_entries, names_bytes, limit):
    budget = budget_for(limit)
    total = compressed_bytes + n_entries * (30 + 46 + 96) + 2 * names_bytes
    return max(1, int(math.ceil(total / float(budget))))


def _estimate_zip(files, n_entries, names_bytes, limit):
    # files bigger than one part are cut into pieces that each fill (most of) their own part
    budget = budget_for(limit)
    chunk = limit - (22 + 56 + 20) - 131072 - 4096
    big = [i.compress_size for i in files if i.compress_size + 200 > budget]
    rest = sum(i.compress_size for i in files if i.compress_size + 200 <= budget)
    n = sum(int(math.ceil(c / (chunk * 0.97))) for c in big)
    if rest or not big:
        n += _estimate(rest, n_entries, names_bytes, limit)
    return max(1, n)


def _read_stub(path):
    try:
        with zipfile.ZipFile(path) as z:
            if zs.APPS_MARKER in z.NameToInfo:
                return "apps", None
            if zs.STUB_NAME in z.NameToInfo:
                return "part", zs.read_json_entry(z, zs.STUB_NAME)
            return "zip", None
    except Exception:
        return "bad", None


def _set_report(folder, set_id=None):
    """All AgentParcel part sets in a folder."""
    sets, others = {}, []
    for fn in sorted(os.listdir(folder), key=lambda s: s.lower()):
        p = os.path.join(folder, fn)
        if not (fn.lower().endswith(".zip") and os.path.isfile(p)):
            continue
        kind, stub = _read_stub(p)
        if kind == "part" and stub:
            sid = str(stub.get("setId"))
            s = sets.setdefault(sid, {"set_id": sid, "original_name": stub.get("originalName"),
                                      "part_count": int(stub.get("partCount", 0)), "present": {}, "made_by": stub.get("tool")})
            s["present"].setdefault(int(stub.get("part", 0)), p)
        elif kind != "apps":
            others.append(p)
    out = []
    for sid, s in sets.items():
        if set_id and sid != set_id:
            continue
        pc = s["part_count"]
        present = sorted(s["present"])
        missing = [k for k in range(1, pc + 1) if k not in s["present"]]
        stem = os.path.splitext(s["original_name"] or "rebuilt.zip")[0]
        w = max(2, len(str(pc)))
        has_manifest = False
        for k in present:
            try:
                with zipfile.ZipFile(s["present"][k]) as z:
                    if zs.MANIFEST_NAME in z.NameToInfo:
                        has_manifest = True
                        break
            except Exception:
                pass
        out.append({"set_id": sid, "original_name": s["original_name"], "part_count": pc, "made_by": s["made_by"],
                    "present_parts": present, "missing_parts": missing,
                    "missing_names": ["%s_part%s.zip" % (stem, str(k).zfill(w)) for k in missing],
                    "complete": not missing and has_manifest, "manifest_found": has_manifest,
                    "paths": [s["present"][k] for k in present],
                    "total_bytes": sum(os.path.getsize(s["present"][k]) for k in present)})
    return out, others


def tool_inspect(args, job):
    p = existing(args.get("path"), "path")
    limit = get_limit(args)
    res = {"ok": True, "path": p, "max_bytes": limit}
    if os.path.isdir(p):
        byte_manifest = os.path.join(p, zs.BYTES_MANIFEST)
        if os.path.isfile(byte_manifest):
            info = _byte_presence(byte_manifest)
            res.update({"kind": "byte_split", "byte_set": info, "recommended_tool": "rebuild" if info["complete"] else "verify"})
            miss = (", MISSING " + ", ".join(info["missing_names"])) if info["missing_names"] else ""
            return res, "Byte-split set for %s: %d/%d part(s)%s. Call verify for checksums." % (
                info["original_name"], len(info["present_parts"]), info["part_count"], miss)
        sets, others = _set_report(p)
        if sets:
            res.update({"kind": "folder_with_parts", "part_sets": sets, "other_zips": others})
            lines = ["Folder with %d AgentParcel part set(s):" % len(sets)]
            for s in sets:
                lines.append("  %s: %d/%d parts%s" % (s["original_name"], len(s["present_parts"]), s["part_count"],
                                                     "" if not s["missing_parts"] else ", MISSING " + ", ".join(s["missing_names"])))
            return res, "\n".join(lines)
        n, total, biggest = 0, 0, []
        for root, dirs, files in os.walk(p):
            job.check()
            for f in files:
                fp = os.path.join(root, f)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                n += 1
                total += sz
                biggest.append((sz, fp))
        biggest.sort(reverse=True)
        res.update({"kind": "folder", "files": n, "bytes": total,
                    "largest_files": [{"path": b, "bytes": a} for a, b in biggest[:5]],
                    "estimated_parts_max": _estimate(total, n, 0, limit),
                    "fits_in_one_part": total < budget_for(limit),
                    "recommended_tool": "split_files",
                    "note": "estimated_parts_max assumes nothing compresses; text/logs usually need far fewer parts."})
        return res, "Folder: %d files, %d bytes; at most ~%d part(s) of %d bytes. Use split_files." % (
            n, total, res["estimated_parts_max"], limit)
    size = os.path.getsize(p)
    res["bytes"] = size
    res["fits_in_one_part"] = size <= limit
    if not zipfile.is_zipfile(p):
        beside = os.path.join(os.path.dirname(p), zs.BYTES_MANIFEST)
        if os.path.isfile(beside):
            info = _byte_presence(beside)
            res.update({"kind": "byte_part", "byte_set": info, "recommended_tool": "rebuild" if info["complete"] else "verify"})
            return res, "File is in a byte-split set for %s (%d/%d parts present). Call verify, then rebuild." % (
                info["original_name"], len(info["present_parts"]), info["part_count"])
        res.update({"kind": "file", "estimated_parts_max": max(1, int(math.ceil(size / float(limit))) if size else 1),
                    "recommended_tool": "split_any_file" if size > limit else None,
                    "note": "Not a zip. split_any_file cuts the exact bytes into numbered parts (no compression). "
                            "split_files packs it into zip parts instead."})
        return res, "File (not a zip), %d bytes: %s" % (
            size, "fits under the limit" if size <= limit else
            "about %d raw part(s); use split_any_file" % res["estimated_parts_max"])
    kind, stub = _read_stub(p)
    if kind == "apps":
        res.update({"kind": "apps_bundle", "note": "AgentParcel-apps.zip (the apps; not a part, rebuild ignores it)."})
        return res, "This is the AgentParcel apps bundle, not a part."
    with zipfile.ZipFile(p) as z:
        infos = z.infolist()
    files = [i for i in infos if not i.is_dir()]
    res.update({"entries": len(infos), "files": len(files), "folders": len(infos) - len(files),
                "uncompressed_bytes": sum(i.file_size for i in files),
                "compressed_bytes": sum(i.compress_size for i in files)})
    if kind == "part" and stub:
        sets, _ = _set_report(os.path.dirname(p), str(stub.get("setId")))
        s = sets[0] if sets else {}
        res.update({"kind": "agentparcel_part", "part": int(stub.get("part", 0)), "part_count": int(stub.get("partCount", 0)),
                    "set_id": stub.get("setId"), "original_name": stub.get("originalName"), "made_by": stub.get("tool"),
                    "set_in_this_folder": s, "recommended_tool": "rebuild"})
        miss = s.get("missing_parts") or []
        return res, "Part %d of %d of %s (set %s). %s" % (
            res["part"], res["part_count"], res["original_name"], res["set_id"],
            "All parts present - ready to rebuild." if s.get("complete") else
            "Missing in this folder: " + ", ".join(s.get("missing_names") or []) if miss else "")
    budget = budget_for(limit)
    too_big = [{"name": i.filename, "bytes": i.file_size, "compressed_bytes": i.compress_size}
               for i in files if i.compress_size + 200 > budget]
    inner = [i.filename for i in files if i.filename.lower().endswith(".zip")]
    names_bytes = sum(len(i.filename.encode("utf-8")) for i in infos)
    legacy = zs.part_info(os.path.basename(p)) is not None
    res.update({"kind": "zip", "inner_zips": inner,
                "largest_entries": [{"name": i.filename, "bytes": i.file_size, "compressed_bytes": i.compress_size}
                                    for i in sorted(files, key=lambda x: -x.compress_size)[:5]],
                "entries_bigger_than_a_part": too_big,
                "estimated_parts": _estimate_zip(files, len(infos), names_bytes, limit),
                "recommended_tool": "split_zip" if size > limit else None})
    if legacy:
        res["note"] = "Name looks like an older AgentParcel part (no label); rebuild can still join such sets."
    msg = "Zip, %d bytes, %d entries. " % (size, len(infos))
    msg += ("Fits under the limit; no split needed." if size <= limit else
            "About %d part(s) of <= %d bytes; use split_zip." % (res["estimated_parts"], limit))
    if too_big:
        msg += " %d entr(y/ies) are bigger than one part and will be cut into pieces." % len(too_big)
    return res, msg


# --- tool catalogue (descriptions are written for agents) -------------------------------------------
_LIMIT_PROPS = {
    "max_mb": {"type": "number", "default": DEFAULT_MB, "minimum": 0.25,
               "description": "Max size of each part in MiB (1 MB here = 1,048,576 bytes). Default 19.5. If your upload "
                              "limit is in decimal MB (e.g. 20 MB = 20,000,000 bytes) pass max_bytes or a smaller max_mb."},
    "max_bytes": {"type": "integer", "minimum": MIN_LIMIT,
                  "description": "Exact max size of each part in bytes. Overrides max_mb. Do not combine with a named preset."},
    "preset": {"type": "string",
               "enum": ["custom", "chatgpt-dot", "chat-512", "discord", "email", "github-release"],
               "description": "Pick the part size from a platform cap. custom (default) uses max_mb/max_bytes. "
                              "chatgpt-dot: 19,000,000 bytes (under a 20,000,000 byte ChatGPT Dot cap). "
                              "chat-512: 500,000,000 bytes (under a 512,000,000 byte chat cap; products differ). "
                              "discord: 24,000,000 bytes for the free 25 MB limit (Nitro is higher and is not this preset). "
                              "email: 24,000,000 bytes under a common 25 MB attachment cap (other providers differ). "
                              "github-release: 1,900,000,000 bytes under GitHub's 2 GB release-asset limit. "
                              "A named preset sets the part size. max_mb is ignored. max_bytes together with a named preset is an error. "
                              "These limits can change; confirm the current one before a large send."},
}
_OUT_PROPS = {
    "output_dir": {"type": "string", "description": "Absolute folder to write into. A new sub-folder "
                                                    "'<name>_split' (or ' (2)', ' (3)'... if taken) is created inside it. "
                                                    "Default: the folder of the input."},
    "create_output_dir": {"type": "boolean", "default": False,
                          "description": "Create output_dir if it does not exist (otherwise that is an error)."},
}
_APPS_PROP = {"include_apps": {"type": "boolean", "default": False,
                               "description": "Also write AgentParcel-apps.zip (AgentParcel for Windows, Mac and Linux, "
                                              "about 0.35 MB; not a part) so a human recipient can rebuild."}}
_UNPACK_PROP = {"unpack_inner": {"type": "boolean", "default": True,
                                 "description": "Unpack zips found inside so their files can be spread over parts and "
                                                "opened directly; rebuild puts the inner zips back (same files, verified)."}}


def _obj(props, required=()):
    s = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        s["required"] = list(required)
    return s


def _merge(*ds):
    out = {}
    for d in ds:
        out.update(d)
    return out


_SPLIT_OUT = {"type": "object", "properties": {
    "ok": {"type": "boolean"}, "output_dir": {"type": "string"}, "set_id": {"type": "string"},
    "part_count": {"type": "integer"}, "max_bytes": {"type": "integer"}, "parts": {"type": "array"},
    "how_to_rebuild": {"type": "string"}}}

TOOLS = [
    {"name": "inspect", "title": "Inspect a zip, part, file or folder",
     "description": "Read-only. Look at a path before splitting or rebuilding. For a .zip: entry count, sizes, entries "
                    "bigger than one part, estimated number of parts at max_mb. For a AgentParcel part: set id, part n of "
                    "N, which parts are present/missing in its folder, whether it is ready to rebuild. For a folder: the "
                    "part sets in it (with missing parts), or for a normal folder file count/bytes and a worst-case part "
                    "estimate. For any other file: size and worst-case part estimate. Paths must be absolute.",
     "inputSchema": _obj(_merge({"path": {"type": "string", "description": "Absolute path of a .zip, a part, a folder or any file."}},
                                _LIMIT_PROPS), ["path"]),
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "split_zip", "title": "Split a .zip into smaller standalone zips",
     "description": "Use when a .zip is too big to upload/attach. Splits it into parts named <name>_part01.zip, "
                    "_part02.zip ... each <= max_mb, and each a complete, valid zip that opens on its own (files are "
                    "never cut unless a single file is bigger than a part; such files become .001/.002 pieces). Returns "
                    "absolute paths and byte sizes of every part: upload all of them. Never overwrites anything. The "
                    "original can be rebuilt exactly (SHA-256 verified) with the rebuild tool or the AgentParcel apps. "
                    "For anything that is not a .zip (folders, logs, videos...) use split_files.",
     "inputSchema": _obj(_merge({"path": {"type": "string", "description": "Absolute path of the .zip to split."}},
                                _LIMIT_PROPS, _OUT_PROPS, _UNPACK_PROP, _APPS_PROP), ["path"]),
     "outputSchema": _SPLIT_OUT,
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "split_any_file", "title": "Split any file into exact byte parts",
     "description": "Byte-level split of ANY file (PDF, video, dataset, CAD, a zip you must not repack, and so on) into "
                    "numbered raw parts, each <= max_mb / max_bytes. Parts are not zips. Rebuilding concatenates them "
                    "and checks the original SHA-256. The output folder also contains _agentparcel_bytes.json, "
                    "HOW-TO-REBUILD.txt, and a dependency-free rebuild.py (Python 3 standard library only) so a receiver "
                    "can rebuild without AgentParcel. Use split_zip or split_files when you want standalone zip parts.",
     "inputSchema": _obj(_merge({"path": {"type": "string", "description": "Absolute path of the file to split. Any type."}},
                                {"max_mb": {"type": "number", "default": DEFAULT_MB, "minimum": 0,
                                            "description": "Max size of each raw part in MiB. Default 19.5. Ignored when preset is a named preset."},
                                 "max_bytes": {"type": "integer", "minimum": 1,
                                               "description": "Exact max size of each raw part in bytes. Overrides max_mb. Minimum 1. Do not combine with a named preset."},
                                 "preset": _LIMIT_PROPS["preset"],
                                 "compress": {"type": "boolean", "default": False,
                                              "description": "Compress each byte part with zlib (level 6) before the size cap. Off by default. "
                                                             "python3 rebuild.py in the folder decompresses these parts with the standard library."},
                                 "password": {"type": "string",
                                              "description": "If set, encrypt each byte part with AES-256-GCM (scrypt key derivation). "
                                                             "Requires the cryptography package (pip install agentparcel[crypto]). "
                                                             "Off when omitted. The password is never written to the manifest or the log."}},
                                _OUT_PROPS, _APPS_PROP), ["path"]),
     "outputSchema": _SPLIT_OUT,
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "split_files", "title": "Zip files/folders and split into parts",
     "description": "Use when files or folders that are not a .zip are too big to upload (a big log, video, dataset, "
                    "project folder, several files). Packs the inputs into <archive_name>.zip (folders keep their "
                    "structure) and splits it into standalone zip parts <= max_mb, in one step, without writing the full "
                    "zip anywhere permanent. A single file bigger than a part is cut into .001/.002 pieces inside "
                    "consecutive parts. Returns every part's absolute path and size. Rebuild with the rebuild tool "
                    "(extract=true gives the files back as a folder).",
     "inputSchema": _obj(_merge({
         "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                   "description": "Absolute paths of files and/or folders to include."},
         "archive_name": {"type": "string", "description": "Name for the archive and parts (default: the single input's "
                                                           "name, or 'files')."}},
         _LIMIT_PROPS, _OUT_PROPS, _UNPACK_PROP, _APPS_PROP), ["paths"]),
     "outputSchema": _SPLIT_OUT,
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "verify", "title": "Check parts before rebuilding",
     "description": "Read-only check before rebuild. Confirms every part is present and each part's checksum matches "
                    "the manifest. Works for zip part sets (_zipsplitter_manifest.json, and _agentparcel_zipset.json when "
                    "that sidecar is present) and for byte-split sets (_agentparcel_bytes.json). Does not write a rebuilt "
                    "file. ok is false when something is wrong; missing_parts, missing_names, and corrupt_parts name exactly "
                    "which parts. A part that fails its SHA-256 is corrupt, not missing.",
     "inputSchema": _obj({
         "parts": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                   "description": "Absolute paths: the parts folder, one part, or all parts. A single string is also accepted."}},
         ["parts"]),
     "outputSchema": {"type": "object", "properties": {
         "ok": {"type": "boolean"}, "missing_parts": {"type": "array"}, "missing_names": {"type": "array"},
         "corrupt_parts": {"type": "array"}, "present_parts": {"type": "array"}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "regenerate_parts", "title": "Re-send only the missing or corrupt parts",
     "description": "Given the original file and an existing part set, rewrite only the parts that verify reports as "
                    "missing or corrupt (or the part_numbers you list). Parts that already match are left untouched, "
                    "so you can upload just the replacements. Works for a byte-split folder and, when a fresh split "
                    "lands on the same layout, for a zip part set. If the zip layout does not match, nothing is replaced "
                    "and the error tells you to split the whole zip again. An encrypted byte set needs password. "
                    "The password is not stored. still_needed names any parts that are still missing or corrupt.",
     "inputSchema": _obj({
         "original": {"type": "string", "description": "Absolute path of the original file that was split."},
         "parts": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                   "description": "Absolute paths: the parts folder, one part, or all parts."},
         "part_numbers": {"type": "array", "items": {"type": "integer"},
                          "description": "Part numbers to rewrite. Omit to rewrite every missing or corrupt part from verify."},
         "password": {"type": "string",
                      "description": "Password for an encrypted byte set. Not stored and not logged."}},
         ["original", "parts"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "rebuild", "title": "Rebuild the original from parts",
     "description": "Rebuild the original from AgentParcel parts (made by this server or by any AgentParcel app). "
                    "Zip part sets become the original zip (every file verified, size + SHA-256). A byte-split set "
                    "(folder with _agentparcel_bytes.json, or any file in that folder) becomes the original file, byte for "
                    "byte. Give the folder, any single part (the others are found next to it), or an explicit list. If parts "
                    "are missing or corrupt it fails and names exactly which (missing_parts / missing_names / corrupt_parts). "
                    "AgentParcel-apps.zip is ignored. Output never overwrites. extract=true unpacks a rebuilt zip into a new "
                    "folder; it does not apply to a byte-split file.",
     "inputSchema": _obj({
         "parts": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                   "description": "Absolute paths: a folder containing the parts, one part, or all parts. A single string is also accepted."},
         "output_dir": {"type": "string", "description": "Absolute folder for the rebuilt zip (default: next to the parts)."},
         "create_output_dir": _OUT_PROPS["create_output_dir"],
         "extract": {"type": "boolean", "default": False,
                     "description": "Also extract the rebuilt zip into a new folder next to it."},
         "password": {"type": "string",
                      "description": "Password for an encrypted byte-split set. Never stored. Omit for zip sets and for plain byte sets."}}, ["parts"]),
     "outputSchema": {"type": "object", "properties": {"ok": {"type": "boolean"}, "output_path": {"type": "string"},
                                                        "bytes": {"type": "integer"}, "verified": {"type": "boolean"}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "make_apps_bundle", "title": "Write AgentParcel-apps.zip",
     "description": "Write AgentParcel-apps.zip (AgentParcel for Windows, Mac and Linux plus this MCP server and "
                    "'HOW TO REBUILD.txt') into output_dir, so a human who receives parts can rebuild them. Never "
                    "overwrites (adds ' (2)'). Optional max_mb/max_bytes: fail if the bundle would be bigger.",
     "inputSchema": _obj(_merge({"output_dir": {"type": "string", "description": "Absolute folder to write into."},
                                 "create_output_dir": _OUT_PROPS["create_output_dir"]}, _LIMIT_PROPS), ["output_dir"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
]

HANDLERS = {"inspect": tool_inspect, "split_zip": tool_split_zip, "split_any_file": tool_split_any_file,
            "split_files": tool_split_files, "verify": tool_verify, "regenerate_parts": tool_regenerate_parts,
            "rebuild": tool_rebuild, "make_apps_bundle": tool_make_apps_bundle}

INSTRUCTIONS = (
    "AgentParcel splits big zips/files/folders into parts under an upload size limit and rebuilds the original "
    "(verified). Typical flow: inspect(path) -> split_zip (a .zip, standalone zip parts) or split_any_file (any one "
    "file, exact bytes, plus HOW-TO-REBUILD.txt and rebuild.py) or split_files (files/folders packed into zip parts) "
    "-> upload every returned part path. Pass preset to pick a platform cap (chatgpt-dot, chat-512, discord, email, "
    "github-release) instead of max_mb. Those caps sit under the advertised limit and the real limit can change. "
    "split_any_file compress=true uses zlib (rebuild.py can undo it). password encrypts byte parts with AES-256-GCM; "
    "it is never stored. Before rebuild, call verify(parts=[folder]); it names missing and corrupt parts and writes "
    "nothing. regenerate_parts(original, parts) rewrites only those parts so you can re-upload them. "
    "To restore: rebuild(parts=[folder]) handles both zip sets and byte-split sets, and says which parts are still "
    "needed when it cannot. All paths must be absolute. max_mb is MiB (19.5 default = 20,447,232 bytes); use max_bytes "
    "for an exact byte limit. Nothing is ever overwritten. A cancelled call deletes the partial output it had started.")


# --- JSON-RPC / MCP server ------------------------------------------------------------------------
class Server:
    def __init__(self):
        self.protocol = PROTOCOLS[0]
        self.initialized = False
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.threads = []

    def tools_for_client(self):
        out = []
        for t in TOOLS:
            t = dict(t)
            if self.protocol < "2025-06-18":
                t.pop("outputSchema", None)
                t.pop("title", None)
            out.append(t)
        return out

    @staticmethod
    def error(req_id, code, message, data=None):
        e = {"code": code, "message": message}
        if data is not None:
            e["data"] = data
        send({"jsonrpc": "2.0", "id": req_id, "error": e})

    @staticmethod
    def result(req_id, result):
        send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def handle(self, msg):
        if isinstance(msg, list):            # JSON-RPC batch (2025-03-26)
            if not msg:
                self.error(None, -32600, "Invalid Request: empty batch")
            for m in msg:
                self.handle(m)
            return
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            self.error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
            return
        method = msg.get("method")
        has_id = "id" in msg and msg.get("id") is not None
        req_id = msg.get("id")
        params = msg.get("params") or {}
        if method is None:
            return                            # a response to something we never asked: ignore
        if not isinstance(method, str) or not isinstance(params, dict):
            if has_id:
                self.error(req_id, -32600, "Invalid Request")
            return
        if not has_id:
            self.notification(method, params)
            return
        try:
            if method == "initialize":
                want = params.get("protocolVersion")
                self.protocol = want if want in PROTOCOLS else PROTOCOLS[0]
                ci = params.get("clientInfo") or {}
                log("initialize from %s %s, protocol %s (asked %s)" % (ci.get("name"), ci.get("version"), self.protocol, want))
                self.result(req_id, {
                    "protocolVersion": self.protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "title": "AgentParcel", "version": SERVER_VERSION},
                    "instructions": INSTRUCTIONS})
            elif method == "ping":
                self.result(req_id, {})
            elif method == "tools/list":
                self.result(req_id, {"tools": self.tools_for_client()})
            elif method == "tools/call":
                self.start_call(req_id, params)
            elif method == "resources/list":
                self.result(req_id, {"resources": []})
            elif method == "resources/templates/list":
                self.result(req_id, {"resourceTemplates": []})
            elif method == "prompts/list":
                self.result(req_id, {"prompts": []})
            elif method == "logging/setLevel":
                self.result(req_id, {})
            else:
                self.error(req_id, -32601, "Method not found: %s" % method)
        except Exception as ex:
            log(traceback.format_exc())
            self.error(req_id, -32603, "Internal error: %s" % ex)

    def notification(self, method, params):
        if method == "notifications/initialized":
            self.initialized = True
        elif method == "notifications/cancelled":
            rid = params.get("requestId")
            with self.jobs_lock:
                job = self.jobs.get(json.dumps(rid))
            if job:
                log("cancel requested for %r" % (rid,))
                job.cancelled.set()

    def start_call(self, req_id, params):
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in HANDLERS:
            self.error(req_id, -32602, "Unknown tool: %r" % (name,), {"tools": sorted(HANDLERS)})
            return
        if not isinstance(args, dict):
            self.error(req_id, -32602, "arguments must be an object")
            return
        meta = params.get("_meta") or {}
        job = Job(meta.get("progressToken") if isinstance(meta, dict) else None)
        key = json.dumps(req_id)
        with self.jobs_lock:
            self.jobs[key] = job
        th = threading.Thread(target=self.run_call, args=(req_id, key, name, args, job), daemon=True)
        self.threads.append(th)
        th.start()

    def run_call(self, req_id, key, name, args, job):
        started = time.time()
        try:
            data, text = HANDLERS[name](args, job)
            log("%s ok in %.1fs" % (name, time.time() - started))
            self.result(req_id, {"content": [{"type": "text", "text": text},
                                             {"type": "text", "text": json.dumps(data, indent=1, ensure_ascii=False)}],
                                 "structuredContent": data, "isError": False})
        except Cancelled:
            log("%s cancelled" % name)          # per spec: no response for a cancelled request
        except (ToolError, zs.ZsError) as ex:
            data = {"ok": False, "error": str(ex)}
            data.update(getattr(ex, "data", {}) or {})
            log("%s error: %s" % (name, str(ex).splitlines()[0]))
            self.result(req_id, {"content": [{"type": "text", "text": "ERROR: " + str(ex)}],
                                 "structuredContent": data, "isError": True})
        except Exception as ex:
            log(traceback.format_exc())
            data = {"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}
            self.result(req_id, {"content": [{"type": "text", "text": "ERROR: " + data["error"]}],
                                 "structuredContent": data, "isError": True})
        finally:
            with self.jobs_lock:
                self.jobs.pop(key, None)

    def serve(self):
        inp = sys.stdin.buffer
        log("AgentParcel MCP server %s ready (engine %s, Python %d.%d)%s" % (
            SERVER_VERSION, CORE_PATH, sys.version_info[0], sys.version_info[1],
            "; roots: %s" % allowed_roots() if allowed_roots() else ""))
        if zs.VERSION != SERVER_VERSION:
            log("WARNING: agentparcel.py is version %s, this server is %s" % (zs.VERSION, SERVER_VERSION))
        while True:
            try:
                line = inp.readline()
            except KeyboardInterrupt:
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception as ex:
                self.error(None, -32700, "Parse error: %s" % ex)
                continue
            try:
                self.handle(msg)
            except (BrokenPipeError, OSError):
                break
        # stdin closed: the client is shutting us down. Stop running jobs so they clean up their temp files.
        with self.jobs_lock:
            for j in self.jobs.values():
                j.cancelled.set()
        for th in self.threads:
            th.join(timeout=15)
        log("bye")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        sys.stderr.write("AgentParcel MCP server %s\n" % SERVER_VERSION)
        return 0
    if "--help" in argv or "-h" in argv:
        sys.stderr.write(__doc__)
        return 0
    if "--list-tools" in argv:
        _OUT.write((json.dumps(TOOLS, indent=1) + "\n").encode("utf-8"))
        _OUT.flush()
        return 0
    if sys.version_info < (3, 9):
        log("Python 3.9+ is required.")
        return 2
    Server().serve()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
