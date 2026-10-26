#!/bin/sh
# AgentParcel launcher for Linux.  Usage:  ./agentparcel.sh [file.zip | parts... | folder]
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
PY=""
for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "AgentParcel needs Python 3.9 or newer (e.g. 'sudo apt install python3 python3-tk')." >&2
  exit 1
fi
exec "$PY" "$HERE/agentparcel.py" "$@"
