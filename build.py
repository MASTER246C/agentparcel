#!/usr/bin/env python3
"""
Build script for AgentParcel.  Regenerates every release file from src/ so the Windows,
Mac and Linux versions always carry the same version and the same embedded payload.

  src/VERSION                 version string (e.g. 3.1.0)
  src/AgentParcel.core.ps1    Windows program (empty payload block)
  src/agentparcel.core.py     Mac/Linux program (empty payload block)
  src/AgentParcel.bat, Install-Python-for-AgentParcel.bat, README-windows.txt, AgentParcel.command, agentparcel.sh,
  agentparcel.desktop, README-mac-linux.txt, HOW-TO-REBUILD.txt

Payload = base64( raw-deflate( JSON {"format":"zipsplitter-payload","version":..,"files":{name: text}} ) ).
It contains both program sources (with EMPTY payload blocks) and all other release files, and
is embedded identically into both programs. Each program can therefore regenerate the complete
Windows, Mac and Linux releases (byte-identical to dist/) for AgentParcel-apps.zip.

Output: dist/windows/*, dist/mac-linux/*, dist/AgentParcel-mac-linux.zip
"""
import base64, hashlib, re, importlib.util, json, os, shutil, sys, time, zipfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
DIST = os.path.join(HERE, "dist")


def read(name):
    with open(os.path.join(SRC, name), "rb") as f:
        data = f.read()
    text = data.decode("ascii")          # everything must be pure ASCII
    text = text.replace("\r\n", "\n")
    # Windows files get CRLF, Unix files LF
    if name.endswith((".ps1", ".bat")) or name in ("README-windows.txt", "HOW-TO-REBUILD.txt"):
        text = text.replace("\n", "\r\n")
    return text


PC_PYTHON = r"C:\Users\bobji\AppData\Local\Programs\Python\Python315\python.exe"
GENERIC_WIN = {
    "py": r"C:\Users\YOU\AppData\Local\Programs\Python\Python315\python.exe",
    "mcp": r"C:\Users\YOU\Desktop\AgentParcel\mcp\agentparcel_mcp.py",
    "root": r"C:\Users\YOU",
    "note": "No Python yet? Double-click Install-Python-for-AgentParcel.bat (next to this file, or in the Windows\\\n"
            "folder of AgentParcel-apps.zip) - it installs Python 3.15 for your user only (or run:\n"
            "winget install -e --id Python.Python.3.15 --scope user), tests the server and writes\n"
            "MCP-config-snippets.txt with your real paths.\n"
            "Use the full path of a real python.exe (run:  where.exe python  or  py -3 -c \"import sys; print(sys.executable)\").\n"
            "Not the WindowsApps\\python.exe Store shortcut. Put agentparcel_mcp.py and agentparcel.py in one folder.\n",
}


UNIX_ALL = {
    "UHEAD": "MAC / LINUX  (replace /Users/YOU/AgentParcel with where you put the files; on Linux /home/YOU/...)",
    "UFIND": "Find python:  which python3      (macOS: install from python.org or \"brew install python\" if missing)\n",
    "UCD": "Claude Desktop (macOS): ~/Library/Application Support/Claude/claude_desktop_config.json",
    "UPY": "/usr/local/bin/python3",
    "UMCP": "/Users/YOU/AgentParcel/agentparcel_mcp.py",
    "UMCPH": "$HOME/AgentParcel/agentparcel_mcp.py",
    "UROOT": "/Users/YOU",
}


def render_mcp_readme(text, py, mcp, root, note, platform="all", unix=None):
    """platform: all | windows | unix  (unix uses the `unix` token dict)."""
    keep = {"all": ("WIN", "UNIX"), "windows": ("WIN",), "unix": ("UNIX",)}[platform]
    for sec in ("WIN", "UNIX"):
        pat = r"@@IF-%s@@\n(.*?)@@END-%s@@\n" % (sec, sec)
        text = re.sub(pat, (lambda m: m.group(1)) if sec in keep else "", text, flags=re.S)
    j = lambda v: json.dumps(v)[1:-1]
    for k, v in (("@@PYJ@@", j(py)), ("@@MCPJ@@", j(mcp)), ("@@ROOTJ@@", j(root)), ("@@PYNOTE@@", note),
                 ("@@PY@@", py), ("@@MCP@@", mcp), ("@@ROOT@@", root)):
        text = text.replace(k, v)
    for k, v in (unix or UNIX_ALL).items():
        text = text.replace("@@%s@@" % k, v)
    assert "@@" not in text, re.findall(r"@@\w+@@", text)
    return text


def build_release(version, sub, files, ps_full, py_full, now):
    rsrc = lambda n: sub(read(os.path.join("release", n)))
    crlf = lambda t: t.replace("\r\n", "\n").replace("\n", "\r\n")
    lf = lambda t: t.replace("\r\n", "\n")
    rdir = os.path.join(DIST, "release")
    os.makedirs(rdir)
    common = lambda plat, nl: [
        ("CHANGELOG.md", nl(rsrc("CHANGELOG.md")), 0o644),
        ("TESTING-CHECKLIST.md", nl(rsrc("TESTING-%s.md" % plat)), 0o644),
        ("README.md", nl(rsrc("README-%s.md" % plat)), 0o644),
        ("VERSION", nl(version + "\n"), 0o644),
        ("LICENSE.txt", nl(files["LICENSE.txt"]), 0o644),
        ("README-format.txt", nl(files["README-windows.txt"]), 0o644),
    ]
    top = lambda plat: "AgentParcel-%s-%s" % (version, plat)
    win_mcp = r"C:\Users\YOU\%s\mcp\agentparcel_mcp.py" % top("windows")
    win_note = ("Easiest: double-click ..\\Install-Python-for-AgentParcel.bat (in the folder above this one).\n"
                "It installs Python 3.15 for your user only (no admin), tests this server and writes\n"
                "MCP-config-snippets.txt with the exact paths for this PC. The paths below are examples:\n"
                "change C:\\Users\\YOU\\%s to where you extracted the package.\n"
                "Not the WindowsApps\\python.exe Store shortcut.\n" % top("windows"))
    unix = {
        "linux": {
            "UHEAD": "LINUX  (replace /home/YOU with your home folder if you extracted elsewhere)",
            "UFIND": "Find python:  command -v python3   (missing? run ../install-deps.sh)\n",
            "UCD": "Claude Desktop: there is no official Linux build - use Claude Code, Cursor or Codex CLI.",
            "UPY": "/usr/bin/python3",
            "UMCP": "/home/YOU/%s/mcp/agentparcel_mcp.py" % top("linux"),
            "UMCPH": "$HOME/%s/mcp/agentparcel_mcp.py" % top("linux"),
            "UROOT": "/home/YOU",
        },
        "macos": {
            "UHEAD": "MACOS  (UNTESTED - replace /Users/YOU with your home folder if you extracted elsewhere)",
            "UFIND": ("Find python:  ../install-python-macos.sh --check   (prints the path to use)\n"
                      "  python.org: /usr/local/bin/python3   Homebrew: /opt/homebrew/bin/python3 (Apple silicon)\n"
                      "  Don't use /usr/bin/python3 (Apple's stub). If yours differs, change \"command\" below.\n"),
            "UCD": ("Claude Desktop: ~/Library/Application Support/Claude/claude_desktop_config.json\n"
                    "  (Settings > Developer > Edit Config), merge into \"mcpServers\" like the Cursor example, restart it."),
            "UPY": "/usr/local/bin/python3",
            "UMCP": "/Users/YOU/%s/mcp/agentparcel_mcp.py" % top("macos"),
            "UMCPH": "$HOME/%s/mcp/agentparcel_mcp.py" % top("macos"),
            "UROOT": "/Users/YOU",
        },
    }
    mcp_readme = sub(read("README-mcp.txt"))
    pkgs = {
        "windows": [
            ("AgentParcel.bat", files["AgentParcel.bat"], 0o644),
            ("AgentParcel.ps1", ps_full, 0o644),
            ("Install-Python-for-AgentParcel.bat", files["Install-Python-for-AgentParcel.bat"], 0o644),
            ("mcp/agentparcel_mcp.py", files["agentparcel_mcp.py"], 0o755),
            ("mcp/agentparcel.py", py_full, 0o755),
            ("mcp/README-mcp.txt", crlf(render_mcp_readme(mcp_readme, GENERIC_WIN["py"], win_mcp, r"C:\Users\YOU",
                                                          win_note, "windows")), 0o644),
        ] + common("windows", crlf),
        "linux": [
            ("agentparcel.sh", files["agentparcel.sh"], 0o755),
            ("agentparcel.py", py_full, 0o755),
            ("agentparcel.desktop", files["agentparcel.desktop"].replace(
                "/home/YOUR-USER-NAME/AgentParcel/agentparcel.png",
                "/home/YOUR-USER-NAME/%s/assets/agentparcel-256.png" % top("linux")).replace(
                "/home/YOUR-USER-NAME/AgentParcel/", "/home/YOUR-USER-NAME/%s/" % top("linux")), 0o644),
            ("install-deps.sh", rsrc("install-deps.sh"), 0o755),
            ("README-mac-linux.txt", files["README-mac-linux.txt"], 0o644),
            ("mcp/agentparcel_mcp.py", files["agentparcel_mcp.py"], 0o755),
            ("mcp/agentparcel.py", py_full, 0o755),
            ("mcp/README-mcp.txt", render_mcp_readme(mcp_readme, "", "", "", "", "unix", unix["linux"]), 0o644),
        ] + common("linux", lf),
        "macos": [
            ("AgentParcel.command", files["AgentParcel.command"], 0o755),
            ("agentparcel.py", py_full, 0o755),
            ("install-python-macos.sh", rsrc("install-python-macos.sh"), 0o755),
            ("README-mac-linux.txt", files["README-mac-linux.txt"], 0o644),
            ("mcp/agentparcel_mcp.py", files["agentparcel_mcp.py"], 0o755),
            ("mcp/agentparcel.py", py_full, 0o755),
            ("mcp/README-mcp.txt", render_mcp_readme(mcp_readme, "", "", "", "", "unix", unix["macos"]), 0o644),
        ] + common("macos", lf),
    }
    def asset(name):
        with open(os.path.join(ASSETS, name), "rb") as f:
            return f.read()
    brand = ["agentparcel-%d.png" % s for s in (16, 24, 32, 48, 64, 128, 256, 512)] + \
            ["agentparcel-wordmark.png", "agentparcel-wordmark-black.png"]
    extra = {"windows": ["AgentParcel.ico"], "linux": [], "macos": ["AgentParcel.icns"]}
    for plat in pkgs:
        pkgs[plat] += [("assets/" + n, asset(n), 0o644) for n in brand + extra[plat]]
    sums = []
    for plat, entries in pkgs.items():
        t = top(plat)
        zpath = os.path.join(rdir, t + ".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for d in (t + "/", t + "/assets/", t + "/mcp/"):
                zi = zipfile.ZipInfo(d, now)
                zi.create_system = 3
                zi.external_attr = (0o40755 << 16) | 0x10
                z.writestr(zi, b"")
            for name, text, mode in sorted(entries, key=lambda e: (e[0].count("/"), e[0].lower())):
                zi = zipfile.ZipInfo(t + "/" + name, now)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.create_system = 3
                zi.external_attr = (0o100000 | mode) << 16
                z.writestr(zi, text if isinstance(text, bytes) else text.encode("ascii"))
        with open(zpath, "rb") as f:
            sums.append("%s  %s" % (hashlib.sha256(f.read()).hexdigest(), t + ".zip"))
    with open(os.path.join(rdir, "SHA256SUMS.txt"), "w", newline="\n") as f:
        f.write("\n".join(sums) + "\n")
    for n in ("RELEASE-NOTES.md", "CHANGELOG.md"):
        with open(os.path.join(rdir, n), "w", newline="\n") as f:
            f.write(lf(rsrc(n)))


ASSETS = os.path.join(SRC, "assets")


def asset_b64(name):
    with open(os.path.join(ASSETS, name), "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pc-python", default=PC_PYTHON, help="Windows python.exe path for a machine-specific dist/mcp-pc/README-mcp.txt")
    ap.add_argument("--pc-dir", help="Windows folder that will hold agentparcel_mcp.py")
    ap.add_argument("--pc-root", help="Windows folder for AGENTPARCEL_MCP_ROOTS")
    ap.add_argument("--pc-note", default="", help="extra note at the top of the Windows section")
    opts = ap.parse_args()
    version = read("VERSION").strip()
    sub = lambda t: t.replace("@@ZS_VERSION@@", version)
    ps_core = sub(read("AgentParcel.core.ps1"))
    py_core = sub(read("agentparcel.core.py"))
    assert "\r\n" in ps_core and "\r\n" not in py_core, "line endings: .ps1 must be CRLF, .py LF"
    for core in (ps_core, py_core):
        assert len(re.findall(r"(?m)^#==ZS-PAYLOAD-(BEGIN|END)==\r?$", core)) == 2, "payload marker lines"
    files = {
        "AgentParcel.ps1": ps_core,
        "agentparcel.py": py_core,
        "AgentParcel.bat": read("AgentParcel.bat"),
        "README-windows.txt": sub(read("README-windows.txt")),
        "AgentParcel.command": read("AgentParcel.command"),
        "agentparcel.sh": read("agentparcel.sh"),
        "agentparcel.desktop": read("agentparcel.desktop"),
        "README-mac-linux.txt": sub(read("README-mac-linux.txt")),
        "HOW TO REBUILD.txt": read("HOW-TO-REBUILD.txt"),
        "LICENSE.txt": read(os.path.join("release", "LICENSE.txt")).replace("\n", "\r\n"),
        "icon-AgentParcel.ico.b64": asset_b64("AgentParcel-small.ico"),
        "icon-agentparcel-64.png.b64": asset_b64("agentparcel-64.png"),
        "icon-agentparcel-32.png.b64": asset_b64("agentparcel-32.png"),
        "agentparcel_mcp.py": sub(read("agentparcel_mcp.py")),
        "README-mcp.txt": render_mcp_readme(sub(read("README-mcp.txt")), **GENERIC_WIN),
        "Install-Python-for-AgentParcel.bat": sub(read("Install-Python-for-AgentParcel.bat")),
    }
    assert "\r\n" in files["Install-Python-for-AgentParcel.bat"] and "@@" not in files["Install-Python-for-AgentParcel.bat"]
    assert "\r\n" not in files["agentparcel_mcp.py"]
    blob = json.dumps({"format": "zipsplitter-payload", "version": version, "files": files},
                      ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    b64 = base64.b64encode(co.compress(blob) + co.flush()).decode("ascii")

    # use the program's own fill function so build and runtime can never disagree
    spec = importlib.util.spec_from_file_location("zs_core", os.path.join(SRC, "agentparcel.core.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ps_full = mod.fill_payload(ps_core, b64, "\r\n", "ps")
    py_full = mod.fill_payload(py_core, b64, "\n", "py")

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    win = os.path.join(DIST, "windows")
    ml = os.path.join(DIST, "mac-linux")
    os.makedirs(win)
    os.makedirs(ml)

    def put(path, text, mode=0o644):
        with open(path, "wb") as f:
            f.write(text.encode("ascii"))
        os.chmod(path, mode)

    put(os.path.join(win, "AgentParcel.ps1"), ps_full)
    put(os.path.join(win, "AgentParcel.bat"), files["AgentParcel.bat"])
    put(os.path.join(win, "README.txt"), files["README-windows.txt"])
    put(os.path.join(win, "Install-Python-for-AgentParcel.bat"), files["Install-Python-for-AgentParcel.bat"])
    put(os.path.join(ml, "agentparcel.py"), py_full, 0o755)
    put(os.path.join(ml, "AgentParcel.command"), files["AgentParcel.command"], 0o755)
    put(os.path.join(ml, "agentparcel.sh"), files["agentparcel.sh"], 0o755)
    put(os.path.join(ml, "agentparcel.desktop"), files["agentparcel.desktop"])
    put(os.path.join(ml, "README-mac-linux.txt"), files["README-mac-linux.txt"])
    put(os.path.join(ml, "README-format-and-windows.txt"), files["README-windows.txt"])
    put(os.path.join(ml, "agentparcel_mcp.py"), files["agentparcel_mcp.py"], 0o755)
    put(os.path.join(ml, "README-mcp.txt"), files["README-mcp.txt"])
    mcpd = os.path.join(DIST, "mcp")
    os.makedirs(mcpd)
    put(os.path.join(mcpd, "agentparcel_mcp.py"), files["agentparcel_mcp.py"], 0o755)
    put(os.path.join(mcpd, "agentparcel.py"), py_full, 0o755)
    put(os.path.join(mcpd, "README-mcp.txt"), files["README-mcp.txt"])
    put(os.path.join(mcpd, "Install-Python-for-AgentParcel.bat"), files["Install-Python-for-AgentParcel.bat"])
    if opts.pc_python and opts.pc_dir:
        pcd = os.path.join(DIST, "mcp-pc")
        os.makedirs(pcd)
        for fn in ("agentparcel_mcp.py", "agentparcel.py", "Install-Python-for-AgentParcel.bat"):
            shutil.copy2(os.path.join(mcpd, fn), os.path.join(pcd, fn))
        txt = render_mcp_readme(sub(read("README-mcp.txt")), opts.pc_python, opts.pc_dir.rstrip("\\") + "\\agentparcel_mcp.py",
                                opts.pc_root or opts.pc_dir, opts.pc_note.replace("\\n", "\n"))
        put(os.path.join(pcd, "README-mcp.txt"), txt.replace("\n", "\r\n"))

    zpath = os.path.join(DIST, "AgentParcel-mac-linux.zip")
    now = time.localtime()[:6]
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("AgentParcel/", now)
        zi.create_system = 3
        zi.external_attr = (0o40755 << 16) | 0x10
        z.writestr(zi, b"")
        for fn in sorted(os.listdir(ml)):
            mode = os.stat(os.path.join(ml, fn)).st_mode & 0o777
            zi = zipfile.ZipInfo("AgentParcel/" + fn, now)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3
            zi.external_attr = (0o100000 | mode) << 16
            with open(os.path.join(ml, fn), "rb") as f:
                z.writestr(zi, f.read())

    # ---- release packages: dist/release/AgentParcel-<ver>-<platform>.zip ----
    build_release(version, sub, files, ps_full, py_full, now)

    # sanity checks
    import py_compile
    py_compile.compile(os.path.join(ml, "agentparcel.py"), cfile=os.path.join(DIST, ".check.pyc"), doraise=True)
    os.remove(os.path.join(DIST, ".check.pyc"))
    back = json.loads(zlib.decompress(base64.b64decode(b64), -15))
    assert back["files"] == files and back["version"] == version
    print("AgentParcel %s built: payload %d KB (base64), ps1 %d KB, py %d KB" % (
        version, len(b64) // 1024, len(ps_full) // 1024, len(py_full) // 1024))
    for root, _, fns in os.walk(DIST):
        for fn in sorted(fns):
            print("  " + os.path.relpath(os.path.join(root, fn), DIST))
    return 0


if __name__ == "__main__":
    sys.exit(main())
