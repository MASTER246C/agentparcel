AgentParcel  (version @@ZS_VERSION@@)  -  https://agentparcel.net
=================================================================
Splits one big .zip into smaller .zip files of at most 19.5 MB each
(19.5 x 1024 x 1024 = 20,447,232 bytes), and rebuilds the original zip from them.
Every part is a normal zip that also opens on its own.

HOW TO USE
- Double-click AgentParcel.bat. The window has two tabs:
    "Split a zip"         - drag a file in (or Browse...), then Split.
                            A .zip becomes zip parts. Any other file, or the
                            "Byte-split this file" box, becomes raw byte parts.
    "Rebuild from parts"  - drag in the parts, their folder, or just ONE part
                            (the other parts next to it are found automatically),
                            then Verify (checksums) or Rebuild.
- Stop cancels a running split or rebuild, deletes that run's partial files,
  and the status line says Cancelled. The window stays usable while work runs.
- You can also drag things straight onto AgentParcel.bat: a normal zip is split,
  parts (or a folder of parts) are rebuilt.
- "Max size per zip (MB)" defaults to 19.5.
- "Unpack zips inside the zip (recommended)" is ON by default (see below).
- "Include AgentParcel apps (Windows, Mac, Linux) so the recipient can rebuild" is ON by
  default: the split folder also gets AgentParcel-apps.zip (this program for Windows, Mac
  and Linux plus "HOW TO REBUILD.txt"). Send it along with the parts. It is not a part and
  Rebuild ignores it if it is dropped in with the parts.

SPLIT OUTPUT
- A folder next to the original zip:  <name>_split\<name>_part01.zip, _part02.zip, ...
  (if that folder already has files in it, "<name>_split (2)" is used instead).
- The original zip is never changed.

REBUILD OUTPUT
- <name>_rebuilt.zip in the parts folder, or <original name>.zip in the folder you
  choose with "Save to". Existing files are never overwritten - " (2)" is added.
- Every file is checked against the size and SHA-256 recorded when it was split.
  If a part is missing, the exact part numbers are listed and nothing is written.
- Files, folders (including empty ones), paths and order come back exactly. The
  rebuilt zip is re-compressed, so its own size/bytes can differ slightly from the
  original zip, but everything inside it (including inner zips' contents) is identical.

ZIPS INSIDE THE ZIP
- With the box ticked (default), any .zip found inside your zip - at any depth - is
  opened and its contents are repacked straight into the parts, inside a folder named
  after it. Example:  NOLA SHIT\batch-01.zip  ->  NOLA SHIT\batch-01\...files...
  So every part works on its own. Rebuild turns those folders back into the inner zips.
  (If a folder with that name already exists in the zip, "<name>_unzipped" is used.)
- An inner zip that can't be opened (corrupt or password-protected) is kept as a
  normal file; the window lists any such zips.
- Untick the box (or use -NoUnpackInner) to keep inner zips as plain files.

VERY LARGE FILES
- Only as a last resort: if one single (non-zip) file is too big to fit in 19.5 MB even
  when compressed, it is cut into pieces named <file>.001, <file>.002, ... spread over
  consecutive parts. Rebuild joins them automatically. Without the app:
  extract all parts into one folder and run, in Command Prompt, e.g.
      copy /b "videos\big.mp4.001"+"videos\big.mp4.002" "videos\big.mp4"
  (REJOIN_INSTRUCTIONS.txt in the split folder has the exact commands.)

PARTS FROM THE OLDER VERSION (no manifest)
- Rebuild still works on a best-effort basis: it merges all parts and re-joins
  .001/.002 pieces, but it cannot verify files, cannot detect a missing LAST part,
  and cannot turn unpacked inner-zip folders back into zips.

COMMAND LINE (no window)
  split:    powershell -ExecutionPolicy Bypass -File AgentParcel.ps1 -NoGui "C:\path\file.zip"
            options: -LimitMB 19.5   -OutputDir "D:\somewhere"   -NoUnpackInner   -NoIncludeApps
  rebuild:  powershell -ExecutionPolicy Bypass -File AgentParcel.ps1 -Join "C:\path\file_split"
            (-Join takes a folder, one part, or several parts; option: -OutputDir "D:\somewhere")

NOTES
- Needs only Windows PowerShell 5.1 (built into Windows 10/11). Nothing to install.
- Password-protected/encrypted zips are not supported.
- Inner zips are unpacked/rebuilt in a temporary folder (%TEMP%\AgentParcel_...) that
  is deleted when the job finishes. Needs free disk space about the size of the inner zips.

BYTE SPLIT (any file type)
- Tick "Byte-split this file", or choose a file that is not a .zip.
  Command line: -NoGui -SplitBytes "C:\path\movie.mp4"
  Output folder: <full file name>_split\  (for example movie.mp4_split)
  Parts: movie.mp4_part01, movie.mp4_part02, ... raw bytes, each <= the limit.
- _agentparcel_bytes.json records the original name, size, SHA-256, and each part's SHA-256.
- HOW-TO-REBUILD.txt explains the rebuild for a person or another AI agent.
  rebuild.py (Python 3, no packages) checks every part and writes the original file.
  The text file also has a PowerShell equivalent.
- Verify (window button, or -Verify "C:\path\movie.mp4_split") names missing and corrupt parts
  and writes nothing. Rebuild refuses to write a file until every part matches.

ZIP PART SIDECAR
- A zip split still uses _zipsplitter_part.json and _zipsplitter_manifest.json inside the parts
  (see MANIFEST FORMAT below). The folder also gets _agentparcel_zipset.json (SHA-256 of each
  part file), HOW-TO-REBUILD.txt, and rebuild.py. rebuild.py only checks those part files.
  Reassembling the zip is still AgentParcel's Rebuild.

==========================================================================================
MANIFEST FORMAT (version 1) - for other implementations (macOS / Linux builds)
==========================================================================================
About the name: https://github.com/MASTER246C/agentparcel/blob/main/README.md#about-the-name
The file names (_zipsplitter_part.json, _zipsplitter_manifest.json, _zipsplitter_apps.json)
and the "zipsplitter-*" format ids below stay so older part sets still rebuild.
All JSON files are UTF-8; AgentParcel writes pure ASCII (non-ASCII chars as \uXXXX escapes).
All paths are zip entry names exactly as stored (normally "/" separated, dirs end in "/").
Times are the zip entry's local wall-clock time, "yyyy-MM-dd HH:mm:ss" (no time zone).

1) _zipsplitter_part.json  - at the root of EVERY part
   {"format":"zipsplitter-part","version":1,"setId":"<32 hex>","part":3,"partCount":8,
    "originalName":"NOLA SHIT.zip","tool":"AgentParcel.ps1 3.0"}
   - part is 1-based. Parts of one set share setId. Part file names are
     <original name without .zip>_partNN.zip (NN zero-padded to at least 2 digits),
     but readers must rely on the JSON, not the file name.

2) _zipsplitter_manifest.json - at the root of the FIRST and the LAST part (identical copies)
   {"format":"zipsplitter-manifest","version":1,"setId":"...","tool":"...","created":"...",
    "originalName":"NOLA SHIT.zip","originalSize":87491020,"limitBytes":20447232,
    "unpackInner":true,
    "archives":[ {"id":0,"parent":-1,"depth":0,"entry":"","folder":""},
                 {"id":1,"parent":0,"depth":1,"entry":"NOLA SHIT/x.zip","folder":"NOLA SHIT/x/"}, ... ],
    "entries":[ ...records... ]}

   archives: id 0 is the original (outer) zip. Every other id is an inner zip that was
     unpacked: "parent" = archive it lives in, "entry" = its entry name inside the parent,
     "folder" = prefix under which its contents are stored in the parts. Ids are unique
     but not necessarily contiguous.

   entries: one record per entry of every archive. Records of the SAME archive appear in
     that archive's original entry order (records of different archives are interleaved;
     group by "archive" and keep the order). Fields:
       archive  - id of the archive this entry belongs to
       name     - entry name inside that archive (exactly as in the original)
       type     - "file" | "dir" | "zip"
     type "file":
       stored   - entry name in the parts holding the data
       size     - uncompressed size in bytes
       sha256   - lowercase hex SHA-256 of the uncompressed data
       split    - true if it was cut into raw pieces (informational)
       time     - last-write time
       If no part contains an entry named <stored>, the data is in raw pieces
       <stored>.001, <stored>.002, ... (3 or more digits, consecutive from 1, each piece in
       its own part); concatenate them in numeric order. The last piece's part also holds
       <stored>.REJOIN.txt (human note, ignore it).
     type "dir":   stored, time   (empty folders are kept this way)
     type "zip":   zip (archive id), folder, size + sha256 of the ORIGINAL inner zip file
                   (informational - a rebuilt inner zip is re-compressed and won't match), time

   Rebuild algorithm: open all parts, check part numbers 1..partCount are present (same setId),
   index every entry name across all parts; then write archive 0: for each of its records in
   order -> dir: create dir entry; file: copy stored data (or pieces), verify size + sha256;
   zip: recursively build archive <zip> into a temp zip file, add it under <name>.
   Ignore _zipsplitter_part.json, _zipsplitter_manifest.json and *.REJOIN.txt in the parts.
   Readers should refuse/warn on "version" greater than they understand.

3) AgentParcel-apps.zip (optional, written next to the parts; NOT a part)
   Contains _zipsplitter_apps.json {"format":"zipsplitter-apps","version":"x.y.z",...} at the root,
   "HOW TO REBUILD.txt", LICENSE.txt, Windows/ (AgentParcel.ps1, AgentParcel.bat, README.txt,
   Install-Python-for-AgentParcel.bat),
   mac/ (agentparcel.py, AgentParcel.command - mode 755, README.txt) and
   linux/ (agentparcel.py, agentparcel.sh - mode 755, agentparcel.desktop, README.txt) and
   mcp/ (agentparcel_mcp.py, agentparcel.py - mode 755, README.txt: the MCP server for AI agents).
   Rebuild skips any zip named AgentParcel-apps*.zip or ZipSplitter-apps*.zip
   (the bundle name from development builds), or containing _zipsplitter_apps.json.
