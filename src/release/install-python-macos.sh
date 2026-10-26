#!/bin/bash
# AgentParcel @@ZS_VERSION@@ - get a Python with Tk for AgentParcel on macOS.   UNTESTED on a real Mac.
# Run it in Terminal:   ./install-python-macos.sh            (asks before changing anything)
#   --check   only check          --pkg   use the python.org installer even if Homebrew exists
# It never uses sudo itself. The python.org installer asks for your password in its own window.
set -u
PY_VER="3.15.1"
PKG_URL="https://www.python.org/ftp/python/3.15.1/python-3.15.1-macos11.pkg"
PKG_SHA256="de6341e8a4386c8272dc4f7ca1336f4e43abdd292249c674a67bf857c0c6fa3d"
CHECK=0; FORCE_PKG=0
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --pkg) FORCE_PKG=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

find_py() {
  # Apple's /usr/bin/python3 is skipped on purpose: it can trigger the Xcode tools installer and
  # has an old Tk.
  for c in /Library/Frameworks/Python.framework/Versions/3.15/bin/python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
    p=$(command -v "$c" 2>/dev/null) || continue
    [ "$p" = /usr/bin/python3 ] && continue
    if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then echo "$p"; return 0; fi
  done
  return 1
}

report() {
  PY=$(find_py) || PY=""
  if [ -z "$PY" ]; then echo "Python 3.9+ : MISSING"; return 1; fi
  echo "Python 3.9+ : OK  ($PY, $("$PY" -c 'import platform; print(platform.python_version())'))"
  if "$PY" -c 'import tkinter; tkinter.Tcl()' 2>/dev/null; then echo "Tk (window) : OK"; else echo "Tk (window) : MISSING"; return 1; fi
  return 0
}

echo "== AgentParcel: checking Python and Tk"
if report; then echo "Everything is already installed. Use this python in MCP configs: $PY"; exit 0; fi
[ "$CHECK" = 1 ] && exit 1

if [ "$FORCE_PKG" = 0 ] && command -v brew >/dev/null 2>&1; then
  echo
  echo "Homebrew found. This will run:  brew install python@3.15 python-tk@3.15"
  echo "(if Homebrew does not have 3.15 yet, it falls back to: brew install python python-tk)"
  read -r -p "Continue? [y/N] " ans || ans=""
  case "$ans" in y|Y|yes|YES) ;; *) echo "Cancelled - nothing installed."; exit 1 ;; esac
  brew install python@3.15 python-tk@3.15 || brew install python python-tk || { echo "brew install failed."; exit 1; }
else
  echo
  echo "This will download the official Python $PY_VER installer from python.org,"
  echo "check its SHA-256 and Apple signature, and open it (you click through it yourself):"
  echo "  $PKG_URL"
  read -r -p "Continue? [y/N] " ans || ans=""
  case "$ans" in y|Y|yes|YES) ;; *) echo "Cancelled - nothing installed."; exit 1 ;; esac
  TMP=$(mktemp -d) || exit 1
  PKG="$TMP/python-$PY_VER-macos11.pkg"
  curl -fL --retry 3 -o "$PKG" "$PKG_URL" || { echo "Download failed."; exit 1; }
  GOT=$(shasum -a 256 "$PKG" | awk '{print $1}')
  if [ "$GOT" != "$PKG_SHA256" ]; then echo "SHA-256 mismatch ($GOT) - not opening it."; exit 1; fi
  echo "SHA-256 OK"
  if pkgutil --check-signature "$PKG" | grep -q "Python Software Foundation"; then echo "Signed by Python Software Foundation"; else
    echo "Signature check failed - not opening it."; exit 1; fi
  open -W "$PKG"
  echo "When the installer has finished, also run 'Install Certificates.command' in"
  echo "/Applications/Python 3.15 if you want Python to download from https sites."
fi
echo
echo "== Checking again"
report || { echo "Still missing - open a new Terminal window and run: ./install-python-macos.sh --check"; exit 1; }
echo "Done. Double-click AgentParcel.command. Python for MCP configs: $PY"
