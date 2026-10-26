AgentParcel MCP server  (version @@ZS_VERSION@@)  -  https://agentparcel.net
============================================================================
Lets AI agents (Claude Desktop, Claude Code, Cursor, Codex CLI, ...) that hit a file-upload
size limit split big zips / files / folders into standalone .zip parts under the limit, and
rebuild the original from the parts - by calling tools instead of writing their own scripts.
The parts are the same format as the AgentParcel apps for Windows, Mac and Linux.

Files (keep them together in one folder):
  agentparcel_mcp.py   the MCP server (stdio, no extra packages needed)
  agentparcel.py       the AgentParcel engine it uses
Needs Python 3.9 or newer (3.15 recommended; 3.11+ for archives over 4 GB).
Windows without Python: Install-Python-for-AgentParcel.bat installs Python 3.15 for your user
(no admin), smoke-tests this server and writes MCP-config-snippets.txt with the real paths.

TOOLS
  inspect            read-only: sizes, entry count, estimated parts; for parts: set id, part n of N,
                     missing parts. Works on a .zip, a part, a folder or any file.
  split_zip          split a .zip into <name>_part01.zip, _part02.zip ... each <= max_mb.
  split_files        zip files and/or folders (logs, videos, datasets, projects) and split in one step.
  rebuild            rebuild the original from a folder / one part / a list of parts (SHA-256 verified;
                     names any missing part). extract=true also unpacks it into a folder.
  make_apps_bundle   write AgentParcel-apps.zip (the apps for a human recipient).
  Sizes: max_mb is MiB (19.5 = 20,447,232 bytes). For an exact limit pass max_bytes
  (e.g. a "20 MB" upload limit that means 20,000,000 bytes -> max_bytes 20000000, or max_mb 19).
  All paths must be absolute. Nothing is ever overwritten or deleted (new names get " (2)").
  Agents get the apps bundle only if they ask (include_apps=true).

OPTIONAL SANDBOX
  Set AGENTPARCEL_MCP_ROOTS to the folders the server may read and write (separate several with
  ";" on Windows, ":" on Mac/Linux). Paths outside are refused. The snippets below allow your
  user folder; remove the "env" part to allow everything. The compatibility fallback
  ZIPSPLITTER_MCP_ROOTS still works when AGENTPARCEL_MCP_ROOTS is not set. It remains
  only for backward compatibility (ZipSplitter was the internal working name).

LONG JOBS
  Big splits can take minutes. The server sends progress notifications when the client asks, but
  some clients still stop waiting after a fixed time:
    Codex CLI: tool_timeout_sec (default 60) - the snippet below sets 1800.
    Claude Code: set the environment variable MCP_TOOL_TIMEOUT=1800000 (milliseconds) before starting it.

@@IF-WIN@@
-------------------------------------------------------------------------------------------
WINDOWS  (python path: @@PY@@)
-------------------------------------------------------------------------------------------
@@PYNOTE@@
Claude Desktop - %APPDATA%\Claude\claude_desktop_config.json  (Settings > Developer > Edit Config),
merge into "mcpServers", then restart Claude Desktop:
{
  "mcpServers": {
    "agentparcel": {
      "command": "@@PYJ@@",
      "args": ["@@MCPJ@@"],
      "env": { "AGENTPARCEL_MCP_ROOTS": "@@ROOTJ@@" }
    }
  }
}

Claude Code (run once in a terminal; --scope user = available in every project):
  claude mcp add agentparcel --scope user --env AGENTPARCEL_MCP_ROOTS="@@ROOT@@" -- "@@PY@@" "@@MCP@@"
  check:  claude mcp list

Cursor - %USERPROFILE%\.cursor\mcp.json (all projects) or <project>\.cursor\mcp.json:
{
  "mcpServers": {
    "agentparcel": {
      "command": "@@PYJ@@",
      "args": ["@@MCPJ@@"],
      "env": { "AGENTPARCEL_MCP_ROOTS": "@@ROOTJ@@" }
    }
  }
}

Codex CLI - %USERPROFILE%\.codex\config.toml:
[mcp_servers.agentparcel]
command = '@@PY@@'
args = ['@@MCP@@']
env = { AGENTPARCEL_MCP_ROOTS = '@@ROOT@@' }
startup_timeout_sec = 20
tool_timeout_sec = 1800

@@END-WIN@@
@@IF-UNIX@@
-------------------------------------------------------------------------------------------
@@UHEAD@@
-------------------------------------------------------------------------------------------
@@UFIND@@
@@UCD@@
Cursor: ~/.cursor/mcp.json
{
  "mcpServers": {
    "agentparcel": {
      "command": "@@UPY@@",
      "args": ["@@UMCP@@"],
      "env": { "AGENTPARCEL_MCP_ROOTS": "@@UROOT@@" }
    }
  }
}
Claude Code:
  claude mcp add agentparcel --scope user --env AGENTPARCEL_MCP_ROOTS="$HOME" -- @@UPY@@ "@@UMCPH@@"
Codex CLI (~/.codex/config.toml):
[mcp_servers.agentparcel]
command = "@@UPY@@"
args = ["@@UMCP@@"]
env = { AGENTPARCEL_MCP_ROOTS = "@@UROOT@@" }
startup_timeout_sec = 20
tool_timeout_sec = 1800

@@END-UNIX@@
-------------------------------------------------------------------------------------------
TRY IT BY HAND
  python3 agentparcel_mcp.py --version       (prints the version on stderr)
  python3 agentparcel_mcp.py --list-tools    (prints the tool list as JSON)
  Official inspector (needs Node.js):
    npx @modelcontextprotocol/inspector python3 agentparcel_mcp.py
The server only talks MCP on stdin/stdout; its log goes to stderr (your client's MCP log).
