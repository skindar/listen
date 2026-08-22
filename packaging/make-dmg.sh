#!/bin/bash
# Pack dist/Listen.app into a distributable DMG for GitHub Releases.
# Usage: packaging/make-dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/Listen.app"
VERSION="$1"
if [[ -z "$VERSION" ]]; then
  VERSION="0.2.0"
fi
DMG="$ROOT/dist/Listen-${VERSION}.dmg"

if [[ ! -d "$APP" ]]; then
  echo "Build the app first:  .venv/bin/python setup_app.py py2app" >&2
  exit 1
fi

rm -rf "$ROOT/dist/dmg-staging" "$DMG"
mkdir -p "$ROOT/dist/dmg-staging"
cp -R "$APP" "$ROOT/dist/dmg-staging/"
ln -s /Applications "$ROOT/dist/dmg-staging/Applications"

hdiutil create -volname "Listen" -srcfolder "$ROOT/dist/dmg-staging" \
  -fs HFS+ -format UDZO "$DMG"
rm -rf "$ROOT/dist/dmg-staging"

echo "Created $DMG"
shasum -a 256 "$DMG"  # paste this into Casks/listen.rb as sha256