#!/usr/bin/env sh
# Headless check: parse STEP files with the installed IngeTrazo Flatpak.
#   scripts/smoke.sh part.step [max angle in degrees, default 20]
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="$(realpath "$1")"
flatpak run --filesystem="$(dirname "$FILE")":ro --command=python3 com.ingetrazo.IngeTrazo - "$ROOT" "$FILE" "${2:-20}" <<'PY'
import importlib.util, sys, time
root, path, angle = sys.argv[1:4]
sys.path.insert(0, "/app/ingetrazo")
spec = importlib.util.spec_from_file_location(
    "step_import", f"{root}/step_import/__init__.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.time()
parts = mod.parse_step(path, float(angle))
faces = [f for _n, m in parts for f in m.faces]
xs = [c for f in faces for v in f.vertices for c in (v.x(), v.y(), v.z())]
ext = [max(xs[i::3]) - min(xs[i::3]) for i in range(3)]
colours = {tuple(round(c, 2) for c in (f.attrs or {}).get("color", ()))
           for f in faces}
hard = sum(1 for _n, m in parts for e in m.edges
           if not getattr(e, "soft", False) and not getattr(e, "smooth", False))
print(f"{len(parts)} parts, {len(faces)} faces, {len(colours)} colours, "
      f"{hard} visible edges, extent {ext[0]:.4f} x {ext[1]:.4f} x "
      f"{ext[2]:.4f} m, {time.time() - t:.2f}s")
print("parts:", ", ".join(n for n, _m in parts[:6]), "…")
print("colours:", sorted(colours)[:8])
PY
