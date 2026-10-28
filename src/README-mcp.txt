AgentParcel MCP server  (version @@ZS_VERSION@@)  -  https://agentparcel.net
============================================================================
Lets AI agents (Claude Desktop, Claude Code, Cursor, Codex CLI, ...) that hit a file-upload
size limit split big zips / files / folders into standalone .zip parts under the limit, and
rebuild the original from the parts - by calling tools instead of writing their own scripts.
The parts are the same format as the AgentParcel apps for Windows, Mac and Linux.

Files (keep them together in one folder):
  agentparcel_mcp.py   the MCP server (stdio, no extra packages needed)
  agentparcel.py       the AgentParcel engine it uses
Needs Python 3.9 or newer. Python 3.11+ recommended (needed for >4 GB archives).
Windows without Python: Install-Python-for-AgentParcel.bat installs Python 3.15 for your user
(no admin), smoke-tests this server and writes MCP-config-snippets.txt with the real paths.

TOOLS
  inspect            read-only: sizes, entry count, estimated parts; for parts: set id, part n of N,
                     missing parts. Works on a .zip, a part, a folder or any file.
  split_zip          split a .zip into <name>_part01.zip, _part02.zip ... each <= max_mb.
  split_any_file     byte-split ANY one file into raw numbered parts (exact original, SHA-256).
                     The folder also gets HOW-TO-REBUILD.txt and rebuild.py (Python 3 stdlib only).
  split_files        zip files and/or folders (logs, videos, datasets, projects) and split in one step.
  verify             read-only: every part present, each checksum matches the manifest. Names the
                     missing parts and the corrupt parts. Writes nothing.
  regenerate_parts   rewrite only the missing or corrupt parts from the original file, so those
                     parts can be uploaded again. Leaves parts that already match untouched.
  rebuild            rebuild a zip part set OR a byte-split set from a folder / one part / a list
                     (SHA-256 verified; names any missing or corrupt part, and which are still
                     needed). extract=true unpacks a rebuilt zip into a folder.
  make_apps_bundle   write AgentParcel-apps.zip (the apps for a human recipient).
  Sizes: max_mb is MiB (19.5 = 20,447,232 bytes). For an exact limit pass max_bytes
  (e.g. a "20 MB" upload limit that means 20,000,000 bytes -> max_bytes 20000000, or max_mb 19).
  Or pass preset: chatgpt-dot (19000000 bytes), chat-512 (500000000), discord (24000000;
  Nitro is higher and is not this preset), email (24000000), github-release (1900000000).
  Each cap is under the advertised limit. Limits can change. A named preset sets the size;
  do not also pass max_bytes.
  split_any_file compress=true uses zlib (rebuild.py undoes it, stdlib only).
  password encrypts byte parts with AES-256-GCM (pip install agentparcel[crypto]).
  The password is never stored. rebuild.py cannot decrypt an encrypted set.
  All paths must be absolute. Nothing is ever overwritten or deleted (new names get " (2)").
  Agents get the apps bundle only if they ask (include_apps=true).

OPTIONAL SANDBOX
  Set AGENTPARCEL_MCP_ROOTS to the folders the server may read and write (separate several with
  ";" on Windows, ":" on Mac/Linux). Paths outside are refused. The snippets below allow your
  user folder; remove the "env" part to allow everything. ZIPSPLITTER_MCP_ROOTS still
  works when AGENTPARCEL_MCP_ROOTS is not set. See About the name:
  https://github.com/MASTER246C/agentparcel/blob/main/README.md#about-the-name

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
