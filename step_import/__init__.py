# SPDX-License-Identifier: GPL-3.0-or-later
"""STEP import for IngeTrazo (.step / .stp, AP203 / AP214 / AP242).

STEP is a B-rep format: exact surfaces, not triangles. OpenCASCADE, through
the ``cascadio`` wheel vendored in ``_vendor/``, tessellates it to a GLB in
metres (whatever unit the STEP file was written in), and IngeTrazo's own
GLB reader turns that into a Mesh. Planar CAD faces come out as one face
each when "merge coplanar triangles" is on, so they can be pushed/pulled.

The whole file lands as ONE group named after the file, as one undo step.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "_vendor"

#: Relative linear deflection (fraction of edge length) and angular
#: deflection (radians) handed to OpenCASCADE's mesher.
QUALITIES = {
    "coarse": (0.1, 0.5),
    "normal": (0.03, 0.3),
    "fine": (0.01, 0.2),
}

_SETTINGS_QUALITY = "step_import/quality"
_SETTINGS_MERGE = "step_import/merge_coplanar"


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


def parse_step(path, quality: str = "normal", merge_coplanar: bool = True,
               progress=None):
    """Read the STEP at ``path`` into a new Mesh in metres, Z up.

    Safe to call from a worker thread: it builds a detached Mesh and never
    touches the document."""
    from formats.glb import build_mesh, read_triangles

    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    tol_linear, tol_angular = QUALITIES[quality]
    cascadio = _cascadio()
    with tempfile.TemporaryDirectory(prefix="ingetrazo-step-") as tmp:
        glb = Path(tmp) / "model.glb"
        tick(0.05, "Tessellating STEP…")
        status = cascadio.step_to_glb(
            str(path), str(glb), tol_linear=tol_linear,
            tol_angular=tol_angular, tol_relative=True)
        if status != 0 or not glb.is_file():
            raise ValueError(f"OpenCASCADE could not read {Path(path).name}")
        tick(0.5, "Reading triangles…")
        batches, _js = read_triangles(glb)
    if not batches:
        raise ValueError(f"{Path(path).name} contains no solid or surface "
                         "geometry")
    tick(0.6, "Building mesh…")
    mesh = build_mesh(batches)
    if merge_coplanar:
        from formats.fuse import simplify_mesh
        tick(0.85, "Merging coplanar faces…")
        simplify_mesh(mesh, principal_planes=False)
    return mesh


def add_step_mesh(scene, path, mesh) -> None:
    """Insert a parsed STEP mesh as one group (UI thread only)."""
    from core.group import Group
    scene.groups.append(Group(mesh, name=Path(path).stem[:60]))
    scene.version += 1


def _parse_threaded(window, path, quality, merge_coplanar, cb):
    """Run :func:`parse_step` on a worker, relaying progress to the UI
    thread; returns ``(mesh, exception)``. Bound-method receivers on queued
    connections, as docs/plugins.md asks."""
    from PySide6.QtCore import QEventLoop, QObject, QThread, Qt, Signal

    class _Worker(QObject):
        progressed = Signal(float, str)
        finished = Signal(object, object)

        def run(self):
            try:
                mesh = parse_step(
                    path, quality, merge_coplanar,
                    progress=lambda f, t: self.progressed.emit(f, t))
                self.finished.emit(mesh, None)
            except Exception as exc:  # noqa: BLE001 — reported to caller
                self.finished.emit(None, exc)

    result = {}
    loop = QEventLoop()

    class _Relay(QObject):
        def on_progress(self, fraction, text):
            cb(fraction, text)

        def on_finished(self, mesh, exc):
            result["mesh"], result["exc"] = mesh, exc
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
    return result.get("mesh"), result.get("exc")


def _ask_options(window):
    """Quality and merge options; None when cancelled."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                                   QDialogButtonBox, QFormLayout)
    from core.i18n import tr

    settings = QSettings()
    dialog = QDialog(window)
    dialog.setWindowTitle(tr("Import STEP"))
    form = QFormLayout(dialog)
    quality = QComboBox(dialog)
    quality.addItem(tr("Coarse — fewest faces"), "coarse")
    quality.addItem(tr("Normal"), "normal")
    quality.addItem(tr("Fine — smoothest curves"), "fine")
    idx = quality.findData(str(settings.value(_SETTINGS_QUALITY, "normal")))
    quality.setCurrentIndex(idx if idx >= 0 else 1)
    form.addRow(tr("Curve quality"), quality)
    merge = QCheckBox(tr("Merge coplanar triangles into one face"), dialog)
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
    settings.setValue(_SETTINGS_QUALITY, quality.currentData())
    settings.setValue(_SETTINGS_MERGE, merge.isChecked())
    return quality.currentData(), merge.isChecked()


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
    quality, merge_coplanar = options

    dlg, cb = window._import_progress(
        tr("Importing {name}…", name=path.name))
    mesh, exc = _parse_threaded(window, path, quality, merge_coplanar, cb)
    if exc is None:
        cmd = SnapshotImport(lambda scene: add_step_mesh(scene, path, mesh))
        try:
            app.viewport.history.execute(cmd)
        except Exception as err:  # noqa: BLE001 — shown to the user
            exc = err
    if exc is not None:
        dlg.close()
        QMessageBox.critical(window, tr("Import STEP failed"), str(exc))
        return False
    window._prepare_import_display(cmd, cb)
    dlg.close()
    app.viewport.notify_scene_changed()
    app.viewport.update()
    window.statusBar().showMessage(
        tr("Imported {name}", name=path.name), 3000)
    return True


def setup(app):
    app.add_menu_action(
        "Import STEP…", lambda: import_step(app),
        tip="Bring in a STEP (.step/.stp) CAD model as one group.")
    # Double-click / Open Recent / command line: import into the model.
    for suffix in (".step", ".stp"):
        app.add_file_opener(suffix, lambda p: import_step(app, p))
