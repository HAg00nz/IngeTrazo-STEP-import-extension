# SPDX-License-Identifier: GPL-3.0-or-later
"""STEP import for IngeTrazo (.step / .stp, AP203 / AP214 / AP242).

STEP is a B-rep format: exact surfaces, not triangles. OpenCASCADE, through
the ``cascadio`` wheel vendored in ``_vendor/``, tessellates it to a GLB in
metres (whatever unit the STEP file was written in); IngeTrazo's glTF
helpers read that back part by part.

The file lands as one container group named after the file with one named,
coloured group per CAD part inside, as one undo step. Building each part as
its own mesh also keeps it under IngeTrazo's seam-softening cap, so the
tessellation triangles stay hidden. Planar CAD faces come out as one face
each when "merge coplanar triangles" is on, so they can be pushed/pulled.
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "_vendor"

#: Detail levels, coarse to fine: the largest angle (degrees) between two
#: neighbouring facets of a curved surface. The chord tolerance follows the
#: angle (relative to edge length) so small and large curves match.
MAX_ANGLES = (45, 30, 20, 14, 10, 7, 5, 3)
DEFAULT_ANGLE = 20
#: IngeTrazo hides an edge between facets meeting flatter than this
#: (``formats.fuse.soften_smooth_edges``, cos 0.85): coarser than this, the
#: facets of curved surfaces show.
SOFTEN_ANGLE = math.degrees(math.acos(0.85))
#: Above this many triangles the import asks before building the model.
CONFIRM_TRIANGLES = 1_000_000

_SETTINGS_ANGLE = "step_import/max_angle"
_SETTINGS_MERGE = "step_import/merge_coplanar"
_SETTINGS_UP = "step_import/up_axis"

#: World rotation from the STEP file's frame to IngeTrazo's (Z up). STEP is
#: Z up by convention and cascadio writes the GLB without converting it to
#: glTF's Y up, so "z" is the identity; "y" is for exporters that model
#: with Y up.
UP_AXES = {
    "z": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "y": ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
}


def _cascadio():
    """Import the vendored cascadio, with an error that says how to fix it."""
    if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))
    try:
        import cascadio
    except ImportError as exc:
        raise RuntimeError(
            "The STEP reader (cascadio) is missing. Run "
            "scripts/fetch-vendor.sh in the extension folder.") from exc
    return cascadio


def _srgb(c: float) -> float:
    """glTF colour factors are linear; STEP colours and IngeTrazo's face
    colours are sRGB."""
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * c ** (1 / 2.4) - 0.055


def _read_parts(glb: Path, up_axis: str = "z"):
    """``[(name, batches)]``, one entry per glTF node with geometry, in
    world space, metres, Z up. ``batches`` is what ``formats.glb.build_mesh``
    takes."""
    import numpy as np
    from formats.glb import (_accessor, _material_recipe, _node_transforms,
                             parse_container)

    js, buffers = parse_container(glb)
    up = np.array(UP_AXES[up_axis])
    nodes, meshes = js.get("nodes", []), js.get("meshes", [])
    parts = []
    for node_idx, world in _node_transforms(js):
        nd = nodes[node_idx]
        mi = nd.get("mesh")
        if mi is None or mi >= len(meshes):
            continue
        batches = []
        for prim in meshes[mi].get("primitives", []):
            attr = prim.get("attributes", {})
            if prim.get("mode", 4) != 4 or "POSITION" not in attr:
                continue
            pos = _accessor(js, buffers, attr["POSITION"])[:, :3]
            if "indices" in prim:
                idx = _accessor(js, buffers, prim["indices"]).reshape(-1)
            else:
                idx = np.arange(len(pos), dtype=np.int64)
            idx = idx.astype(np.int64)[:(len(idx) // 3) * 3].reshape(-1, 3)
            if not len(idx):
                continue
            _tex, _uvt, rgba, _uv_set, opacity = _material_recipe(
                js, prim.get("material"), [])
            if rgba:
                rgba = [_srgb(c) for c in rgba[:3]] + list(rgba[3:4])
            pts = (pos @ world[:3, :3].T + world[:3, 3]) @ up.T
            batches.append((pts[idx], None, (None, rgba, opacity)))
        if batches:
            name = (nd.get("name") or meshes[mi].get("name")
                    or f"Part {len(parts) + 1}")
            parts.append((name[:60], batches))
    return parts


def tessellate(path, max_angle: float = DEFAULT_ANGLE, up_axis: str = "z",
               progress=None):
    """STEP → ``(parts, triangle count)``; see :func:`_read_parts`.
    Worker-thread safe."""
    if progress is not None:
        progress(0.05, "Tessellating STEP…")
    angle = math.radians(max_angle)
    cascadio = _cascadio()
    with tempfile.TemporaryDirectory(prefix="ingetrazo-step-") as tmp:
        glb = Path(tmp) / "model.glb"
        status = cascadio.step_to_glb(
            str(path), str(glb), tol_linear=0.2 * angle,
            tol_angular=angle, tol_relative=True)
        if status != 0 or not glb.is_file():
            raise ValueError(f"OpenCASCADE could not read {Path(path).name}")
        if progress is not None:
            progress(0.3, "Reading triangles…")
        parts = _read_parts(glb, up_axis)
    if not parts:
        raise ValueError(f"{Path(path).name} contains no solid or surface "
                         "geometry")
    count = sum(len(t) for _n, b in parts for t, _u, _r in b)
    return parts, count


def build_parts(parts, merge_coplanar: bool = True, progress=None):
    """``[(name, Mesh)]`` from :func:`tessellate`'s parts. Worker-thread
    safe: the meshes are detached from the document."""
    from formats.glb import build_mesh
    from formats.fuse import simplify_mesh

    total = sum(len(t) for _n, b in parts for t, _u, _r in b) or 1
    done = 0
    out = []
    for name, batches in parts:
        if progress is not None:
            progress(0.35 + 0.6 * done / total, "Building the model…")
        mesh = build_mesh(batches)
        if merge_coplanar:
            simplify_mesh(mesh, principal_planes=False)
        out.append((name, mesh))
        done += sum(len(t) for t, _u, _r in batches)
    return out


def parse_step(path, max_angle: float = DEFAULT_ANGLE,
               merge_coplanar: bool = True, up_axis: str = "z",
               progress=None):
    """Read the STEP at ``path`` into ``[(part name, Mesh)]``."""
    parts, _count = tessellate(path, max_angle, up_axis, progress)
    return build_parts(parts, merge_coplanar, progress)


def add_step_parts(scene, path, meshes) -> None:
    """Insert parsed parts: one group named after the file holding a group
    per part (just the part, for a single-part file). UI thread only."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group

    stem = Path(path).stem[:60]
    if len(meshes) == 1:
        scene.groups.append(Group(meshes[0][1], name=stem))
    else:
        kids = []
        for name, mesh in meshes:
            kid = Group(mesh, name=name)
            kid.xform = QMatrix4x4()
            # A part is its own geometry, shared with nothing: a group in
            # the container, not a component (as formats/obj.py does).
            kid.component = False
            kids.append(kid)
        container = Group(name=stem)
        container.adopt(kids)
        scene.groups.append(container)
    scene.version += 1


def _run_threaded(window, fn, cb):
    """Run ``fn(progress)`` on a worker, relaying progress to the UI thread;
    returns ``(result, exception)``. Bound-method receivers on queued
    connections, as docs/plugins.md asks."""
    from PySide6.QtCore import QEventLoop, QObject, QThread, Qt, Signal

    class _Worker(QObject):
        progressed = Signal(float, str)
        finished = Signal(object, object)

        def run(self):
            try:
                value = fn(lambda f, t: self.progressed.emit(f, t))
                self.finished.emit(value, None)
            except Exception as exc:  # noqa: BLE001 — reported to caller
                self.finished.emit(None, exc)

    result = {}
    loop = QEventLoop()

    class _Relay(QObject):
        def on_progress(self, fraction, text):
            cb(fraction, text)

        def on_finished(self, value, exc):
            result["value"], result["exc"] = value, exc
            loop.quit()

    thread = QThread(window)
    worker = _Worker()
    worker.moveToThread(thread)
    relay = _Relay(window)
    worker.progressed.connect(relay.on_progress, Qt.QueuedConnection)
    worker.finished.connect(relay.on_finished, Qt.QueuedConnection)
    thread.started.connect(worker.run)
    thread.start()
    loop.exec()
    thread.quit()
    thread.wait()
    worker.deleteLater()
    relay.deleteLater()
    return result.get("value"), result.get("exc")


def _ask_options(window):
    """``(max angle, merge coplanar, up axis)``; None when cancelled."""
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                   QFormLayout, QHBoxLayout, QLabel, QSlider,
                                   QWidget)
    from core.i18n import tr

    settings = QSettings()
    try:
        saved = int(settings.value(_SETTINGS_ANGLE, DEFAULT_ANGLE))
    except (TypeError, ValueError):
        saved = DEFAULT_ANGLE
    start = min(range(len(MAX_ANGLES)),
                key=lambda i: abs(MAX_ANGLES[i] - saved))

    dialog = QDialog(window)
    dialog.setWindowTitle(tr("Import STEP"))
    form = QFormLayout(dialog)

    row = QWidget(dialog)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(QLabel(tr("Coarse"), row))
    slider = QSlider(Qt.Horizontal, row)
    slider.setRange(0, len(MAX_ANGLES) - 1)
    slider.setPageStep(1)
    slider.setTickPosition(QSlider.TicksBelow)
    slider.setValue(start)
    lay.addWidget(slider, 1)
    lay.addWidget(QLabel(tr("Fine"), row))
    form.addRow(tr("Curve resolution"), row)

    shown = QLabel(dialog)
    shown.setWordWrap(True)

    def describe(i):
        a = MAX_ANGLES[i]
        text = tr("At most {a}° between neighbouring facets.", a=a)
        if a > SOFTEN_ANGLE:
            text += " " + tr("Curved surfaces show their facets.")
        else:
            text += " " + tr("Curved surfaces look smooth.")
        if a <= 7:
            text += " " + tr("Large models get very heavy (millions of "
                             "triangles); you will be asked before it is "
                             "built.")
        shown.setText(text)

    slider.valueChanged.connect(describe)
    describe(start)
    form.addRow("", shown)

    up = QComboBox(dialog)
    up.addItem(tr("Z (STEP standard)"), "z")
    up.addItem(tr("Y (some CAD exporters)"), "y")
    idx = up.findData(str(settings.value(_SETTINGS_UP, "z")))
    up.setCurrentIndex(idx if idx >= 0 else 0)
    up.setToolTip(tr("Which axis of the file points up. Pick Y if the "
                     "model comes in lying on its side."))
    form.addRow(tr("Up axis"), up)

    merge = QCheckBox(tr("Merge coplanar triangles into one face"), dialog)
    merge.setToolTip(tr("Flat CAD faces become one face you can push/pull. "
                        "Takes longer on big models."))
    merge.setChecked(
        str(settings.value(_SETTINGS_MERGE, "true")).lower() == "true")
    form.addRow(merge)
    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.Accepted:
        return None
    angle = MAX_ANGLES[slider.value()]
    settings.setValue(_SETTINGS_ANGLE, angle)
    settings.setValue(_SETTINGS_MERGE, merge.isChecked())
    settings.setValue(_SETTINGS_UP, up.currentData())
    return angle, merge.isChecked(), up.currentData()


def _confirm_heavy(window, count) -> bool:
    from PySide6.QtWidgets import QMessageBox
    from core.i18n import tr
    answer = QMessageBox.question(
        window, tr("Import STEP"),
        tr("This model becomes {n} triangles at this resolution. Building "
           "it may take minutes and make the model slow to work with. "
           "Import anyway?", n=f"{count:,}".replace(",", " ")))
    return answer == QMessageBox.Yes


def import_step(app, path=None) -> bool:
    """File dialog (unless ``path`` is given), options, then the import as
    one undo step. True when something was imported."""
    from PySide6.QtWidgets import QMessageBox
    from core.history import SnapshotImport
    from core.i18n import tr
    from views.filedialogs import file_dialogs

    window = app.window
    if path is None:
        path, _ = file_dialogs.getOpenFileName(
            window, tr("Import STEP"), "",
            tr("STEP model (*.step *.stp *.STEP *.STP);;All files (*)"))
        if not path:
            return False
    path = Path(path)
    options = _ask_options(window)
    if options is None:
        return False
    max_angle, merge_coplanar, up_axis = options

    def fail(dlg, exc):
        dlg.close()
        QMessageBox.critical(window, tr("Import STEP failed"), str(exc))
        return False

    title = tr("Importing {name}…", name=path.name)
    dlg, cb = window._import_progress(title)
    tess, exc = _run_threaded(
        window, lambda p: tessellate(path, max_angle, up_axis, p), cb)
    if exc is not None:
        return fail(dlg, exc)
    parts, count = tess
    if count > CONFIRM_TRIANGLES:
        dlg.close()
        if not _confirm_heavy(window, count):
            return False
        dlg, cb = window._import_progress(title)
    meshes, exc = _run_threaded(
        window, lambda p: build_parts(parts, merge_coplanar, p), cb)
    if exc is not None:
        return fail(dlg, exc)
    cmd = SnapshotImport(lambda scene: add_step_parts(scene, path, meshes))
    try:
        app.viewport.history.execute(cmd)
    except Exception as err:  # noqa: BLE001 — shown to the user
        return fail(dlg, err)
    window._prepare_import_display(cmd, cb)
    dlg.close()
    app.viewport.notify_scene_changed()
    app.viewport.update()
    window.statusBar().showMessage(
        tr("Imported {name}: {n} parts", name=path.name, n=len(meshes)),
        3000)
    return True


def setup(app):
    app.add_menu_action(
        "Import STEP…", lambda: import_step(app),
        tip="Bring in a STEP (.step/.stp) CAD model, one group per part.")
    # Double-click / Open Recent / command line: import into the model.
    for suffix in (".step", ".stp"):
        app.add_file_opener(suffix, lambda p: import_step(app, p))
