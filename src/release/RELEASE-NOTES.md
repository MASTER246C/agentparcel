# AgentParcel @@ZS_VERSION@@ - release notes

*AgentParcel is the new name of ZipSplitter. Project site: https://agentparcel.net*

| Package | Platform | Status |
|---|---|---|
| `AgentParcel-@@ZS_VERSION@@-windows.zip` | Windows 10/11 (PowerShell 5.1, included in Windows) | tested on the build box (pwsh) and parse-checked on Windows PowerShell 5.1 |
| `AgentParcel-@@ZS_VERSION@@-linux.zip` | Linux with Python 3.9+ (Tk optional) | tested (CLI, GUI on a headless X server, MCP) |
| `AgentParcel-@@ZS_VERSION@@-macos.zip` | macOS 11+ with Python 3.9+ | **UNTESTED - needs testing on a real Mac** (static checks and a Python run on Linux only) |

Check a download:  `sha256sum -c SHA256SUMS.txt` (Linux), `shasum -a 256 -c SHA256SUMS.txt` (macOS),
`Get-FileHash .\AgentParcel-@@ZS_VERSION@@-windows.zip` (Windows PowerShell).

## What's new
- **3.3.1: renamed ZipSplitter -> AgentParcel.** New file names: AgentParcel.ps1/.bat, agentparcel.py,
  agentparcel_mcp.py, AgentParcel.command, agentparcel.sh, agentparcel.desktop, Install-Python-for-AgentParcel.bat,
  AgentParcel-apps.zip. MCP server name `agentparcel`, env var `AGENTPARCEL_MCP_ROOTS` (old `ZIPSPLITTER_MCP_ROOTS` still accepted).
- Fully compatible both ways: AgentParcel rebuilds every ZipSplitter part set and ignores ZipSplitter-apps.zip;
  ZipSplitter 3.x rebuilds AgentParcel parts and ignores AgentParcel-apps.zip (the on-disk `_zipsplitter_*` label
  file names are unchanged on purpose).
- 3.3.1: AgentParcel-apps.zip (the bundle sent with the parts) now includes LICENSE.txt.
- One package per platform, each with an `mcp/` folder (an MCP server for AI agents, with config
  snippets for Claude Desktop, Claude Code, Cursor and Codex CLI that fit that platform).
- Python helpers: `Install-Python-for-AgentParcel.bat` (Windows, Python 3.15, per user, no admin),
  `install-deps.sh` (Linux), `install-python-macos.sh` (macOS, untested).
- Python 3.15 (3.15.1, released 2026-10-21) is the recommended Python. 3.9+ still works.
- The part format has not changed. Parts made with 3.x on any platform rebuild on any other.

## Known limits / open items
- Old ZipSplitter 3.x only recognises `AgentParcel-apps.zip` by its marker file. If someone picks the bundle
  plus only *some* parts by hand in an old ZipSplitter, it can wrongly report missing parts. Choosing the folder,
  any single part, or all parts works. AgentParcel itself recognises both bundle names.
- macOS package: not yet run on a Mac (Gatekeeper prompts, the Tk look and the pkg install path are unverified).
- The Windows Python installer helper was syntax-checked but not run on a real PC.
- winget has no `Python.Python.3.15` package yet (its submission is still open as of
  2026-10-25), so the helper falls back to the python.org installer.

## License
AgentParcel License 1.0 (see `LICENSE.txt`). This is **source-available**, not OSI-approved open source,
because of its Equal Tier Availability condition. In plain English:
- You may use, copy, modify, share and sell it, including commercially. Keep the license and copyright notice.
- You may market it as an included feature.
- If a product with several plans or tiers includes it, every tier that can use that kind of tool must get it on
  equal terms, free tier included. For the MCP server that means every tier with MCP/tool access; for the apps, every
  tier that can run local apps or scripts. It can't be reserved for a higher or paid tier, and its usage limits can't
  be stricter than those for comparable tools in that tier. A tier with no such access at all doesn't have to get it.
- No warranty.
- Licensing questions and permissions: https://chriskalkowski.com
- Project site: https://agentparcel.net

Full history: CHANGELOG.md inside each package.
