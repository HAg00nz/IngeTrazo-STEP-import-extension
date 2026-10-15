#!/usr/bin/env sh
# Headless check: parse STEP files with the installed IngeTrazo Flatpak.
#   scripts/smoke.sh part.step [quality]
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="$(realpath "$1")"
flatpak run --filesystem="$(dirname "$FILE")":ro --command=python3 com.ingetrazo.IngeTrazo - "$ROOT" "$FILE" "${2:-normal}" <<'PY'
import importlib.util, sys, time
root, path, quality = sys.argv[1:4]
sys.path.insert(0, "/app/ingetrazo")
spec = importlib.util.spec_from_file_location(
    "step_import", f"{root}/step_import/__init__.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.time()
mesh = mod.parse_step(path, quality)
xs = [c for f in mesh.faces for v in f.vertices for c in (v.x(), v.y(), v.z())]
ext = [max(xs[i::3]) - min(xs[i::3]) for i in range(3)]
print(f"{len(mesh.faces)} faces, extent {ext[0]:.4f} x {ext[1]:.4f} x "
      f"{ext[2]:.4f} m, {time.time() - t:.2f}s")
PY
