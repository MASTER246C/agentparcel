# AgentParcel @@ZS_VERSION@@ - release notes

*Project site: https://agentparcel.net.*

AgentParcel is an independent project. It is not affiliated with, endorsed by, or derived from any other project named ZipSplitter, and it does not use any of that project's code. ZipSplitter was only our internal working name; all AgentParcel code was written from scratch for this project. Before release we researched that working name, found another existing project already using it, and switched to AgentParcel for the public release. Leftover `_zipsplitter_*` marker files and `ZIPSPLITTER_*` environment-variable fallbacks come from our own development builds, not from that other project. They remain only for backward compatibility.

| Package | Platform | Status |
|---|---|---|
| `AgentParcel-@@ZS_VERSION@@-windows.zip` | Windows 10/11 (PowerShell 5.1, included in Windows) | Zip split (unpack and include-apps both on) and byte verify/rebuild were run with PowerShell 7.6, which throws the same "Argument types do not match" error as Windows PowerShell 5.1. The WinForms window was not opened on Windows |
| `AgentParcel-@@ZS_VERSION@@-linux.zip` | Linux with Python 3.9+ (Tk optional) | unit tests for the 3.5.1 PowerShell fixes, presets, regenerate, zlib, AES-GCM, rebuild.py, and cross-checks between PowerShell and Python |
| `AgentParcel-@@ZS_VERSION@@-macos.zip` | macOS 11+ with Python 3.9+ | **community-tested/beta** (same Python program as Linux). Mac users: if you hit an issue or can help test, reach out via chriskalkowski.com. |

Check a download:  `sha256sum -c SHA256SUMS.txt` (Linux), `shasum -a 256 -c SHA256SUMS.txt` (macOS),
`Get-FileHash .\AgentParcel-@@ZS_VERSION@@-windows.zip` (Windows PowerShell).

## What's new
- **3.5.1: Windows zip split works again.** v3.4.0 and v3.5.0 failed with "Argument types do not match" and deleted the output. A `List[object]` must not be wrapped in `@()`.
- **3.5.1: byte parts verify.** The manifest was already correct. Rebuild no longer calls every part corrupt, and the log puts each part on its own line.
- **3.5.0: size presets.** Window menu and MCP `preset`: chatgpt-dot (19,000,000 bytes under 20 MB), chat-512 (500,000,000 under 512 MB), discord (24,000,000 under the free 25 MB cap; Nitro is higher), email (24,000,000 under a common 25 MB cap), github-release (1,900,000,000 under 2 GB), custom. Caps sit under the advertised limit. Limits can change.
- **3.5.0: re-send missing parts.** MCP `regenerate_parts`, and Resend in the window, rewrite only the missing or corrupt parts from the original file. Rebuild names any parts that are still needed.
- **3.5.0: optional zlib and AES-256-GCM.** Off by default. `rebuild.py` decompresses zlib parts with the standard library. Encrypted parts need AgentParcel plus `cryptography` (`pip install agentparcel[crypto]`). The password is not stored. `rebuild.py` will not decrypt and will not write a file.
- **3.5.0: pip package.** `pip install agentparcel` provides `agentparcel` and `agentparcel-mcp`. Not uploaded to PyPI in this release.
- **macOS is community-tested/beta.** Mac users: if you hit an issue or can help test, reach out via chriskalkowski.com.
- **3.4.0: split any file.** Byte-level split of any file type into numbered parts under a size cap, rebuilt to the exact original (SHA-256). Window checkbox, and MCP tool `split_any_file`. `rebuild` accepts zip part sets and byte-split sets.
- **3.4.0: verify.** Before rebuilding, check that every part is present and that each checksum matches the manifest. Missing and corrupt parts are named. Window button, and MCP tool `verify`.
- **3.4.0: rebuild without AgentParcel.** Every split folder includes `HOW-TO-REBUILD.txt` and a dependency-free `rebuild.py` (Python 3 standard library only). The text file includes a PowerShell equivalent for a byte split. `rebuild.py` reassembles a byte-split file and checks it. For zip parts it verifies part-file checksums; AgentParcel still reassembles the zip.
- **3.4.0: Stop.** The window stays responsive during split and rebuild. Stop cancels the job, deletes partial output from that run, and reports Cancelled. The MCP server honors client cancellation and does not leave a half-written output.
- 3.3.x parts and manifests still work. `_zipsplitter_*` marker files and `ZIPSPLITTER_*` fallbacks are unchanged.
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
- macOS package: community-tested/beta. Mac users: if you hit an issue or can help test, reach out via chriskalkowski.com.
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
