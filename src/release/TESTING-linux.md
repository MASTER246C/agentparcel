# AgentParcel @@ZS_VERSION@@ - Linux testing checklist (for Chris)

Tester: ________  Distro / desktop: ________  Python: ________  Date: ________

## Package
- [ ] `sha256sum -c SHA256SUMS.txt` (the linux line) is OK
- [ ] `unzip` gives `AgentParcel-@@ZS_VERSION@@-linux/`, and `ls -l` shows `x` on agentparcel.sh, agentparcel.py, install-deps.sh and mcp/*.py

## Setup
- [ ] `./install-deps.sh --check` reports python3 and Tk correctly
- [ ] On a machine without Tk, `./install-deps.sh` shows the command, asks y/N, and installs only after "y"

## App
- [ ] `./agentparcel.sh` opens the window, and its title shows @@ZS_VERSION@@
- [ ] Split in the window, then Rebuild in the window: verified
- [ ] CLI: `python3 agentparcel.py --no-gui --limit-mb 19.5 big.zip`, then `--join big_split --output-dir out`: verified, identical files
- [ ] With one part removed, rebuild names the missing part
- [ ] Without a display (e.g. over SSH) it falls back to text mode
- [ ] Optional: the `agentparcel.desktop` menu entry works after editing `Exec=`

## MCP
- [ ] `python3 mcp/agentparcel_mcp.py --list-tools` lists 8 tools (inspect, split_zip, split_any_file, split_files, verify, regenerate_parts, rebuild, make_apps_bundle)
- [ ] `python3 agentparcel.py --split-bytes` on a non-zip, then `python3 rebuild.py` in the parts folder, restores the exact file. `--verify` names a missing part. Stop in the window reports Cancelled
- [ ] `npx @modelcontextprotocol/inspector --cli python3 mcp/agentparcel_mcp.py --method tools/list` works (needs Node.js)
- [ ] With a snippet from `mcp/README-mcp.txt` added to Claude Code, Cursor or Codex, a split and rebuild round trip works

## Cross-platform
- [ ] Linux parts rebuild on Windows, and Windows parts rebuild on Linux
