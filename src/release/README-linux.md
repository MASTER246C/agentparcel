<p align="center"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/agentparcel-wordmark.png">
  <img alt="AgentParcel" src="assets/agentparcel-wordmark-black.png" width="520">
</picture></p>

# AgentParcel @@ZS_VERSION@@ for Linux

*Formerly **ZipSplitter**. Project site: https://agentparcel.net*

Splits a big `.zip` into smaller standalone zips (19.5 MB each by default) and rebuilds the original
from them, checking it with SHA-256. Parts made on Windows, Mac or Linux rebuild on any of them.
Needs Python 3.9+ (3.15 recommended). The window needs Tk; without Tk it runs in text mode.

## Contents
| File | What it is |
|---|---|
| `agentparcel.sh` | **start here**: launcher (finds a suitable python3) |
| `agentparcel.py` | the program (window, text mode and command line; standard library only) |
| `install-deps.sh` | installs python3 + Tk with apt/dnf/yum/pacman/zypper (shows the command, asks before sudo) |
| `agentparcel.desktop` | optional menu entry (edit the `Exec=` path first) |
| `assets/` | AgentParcel icon (PNG 16-512 px) and wordmark (transparent and black background) |
| `mcp/` | MCP server for AI agents: `agentparcel_mcp.py`, `agentparcel.py`, `README-mcp.txt` |
| `README-mac-linux.txt`, `README-format.txt` | detailed manual and the part/manifest format |
| `TESTING-CHECKLIST.md`, `CHANGELOG.md`, `VERSION`, `LICENSE.txt` (AgentParcel License 1.0) | |

## Quick start
```sh
unzip AgentParcel-@@ZS_VERSION@@-linux.zip && cd AgentParcel-@@ZS_VERSION@@-linux
./install-deps.sh --check      # or ./install-deps.sh to install python3 / python3-tk
./agentparcel.sh               # opens the window
```
If a file isn't executable (e.g. it was copied through Windows): `chmod +x *.sh *.py mcp/*.py`.

## Command line
```sh
python3 agentparcel.py --no-gui --limit-mb 19.5 /path/big.zip          # -> /path/big_split/
python3 agentparcel.py --join /path/big_split --output-dir /tmp/out     # rebuild + verify
```
Other options: `--output-dir DIR`, `--no-unpack-inner`, `--include-apps`, `--no-include-apps`, `--version`.

## MCP server (AI agents)
`mcp/agentparcel_mcp.py` gives Claude Code, Cursor and Codex CLI tools (`split_zip`,
`split_files`, `rebuild`, `inspect`, `make_apps_bundle`) for files that are over an upload limit.
Check it with `python3 mcp/agentparcel_mcp.py --list-tools`, then paste a snippet from
`mcp/README-mcp.txt` with your real paths. (Claude Desktop has no official Linux build.)

## Troubleshooting
- **No window, text prompt instead**: Tk or a display is missing. Run `./install-deps.sh`, or
  use the command line.
- **"part NN is missing"**: put all `_partNN.zip` files in one folder.
- **The upload limit is in decimal MB**: use `--limit-mb 19` or lower.
- **Archives over 4 GB**: use Python 3.11 or newer.

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

## Coming from ZipSplitter?
AgentParcel is the new name of ZipSplitter. Parts, manifests and apps bundles made by any ZipSplitter
version rebuild with AgentParcel, and ZipSplitter 3.x can rebuild parts made by AgentParcel (the internal
`_zipsplitter_*` label files are kept for that). MCP: the server is now `agentparcel_mcp.py` and the
server name in the snippets is `agentparcel`. `AGENTPARCEL_MCP_ROOTS` replaces `ZIPSPLITTER_MCP_ROOTS`,
but the old variable still works. Update the path in your agent config.
