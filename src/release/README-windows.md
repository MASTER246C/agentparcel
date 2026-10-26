<p align="center"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/agentparcel-wordmark.png">
  <img alt="AgentParcel" src="assets/agentparcel-wordmark-black.png" width="520">
</picture></p>

# AgentParcel @@ZS_VERSION@@ for Windows

*Project site: https://agentparcel.net*

Splits a big `.zip` into smaller standalone zips (19.5 MB each by default) and rebuilds the original
from them, checking it with SHA-256. It can also byte-split any file (PDF, video, dataset, and so on)
into numbered parts and rebuild the exact original. Parts made on Windows, Mac or Linux rebuild on any of them.
It needs nothing beyond Windows 10/11 and the Windows PowerShell 5.1 that comes with it.
Python is only needed for the optional MCP server.

## Contents
| File | What it is |
|---|---|
| `AgentParcel.bat` | **start here**: double-click it, or drag a .zip / the parts onto it |
| `AgentParcel.ps1` | the program (window + command line) |
| `Install-Python-for-AgentParcel.bat` | installs Python 3.15 for the MCP server (per user, no admin) |
| `assets\` | AgentParcel icon (AgentParcel.ico, PNG 16-512 px) and wordmark (transparent and black background) |
| `mcp\` | MCP server for AI agents: `agentparcel_mcp.py`, `agentparcel.py`, `README-mcp.txt` |
| `README-format.txt` | detailed manual and the part/manifest format |
| `TESTING-CHECKLIST.md`, `CHANGELOG.md`, `VERSION`, `LICENSE.txt` (AgentParcel License 1.0) | |

## Quick start (window)
1. Extract the whole zip: right-click > **Extract All...**. Don't run it from inside the zip.
2. Double-click `AgentParcel.bat`.
3. **Split**: choose a .zip, set the size limit and click Split. The parts go to `<name>_split\`.
   A file that is not a zip, or "Byte-split this file", writes raw numbered parts of that file.
   Keep "Include AgentParcel apps" ticked if the receiver needs the program too.
   Every split folder also gets `HOW-TO-REBUILD.txt` and `rebuild.py`.
4. **Verify** checks that every part is present and that each checksum matches, and names anything missing or corrupt.
5. **Rebuild**: choose the parts folder (or any one part) and click Rebuild.
6. **Stop** cancels a split or rebuild, deletes the partial output from that run, and reports Cancelled.

If Windows shows "Windows protected your PC", click **More info > Run anyway**. The files are
plain text scripts.

## Command line
```bat
powershell -ExecutionPolicy Bypass -File AgentParcel.ps1 -NoGui -LimitMB 19.5 "C:\path\big.zip"
powershell -ExecutionPolicy Bypass -File AgentParcel.ps1 -NoGui -SplitBytes "C:\path\movie.mp4"
powershell -ExecutionPolicy Bypass -File AgentParcel.ps1 -Verify "C:\path\big_split"
powershell -ExecutionPolicy Bypass -File AgentParcel.ps1 -Join "C:\path\big_split" -OutputDir "C:\out"
```
Other options: `-OutputDir DIR`, `-NoUnpackInner`, `-IncludeApps`, `-NoIncludeApps`.

## MCP server (AI agents)
Agents such as Claude Desktop, Claude Code, Cursor and Codex CLI can call the server's tools
(`inspect`, `split_zip`, `split_any_file`, `split_files`, `verify`, `rebuild`, `make_apps_bundle`) when a file is over an
upload limit.
1. Double-click `Install-Python-for-AgentParcel.bat`. It:
   - looks for Python 3.15 and ignores the Microsoft Store `python.exe` shortcut;
   - tries winget, then the official python.org installer (checks its SHA-256 and its
     Python Software Foundation signature, then installs it for your user only);
   - runs a smoke test of the server;
   - prints config snippets with your real paths and saves them to `MCP-config-snippets.txt`.
2. Paste the snippet for your app (it edits no config itself) and restart that app.
   See `mcp\README-mcp.txt` for details, timeouts for long jobs and the optional sandbox.

## Troubleshooting
- **The window doesn't open / closes at once**: run
  `powershell -ExecutionPolicy Bypass -File AgentParcel.ps1` in a terminal to see the error.
- **"part NN is missing"**: copy every `_partNN.zip` into one folder. The message names the missing part.
- **The upload limit is in decimal MB** (e.g. 20,000,000 bytes): use a limit of 19 or lower.
- **`python` opens the Microsoft Store**: that's the Store shortcut, not Python. Run the installer
  bat, or use the full `python.exe` path from `MCP-config-snippets.txt`.
- **The installer bat fails**: read the `ERROR:` line. The python.org installer's log is in
  `%TEMP%\python-3.15.1-install.log`.

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

## Contact
Project site: https://agentparcel.net
Licensing questions and permissions: https://chriskalkowski.com

## About the name
ZipSplitter was our internal working name during development. Before release we researched it, found another existing project already using that name, and switched to AgentParcel for the public release.

AgentParcel is an independent project. It is not affiliated with, endorsed by, or derived from any other project named ZipSplitter, and it does not use any of that project's code. ZipSplitter was only our internal working name; all AgentParcel code was written from scratch for this project.

Leftover `_zipsplitter_*` marker files and `ZIPSPLITTER_*` environment-variable fallbacks come from our own development builds, not from that other project. They remain only for backward compatibility (`ZIPSPLITTER_MCP_ROOTS` still works when `AGENTPARCEL_MCP_ROOTS` is unset). Parts from those builds still rebuild, and those builds still rebuild AgentParcel parts. The MCP server to configure is `agentparcel_mcp.py` (server name `agentparcel`).
