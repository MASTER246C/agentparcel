#!/bin/sh
# AgentParcel @@ZS_VERSION@@ - install what AgentParcel needs on Linux: python3 (3.9+) and Tk (python3-tk).
# Run it yourself:   ./install-deps.sh        (it shows the command and asks before using sudo)
#   --yes   do not ask (still uses sudo)        --check   only check, install nothing
set -u
ASK=1; CHECK=0
for a in "$@"; do
  case "$a" in
    --yes|-y) ASK=0 ;;
    --check) CHECK=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

find_py() {
  for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

report() {
  PY=$(find_py) || PY=""
  if [ -z "$PY" ]; then echo "python3 3.9+ : MISSING"; return 1; fi
  echo "python3 3.9+ : OK  ($(command -v "$PY"), $("$PY" -c 'import platform; print(platform.python_version())'))"
  if "$PY" -c 'import tkinter' 2>/dev/null; then echo "Tk (window)  : OK"; else echo "Tk (window)  : MISSING (AgentParcel still works in text mode / CLI / MCP)"; return 1; fi
  return 0
}

echo "== AgentParcel: checking Python and Tk"
if report; then echo "Everything is already installed."; exit 0; fi
[ "$CHECK" = 1 ] && exit 1

if command -v apt-get >/dev/null 2>&1; then CMD="apt-get update && apt-get install -y python3 python3-tk"
elif command -v dnf >/dev/null 2>&1; then CMD="dnf install -y python3 python3-tkinter"
elif command -v yum >/dev/null 2>&1; then CMD="yum install -y python3 python3-tkinter"
elif command -v pacman >/dev/null 2>&1; then CMD="pacman -S --needed --noconfirm python tk"
elif command -v zypper >/dev/null 2>&1; then CMD="zypper --non-interactive install python3 python3-tk"
else
  echo "No apt-get, dnf, yum, pacman or zypper found. Install python3 (3.9+) and its Tk package"
  echo "with your distribution's package manager, then run this again with --check."
  exit 1
fi

if [ "$(id -u)" = 0 ]; then SUDO=""; else SUDO="sudo"; fi
if [ -n "$SUDO" ] && ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is not available. As root run:  $CMD"; exit 1
fi
echo
echo "This will run:  $SUDO sh -c '$CMD'"
if [ "$ASK" = 1 ]; then
  printf "Continue? [y/N] "
  read -r ans || ans=""
  case "$ans" in y|Y|yes|YES) ;; *) echo "Cancelled - nothing installed."; exit 1 ;; esac
fi
$SUDO sh -c "$CMD" || { echo "The package install failed."; exit 1; }
echo
echo "== Checking again"
report || exit 1
echo "Done. Start AgentParcel with ./agentparcel.sh"
