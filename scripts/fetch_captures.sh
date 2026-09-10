#!/usr/bin/env bash
# Raw captures are ~830 MB total and live outside git.
#
# Google Drive interrupts large downloads with a virus-scan page, so this
# grabs the confirmation token first and then the file. If it fails, the
# plain share link in the README works in a browser.
set -e

FILE_ID="16VfuW4t1hZvr9IrdqhAt4pZuEEVgnZdO"
DEST="/tmp/cozmo-captures.zip"

mkdir -p benchmark/captures

if [ -d benchmark/captures/capture_1788930419 ]; then
  echo "captures already present"
  exit 0
fi

echo "fetching captures (~830 MB)"
COOKIE=$(mktemp)
CONFIRM=$(curl -sc "$COOKIE" "https://drive.google.com/uc?export=download&id=${FILE_ID}" \
          | grep -o 'confirm=[^&"]*' | head -1 | cut -d= -f2)

if [ -n "$CONFIRM" ]; then
  curl -Lb "$COOKIE" \
    "https://drive.google.com/uc?export=download&confirm=${CONFIRM}&id=${FILE_ID}" -o "$DEST"
else
  curl -Lb "$COOKIE" "https://drive.google.com/uc?export=download&id=${FILE_ID}" -o "$DEST"
fi
rm -f "$COOKIE"

if [ "$(stat -f%z "$DEST" 2>/dev/null || stat -c%s "$DEST")" -lt 100000000 ]; then
  echo "download looks too small - Drive probably returned its warning page."
  echo "Download by hand instead:"
  echo "  https://drive.google.com/file/d/${FILE_ID}/view"
  echo "then: unzip -o <the zip> -d benchmark/"
  exit 1
fi

unzip -q -o "$DEST" -d benchmark/
echo "captures ready:"
ls benchmark/captures/
