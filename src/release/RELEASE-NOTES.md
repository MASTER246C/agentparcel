# AgentParcel @@ZS_VERSION@@ - release notes

*Project site: https://agentparcel.net.*

AgentParcel is an independent project. It is not affiliated with, endorsed by, or derived from any other project named ZipSplitter, and it does not use any of that project's code. ZipSplitter was only our internal working name; all AgentParcel code was written from scratch for this project. Before release we researched that working name, found another existing project already using it, and switched to AgentParcel for the public release. Leftover `_zipsplitter_*` marker files and `ZIPSPLITTER_*` environment-variable fallbacks come from our own development builds, not from that other project. They remain only for backward compatibility.

| Package | Platform | Status |
|---|---|---|
| `AgentParcel-@@ZS_VERSION@@-windows.zip` | Windows 10/11 (PowerShell 5.1, included in Windows) | tested on the build box (pwsh) and parse-checked on Windows PowerShell 5.1 |
| `AgentParcel-@@ZS_VERSION@@-linux.zip` | Linux with Python 3.9+ (Tk optional) | tested (CLI, GUI on a headless X server, MCP) |
| `AgentParcel-@@ZS_VERSION@@-macos.zip` | macOS 11+ with Python 3.9+ | **UNTESTED - needs testing on a real Mac** (static checks and a Python run on Linux only) |

Check a download:  `sha256sum -c SHA256SUMS.txt` (Linux), `shasum -a 256 -c SHA256SUMS.txt` (macOS),
`Get-FileHash .\AgentParcel-@@ZS_VERSION@@-windows.zip` (Windows PowerShell).

## What's new
- **3.3.1: the public name is AgentParcel.** ZipSplitter was only our internal working name. AgentParcel is not affiliated with, endorsed by, or derived from any other project named ZipSplitter, and it does not use any of that project's code. All AgentParcel code was written from scratch for this project. New file names: AgentParcel.ps1/.bat, agentparcel.py,
  agentparcel_mcp.py, AgentParcel.command, agentparcel.sh, agentparcel.desktop, Install-Python-for-AgentParcel.bat,
  AgentParcel-apps.zip. MCP server name `agentparcel`, env var `AGENTPARCEL_MCP_ROOTS` (`ZIPSPLITTER_MCP_ROOTS` is still accepted, only as a compatibility fallback from our own development builds).
- Parts from our own development builds still rebuild, and those builds still rebuild AgentParcel parts. AgentParcel ignores `ZipSplitter-apps.zip`; those older builds ignore `AgentParcel-apps.zip`. The on-disk `_zipsplitter_*` marker file names are unchanged on purpose, for backward compatibility with those builds only. They do not come from any other project named ZipSplitter.
- 3.3.1: AgentParcel-apps.zip (the bundle sent with the parts) now includes LICENSE.txt.
- One package per platform, each with an `mcp/` folder (an MCP server for AI agents, with config
  snippets for Claude Desktop, Claude Code, Cursor and Codex CLI that fit that platform).
- Python helpers: `Install-Python-for-AgentParcel.bat` (Windows, Python 3.15, per user, no admin),
  `install-deps.sh` (Linux), `install-python-macos.sh` (macOS, untested).
- Python 3.15 (3.15.1, released 2026-10-21) is the recommended Python. 3.9+ still works.
- The part format has not changed. Parts made with 3.x on any platform rebuild on any other.

## Known limits / open items
- Our development builds that still used the ZipSplitter working name only recognise `AgentParcel-apps.zip` by its marker file. If someone picks the bundle
  plus only *some* parts by hand in one of those older builds, it can wrongly report missing parts. Choosing the folder,
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
