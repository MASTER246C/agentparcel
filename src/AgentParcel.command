#!/bin/bash
# AgentParcel launcher for macOS - double-click this file in Finder.
# (First time: if macOS blocks it, right-click > Open, or see README-mac-linux.txt.)
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "AgentParcel needs Python 3.9 or newer."
  echo "Install it from https://www.python.org/downloads/macos/ and double-click this file again."
  read -r -p "Press Enter to close..." _
  exit 1
fi
"$PY" ./agentparcel.py "$@"
status=$?
if [ $status -ne 0 ]; then read -r -p "Press Enter to close..." _; fi
exit $status
