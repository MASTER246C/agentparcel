# AgentParcel changelog

Project site: https://agentparcel.net.

ZipSplitter was our internal working name during development. Before the public release we researched it, found another existing project already using that name, and switched to AgentParcel.

AgentParcel is an independent project. It is not affiliated with, endorsed by, or derived from any other project named ZipSplitter, and it does not use any of that project's code. ZipSplitter was only our internal working name; all AgentParcel code was written from scratch for this project.

Entries before 3.3.1 still use that working name for the files from our own development builds. The `_zipsplitter_*` marker files and the `ZIPSPLITTER_*` environment-variable fallbacks come from those builds, not from any other project named ZipSplitter. They remain only for backward compatibility.

## 3.3.1 - 2026-10-25
- **Public release name is AgentParcel.** ZipSplitter was only our internal working name. Before release we researched it, found another existing project already using that name, and switched. AgentParcel is not affiliated with, endorsed by, or derived from that project, and it does not use any of that project's code. All AgentParcel code was written from scratch for this project.
  - Files: AgentParcel.ps1, AgentParcel.bat, agentparcel.py, agentparcel_mcp.py, AgentParcel.command,
    agentparcel.sh, agentparcel.desktop, Install-Python-for-AgentParcel.bat.
  - Release zips are AgentParcel-<ver>-<platform>.zip, and the apps bundle is AgentParcel-apps.zip.
  - The MCP server name is `agentparcel`. The env vars are AGENTPARCEL_MCP_ROOTS / AGENTPARCEL_PY.
    ZIPSPLITTER_MCP_ROOTS / ZIPSPLITTER_PY remain as fallbacks from our own development builds, for backward compatibility only. They do not come from any other project named ZipSplitter.
  - The license for the public release is AgentParcel License 1.0, with a refined Equal Tier Availability clause: it covers
    every tier with the Prerequisite Capability (e.g. MCP/tool access), and usage limits may be no stricter
    than for comparable tools.
- The part format is unchanged. The `_zipsplitter_*` label files are kept only for backward compatibility with our own development builds, not with any other project named ZipSplitter. Parts from those builds still rebuild, and those builds still rebuild AgentParcel parts. AgentParcel ignores a development `ZipSplitter-apps.zip`, and those older builds ignore `AgentParcel-apps.zip`.
- AgentParcel-apps.zip (the bundle written next to the parts) now includes LICENSE.txt, from both the
  Windows and the Mac/Linux program.
- New neon AgentParcel icon and wordmark.
  - The window icon is on Windows (WinForms) and in the Tk window (Mac/Linux). It is embedded, so a single
    file still works.
  - The Linux .desktop entry uses the icon.
  - Each release has an `assets/` folder (PNG 16-512 px, .ico, .icns, wordmark).
  - The apps bundle carries small icons: Windows/AgentParcel.ico and linux/agentparcel.png.

## 3.3.0 - 2026-10-25
- Release packages, one per platform: `ZipSplitter-3.3.0-windows.zip`, `-linux.zip`, `-macos.zip`,
  each with the app, its launcher(s), an `mcp/` folder, a Python helper, README.md,
  TESTING-CHECKLIST.md and VERSION. `SHA256SUMS.txt` lists the zip checksums.
- Windows: new `Install-Python-for-ZipSplitter.bat`. It installs Python 3.15 for your user only
  (winget first, then the official python.org installer after checking its SHA-256 and its
  Python Software Foundation signature), smoke-tests the MCP server and writes
  `MCP-config-snippets.txt` with your real paths. It never edits agent configs.
- Linux: new `install-deps.sh` (python3 + Tk via apt/dnf/yum/pacman/zypper; asks before sudo).
- macOS: new `install-python-macos.sh` (Homebrew or the python.org 3.15.1 pkg, hash and
  signature checked). **The macOS release is untested on a real Mac.**
- Launchers prefer python3.15 / 3.14 when installed. The README-mcp snippets use Python 3.15 paths.
- License: ZipSplitter License 1.0 (MIT-style, source-available, with an Equal Tier
  Availability condition). See LICENSE.txt.
- Tested with Python 3.15.1, 3.13 and 3.9. The part format has not changed, so parts from
  3.x still rebuild.

## 3.2.0
- MCP server `zipsplitter_mcp.py` (stdio, standard library only). Tools: inspect, split_zip,
  split_files, rebuild, make_apps_bundle. Supports progress, cancel and the
  ZIPSPLITTER_MCP_ROOTS sandbox.
- The apps bundle has an `mcp/` folder.

## 3.1.0
- Windows window rebuilt (DPI-aware, resizable layout) with a layout self-test; Tk polish.
- "Include ZipSplitter apps" option: writes `ZipSplitter-apps.zip` next to the parts, so the
  receiver gets the Windows, Mac and Linux programs.

## 3.0.0 and earlier
- Split a zip into standalone parts of at most 19.5 MB (adjustable), unpacking zips found inside it.
- Rebuild the original from the parts using a manifest with SHA-256 checks. Missing parts are named.
- Python version for macOS and Linux, compatible both ways with the Windows version.
