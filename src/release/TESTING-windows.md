# AgentParcel @@ZS_VERSION@@ - Windows testing checklist (for Chris)

Tester: ________  Windows version: ________  Date: ________

## Package
- [ ] `Get-FileHash AgentParcel-@@ZS_VERSION@@-windows.zip` matches `SHA256SUMS.txt`
- [ ] Extract All gives one folder `AgentParcel-@@ZS_VERSION@@-windows\`

## App (no Python needed)
- [ ] Double-clicking `AgentParcel.bat` opens the window. Its title shows @@ZS_VERSION@@, and nothing is cut off at 100% and 150% scaling
- [ ] Split a >40 MB zip at 19.5: every part is <= 19.5 MB, and `AgentParcel-apps.zip` is there when the option is ticked
- [ ] Rebuild from the parts folder gives "verified". The rebuilt zip opens and has the same files
- [ ] With one part removed, Rebuild names the missing part
- [ ] Dragging a .zip onto `AgentParcel.bat` starts it with that file
- [ ] Command line: `-NoGui` split and `-Join` rebuild work (see README.md)
- [ ] Byte-split a non-zip file. `python rebuild.py` in that folder restores the exact file. Verify names a part after one is deleted. Stop during a split reports Cancelled and leaves no partial parts

## Python helper + MCP (`Install-Python-for-AgentParcel.bat`)
- [ ] First run on a PC without Python: winget step (expected to say not found until winget adds 3.15), then the python.org download
- [ ] It prints "SHA-256 matches" and "signature valid: Python Software Foundation", with no UAC prompt
- [ ] `%LOCALAPPDATA%\Programs\Python\Python315\python.exe` exists, and `python --version` shows 3.15.1 in a NEW terminal
- [ ] The smoke test prints "OK: agentparcel @@ZS_VERSION@@ ... tools: inspect, split_zip, split_any_file, split_files, verify, rebuild, make_apps_bundle"
- [ ] `MCP-config-snippets.txt` is written, its paths are correct, and it waits for a key at the end
- [ ] A second run says "found" and skips the install
- [ ] Paste a snippet into one agent (e.g. Cursor or Claude Code). The agent lists the agentparcel tools, and a `split_zip` and `rebuild` round trip works
- [ ] Exit code: `cmd /c Install-Python-for-AgentParcel.bat /nopause & echo %errorlevel%` gives 0

## Cross-platform
- [ ] Parts made on Windows rebuild on Linux (`python3 agentparcel.py --join ...`), and the other way round
