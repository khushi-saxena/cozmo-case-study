#!/usr/bin/env bash
# Raw captures are 200-400 MB each and live outside git.
# Point CAPTURE_URL at wherever the bundle is hosted, or unzip it by hand
# into benchmark/captures/.
set -e
mkdir -p benchmark/captures
CAPTURE_URL="${CAPTURE_URL:-https://drive.google.com/uc?export=download&id=FILE_ID}"
if [ -z "$CAPTURE_URL" ]; then
  echo "Set CAPTURE_URL to the captures bundle, or unzip the bundle into"
  echo "benchmark/captures/ manually. Expected folders:"
  echo "  capture_1788930419   multi-space: bedroom, closet, washroom"
  echo "  capture_1788475750   bedroom, second capture (repeatability)"
  echo "  capture_1788461277   bedroom, first capture"
  echo "  capture_1788482793   open-plan space"
  exit 1
fi
curl -L "$CAPTURE_URL" -o /tmp/captures.zip
unzip -q -o /tmp/captures.zip -d benchmark/captures/
echo "captures ready"
