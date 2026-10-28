# AgentParcel changelog

Project site: https://agentparcel.net.

Entries before 3.3.1 use the internal working name. See [About the name](README.md#about-the-name).

## 3.5.1 - 2026-10-26
- **Windows zip split.** Splitting a zip failed with "Argument types do not match" and the output folder was removed, so it looked like no parts were written. The finished part list was passed through `@()`. Windows PowerShell 5.1 and PowerShell 7 throw that error for a `List[object]` made with `New-Object`. Unpack-inner and include-apps both stay on in the fix. 3.3.1 was not affected.
- **Byte-part checksums.** Verify and rebuild reported every byte part corrupt right after a split. The manifest hashes were correct. The reader wrapped the parts array, so it never saw each part's size or SHA-256. PowerShell and Python accept each other's plain byte sets, and `rebuild.py` rebuilds a set written by PowerShell.
- **Error log.** Each missing or corrupt part is on its own line in the Windows log.

## 3.5.0 - 2026-10-26
- **Size presets.** The window has a size-preset menu, and the MCP split tools take `preset`: `chatgpt-dot` (19,000,000 bytes, under a 20,000,000 byte ChatGPT Dot cap), `chat-512` (500,000,000 under 512,000,000; products differ), `discord` (24,000,000 under the free 25 MB cap; Nitro is higher and is not this preset), `email` (24,000,000 under a common 25 MB attachment cap), `github-release` (1,900,000,000 under GitHub's 2 GB release-asset limit), and `custom` (the size you type; default remains 19.5 MiB). Each cap sits under the advertised limit. Those limits can change.
- **Re-send missing parts.** `regenerate_parts` (MCP) and Resend in the window rewrite only the parts verify reports as missing or corrupt, using the original file. Parts that already match are left as they are. Rebuild says which parts are still needed.
- **Optional zlib and AES-256-GCM.** Off by default. Byte parts can be compressed with zlib (one part at a time, standard library). `rebuild.py` decompresses those with the standard library. Optional password encryption uses AES-256-GCM and scrypt from the `cryptography` package (`pip install agentparcel[crypto]`). The manifest records the algorithm and salt, never the password. `rebuild.py` refuses an encrypted set and does not write a file.
- **PyPI layout.** `pyproject.toml` provides the `agentparcel` and `agentparcel-mcp` commands. The package is ready to upload; this release does not publish it.
- **License line.** The project-site line now says ZipSplitter was only an internal working name, and that AgentParcel is not affiliated with or derived from any other project of that name. The license terms are unchanged.
- **macOS.** Labeled community-tested/beta. Mac users: if you hit an issue or can help test, reach out via chriskalkowski.com.
- 3.3.x and 3.4.0 part sets still verify and rebuild. Plain byte parts are unchanged when compression and encryption are left off.

## 3.4.0 - 2026-10-26
- **Split any file.** A file of any type (PDF, video, dataset, CAD, and so on) can be cut into numbered raw parts under a size cap and rebuilt to the exact original bytes. The whole file's SHA-256 is checked. The window has "Byte-split this file"; a file that is not a zip is byte-split automatically. The MCP tool is `split_any_file`. `rebuild` handles both zip part sets and byte-split sets.
- **Verify.** Before rebuilding, check that every part is present and that each part's checksum matches the manifest. Missing parts and corrupt parts are named separately. The window has a Verify button. The MCP tool is `verify`.
- **Agent-readable rebuild kit.** Every split folder includes `HOW-TO-REBUILD.txt` (plain text, for a person or a receiving agent, including a PowerShell equivalent for a byte split) and `rebuild.py` (Python 3 standard library only). `rebuild.py` checks checksums and reassembles a byte-split file. For zip parts it checks each part file against `_agentparcel_zipset.json` and tells you to use AgentParcel to reassemble the zip, because that manifest lives inside the parts.
- **Stop.** The window has a Stop button. Split, package, and rebuild run so the window stays responsive. Stop cancels the job, deletes partial output from that run, and reports Cancelled. The MCP server honors a client `notifications/cancelled` and does not leave a half-written output.
- Zip parts are unchanged: `_zipsplitter_part.json` and `_zipsplitter_manifest.json` are still the format, and `ZIPSPLITTER_*` environment-variable fallbacks still work. A 3.3.x set still rebuilds. New sidecars (`_agentparcel_bytes.json`, `_agentparcel_zipset.json`) are ignored by 3.3.x readers.

## 3.3.1 - 2026-10-25
- **Public release name is AgentParcel.** See [About the name](README.md#about-the-name).
  - Files: AgentParcel.ps1, AgentParcel.bat, agentparcel.py, agentparcel_mcp.py, AgentParcel.command,
    agentparcel.sh, agentparcel.desktop, Install-Python-for-AgentParcel.bat.
  - Release zips are AgentParcel-<ver>-<platform>.zip, and the apps bundle is AgentParcel-apps.zip.
  - The MCP server name is `agentparcel`. The env vars are AGENTPARCEL_MCP_ROOTS / AGENTPARCEL_PY.
    ZIPSPLITTER_MCP_ROOTS / ZIPSPLITTER_PY remain as fallbacks from our own development builds, for backward compatibility only.
  - The license for the public release is AgentParcel License 1.0, with a refined Equal Tier Availability clause: it covers
    every tier with the Prerequisite Capability (e.g. MCP/tool access), and usage limits may be no stricter
    than for comparable tools.
- The part format is unchanged. The `_zipsplitter_*` label files are kept for backward compatibility with our own development builds. Parts from those builds still rebuild, and those builds still rebuild AgentParcel parts. AgentParcel ignores a development `ZipSplitter-apps.zip`, and those older builds ignore `AgentParcel-apps.zip`. See [About the name](README.md#about-the-name).
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
