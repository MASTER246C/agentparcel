AgentParcel for macOS and Linux  (version @@ZS_VERSION@@)
=========================================================
Project site: https://agentparcel.net
Same program as the Windows version (AgentParcel.ps1), written in Python 3.
Parts made on Windows can be rebuilt on Mac/Linux and the other way round - both
use the same part labels and manifest (see README.txt from the Windows version,
section "MANIFEST FORMAT").

Files
  agentparcel.py        the program (Python 3.9+, standard library only)
  AgentParcel.command   macOS launcher (double-click in Finder)
  agentparcel.sh        Linux launcher
  agentparcel.desktop   optional Linux menu/desktop entry (edit the path inside first)
  agentparcel_mcp.py    MCP server for AI agents (see README-mcp.txt)

Requirements
  - Python 3.9 or newer (3.11+ recommended for very large archives over 4 GB).
  - For the window: Tk support in Python.
      macOS : the python.org installer includes it (https://www.python.org/downloads/macos/).
              Homebrew: brew install python python-tk
              (Apple's built-in /usr/bin/python3 has an old Tk that may look broken.)
      Linux : sudo apt install python3 python3-tk      (Debian/Ubuntu)
              sudo dnf install python3 python3-tkinter (Fedora)
  - Without Tk or without a display it falls back to text mode automatically: it asks you
    to drag a zip (or the parts / their folder) into the Terminal window and press Enter.

macOS - first run
  1. Put the folder somewhere (e.g. Documents/AgentParcel).
  2. Make the launcher executable (needed once if the files came via Windows or a zip):
       open Terminal, type  chmod +x  (with a space), drag AgentParcel.command onto the
       Terminal window, press Enter.
  3. Double-click AgentParcel.command. If macOS says it "cannot be opened because it is
     from an unidentified developer": right-click it > Open > Open (only the first time),
     or System Settings > Privacy & Security > "Open Anyway".
     Terminal alternative:  xattr -d com.apple.quarantine AgentParcel.command
  (Finder does not pass files dropped onto a .command file; use the buttons in the window.)

Linux
  chmod +x agentparcel.sh agentparcel.py
  ./agentparcel.sh                       opens the window
  ./agentparcel.sh file.zip              opens the window and starts splitting
  ./agentparcel.sh some_part03.zip       opens the window and rebuilds (siblings found automatically)
  Menu entry: edit the Exec= path in agentparcel.desktop, copy it to
  ~/.local/share/applications/ (then files can also be opened "with" AgentParcel).

Using the window
  Tab "Split a zip"         : Browse... to the zip, optionally change "Max size per zip (MB)"
                              (default 19.5), "Unpack zips inside the zip (recommended)" and
                              "Include AgentParcel apps ..." (writes AgentParcel-apps.zip with the
                              Windows/Mac/Linux apps next to the parts - send it along), Split.
  Tab "Rebuild from parts"  : Add parts... (one part is enough) or Add folder..., optionally
                              "Save to", Rebuild.
  Drag-and-drop into the window only works if the optional 'tkinterdnd2' package is installed
  (pip install tkinterdnd2); otherwise use the buttons.

Command line (same options as the Windows version)
  python3 agentparcel.py --no-gui [--limit-mb 19.5] [--no-unpack-inner] [--no-include-apps] [--output-dir DIR] file.zip
  python3 agentparcel.py --join FOLDER_OR_PART [MORE_PARTS ...] [--output-dir DIR]
     Windows equivalents: -NoGui, -LimitMB, -NoUnpackInner, -NoIncludeApps, -OutputDir, -Join

What it does (identical to Windows)
  Split : parts <name>_split/<name>_part01.zip ... each <= the limit and openable on its own.
          Zips inside the zip (any depth) are unpacked into folders named after them.
          A single file too big even after compression is cut into <file>.001, .002 ...
          Every part has _zipsplitter_part.json; the first and last have _zipsplitter_manifest.json.
  Rebuild: checks every part is present (lists missing part numbers), joins pieces, re-creates
          the inner zips, verifies every file's size + SHA-256, and writes <name>_rebuilt.zip
          (or <name>.zip in "Save to"); never overwrites - adds " (2)". Temp files are removed.
          Parts from the older Windows version (no manifest) are merged best-effort.
  By hand without the app (pieces): extract all parts into one folder, then
          cat "big.mp4.001" "big.mp4.002" > "big.mp4"

AI AGENTS (MCP)
  agentparcel_mcp.py is an MCP server (stdio, no extra packages) that lets AI agents split and
  rebuild with tools (inspect, split_zip, split_files, rebuild, make_apps_bundle). It must stay
  next to agentparcel.py. Setup for Claude Desktop / Claude Code / Cursor / Codex: README-mcp.txt.
