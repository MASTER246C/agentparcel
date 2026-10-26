# AgentParcel @@ZS_VERSION@@ - macOS testing checklist (for a Mac tester)

**This package has never been run on a Mac. Please note everything unexpected, with screenshots.**

Tester: ________  Mac model / chip: ________  macOS version: ________  Date: ________

## Package
- [ ] `shasum -a 256 -c SHA256SUMS.txt` (the macos line) is OK
- [ ] Double-clicking the zip in Finder gives `AgentParcel-@@ZS_VERSION@@-macos/`
- [ ] `ls -l` shows the executable bit on AgentParcel.command, agentparcel.py, install-python-macos.sh and mcp/*.py (Finder's Archive Utility should keep it; note if it doesn't)

## Python
- [ ] `./install-python-macos.sh --check`: what does it report? (paste it)
- [ ] Without Python 3.9+: try the Homebrew path (if brew is installed) and the `--pkg` path. Did the SHA-256 and signature checks pass, and did the pkg installer open?
- [ ] Afterwards `--check` shows Python 3.15.x and Tk OK

## App
- [ ] Double-click `AgentParcel.command`: what did Gatekeeper say? Did right-click > Open work? (note exact wording)
- [ ] The window opens, looks right in light and dark mode, and its title shows @@ZS_VERSION@@
- [ ] Split a >40 MB zip, then Rebuild: verified, and the rebuilt zip opens in Finder
- [ ] With one part removed, rebuild names the missing part
- [ ] Dropping files works (or note that it doesn't)
- [ ] CLI split and `--join` work in Terminal

## MCP
- [ ] `/usr/local/bin/python3 mcp/agentparcel_mcp.py --list-tools` (or the Homebrew path) lists 5 tools
- [ ] Claude Desktop config snippet from `mcp/README-mcp.txt`: after a restart, the agentparcel tools appear and a split works
- [ ] Optional: Claude Code / Cursor / Codex snippet

## Cross-platform
- [ ] Parts made on the Mac rebuild on Windows or Linux, and the other way round
