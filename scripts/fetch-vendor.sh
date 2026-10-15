#!/usr/bin/env sh
# Unpack the cascadio wheel (OpenCASCADE STEP reader, MIT) into
# step_import/_vendor/. The abi3 wheel covers CPython 3.12+, which is what
# the IngeTrazo Flatpak and installers ship.
set -eu
VERSION="${CASCADIO_VERSION:-0.1.1}"
PLATFORM="${CASCADIO_PLATFORM:-manylinux_2_27_x86_64}"
cd "$(dirname "$0")/.."
DEST=step_import/_vendor
URL=$(curl -fsSL "https://pypi.org/pypi/cascadio/$VERSION/json" | python3 -c "
import json, sys
urls = json.load(sys.stdin)['urls']
print(next(u['url'] for u in urls
           if 'cp312-abi3-$PLATFORM' in u['filename']))")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL -o "$TMP/cascadio.whl" "$URL"
rm -rf "$DEST"
python3 -m zipfile -e "$TMP/cascadio.whl" "$DEST"
echo "cascadio $VERSION ($PLATFORM) -> $DEST"
