<p align="center"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/agentparcel-wordmark.png">
  <img alt="AgentParcel" src="assets/agentparcel-wordmark-black.png" width="520">
</picture></p>

# AgentParcel @@ZS_VERSION@@ for macOS

*Project site: https://agentparcel.net*

> **UNTESTED - needs testing.** This package has not been run on a real Mac yet. It is the same
> Python program as the tested Linux release, but the Finder/Gatekeeper steps, the Tk window
> and `install-python-macos.sh` are unverified. Please work through `TESTING-CHECKLIST.md` and
> report what happens.

Splits a big `.zip` into smaller standalone zips (19.5 MB each by default) and rebuilds the original
from them, checking it with SHA-256. Parts made on Windows, Mac or Linux rebuild on any of them.
Needs Python 3.9+ with Tk (the python.org installer includes Tk; 3.15 recommended).

## Contents
| File | What it is |
|---|---|
| `AgentParcel.command` | **start here**: double-click it in Finder |
| `agentparcel.py` | the program (window, text mode and command line) |
| `install-python-macos.sh` | gets Python 3.15 + Tk via Homebrew or the python.org pkg (checks the hash and signature, asks first) |
| `assets/` | AgentParcel icon (PNG 16-512 px, AgentParcel.icns) and wordmark (transparent and black background) |
| `mcp/` | MCP server for AI agents: `agentparcel_mcp.py`, `agentparcel.py`, `README-mcp.txt` |
| `README-mac-linux.txt`, `README-format.txt` | detailed manual and the part/manifest format |
| `TESTING-CHECKLIST.md`, `CHANGELOG.md`, `VERSION`, `LICENSE.txt` (AgentParcel License 1.0) | |

## Quick start
1. Double-click the zip in Finder to extract it, and move the folder to e.g. Documents.
2. In Terminal:
   ```sh
   cd ~/Documents/AgentParcel-@@ZS_VERSION@@-macos
   xattr -dr com.apple.quarantine .        # optional: avoids the "unidentified developer" prompts
   ./install-python-macos.sh --check       # or without --check to install Python 3.15
   ```
3. Double-click `AgentParcel.command`. The first time, macOS may block it: right-click > **Open** > **Open**.
   If it says "permission denied": `chmod +x AgentParcel.command agentparcel.py mcp/*.py`.

## Command line
```sh
python3 agentparcel.py --no-gui --limit-mb 19.5 ~/Downloads/big.zip
python3 agentparcel.py --join ~/Downloads/big_split --output-dir ~/Desktop
```

## MCP server (AI agents)
`mcp/agentparcel_mcp.py` gives Claude Desktop, Claude Code, Cursor and Codex CLI tools
(`split_zip`, `split_files`, `rebuild`, `inspect`, `make_apps_bundle`). Use the full python path:
`/usr/local/bin/python3` (python.org) or `/opt/homebrew/bin/python3` (Homebrew on Apple silicon).
Don't use `/usr/bin/python3`. Snippets are in `mcp/README-mcp.txt`.

## Troubleshooting
- **The window looks broken or blank**: you're on Apple's old Tk. Install Python from python.org
  (`./install-python-macos.sh --pkg`).
- **`xcrun: error` / a prompt to install developer tools**: that's Apple's `/usr/bin/python3` stub.
  Install Python as above.
- **"part NN is missing"**: put all `_partNN.zip` files in one folder.

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
ZipSplitter was our internal working name during development. Before release we researched it, found another existing project already using that name, and switched to AgentParcel for the public release. Leftover internal identifiers remain only for backward compatibility: the `_zipsplitter_*` marker files, and the `ZIPSPLITTER_*` environment-variable fallbacks (`ZIPSPLITTER_MCP_ROOTS` still works when `AGENTPARCEL_MCP_ROOTS` is unset). Parts made during development still rebuild, and those older builds still rebuild AgentParcel parts. The MCP server to configure is `agentparcel_mcp.py` (server name `agentparcel`).
