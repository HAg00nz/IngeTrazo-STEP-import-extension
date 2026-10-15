# IngeTrazo-STEP-import-extension

Import STEP CAD models (`.step` / `.stp`, AP203 / AP214 / AP242) into
[IngeTrazo](https://github.com/ingelibre/ingetrazo).

- **Extensions ▸ Import STEP…**, or open/double-click a `.step` file.
- The file lands as one group named after the file, as one undo step.
- Units are read from the STEP file and converted to metres.
- *Curve quality* (coarse / normal / fine) sets how finely curved surfaces
  are tessellated; *merge coplanar triangles* turns each flat CAD face back
  into one IngeTrazo face so it can be pushed/pulled.

STEP is tessellated by OpenCASCADE through
[cascadio](https://github.com/trimesh/cascadio) (MIT), vendored into
`step_import/_vendor/`; the resulting GLB is read with IngeTrazo's own glTF
reader.

Tested with IngeTrazo 0.5.8 (plugin API 2, which is not stable yet).

## Install (development)

```sh
scripts/fetch-vendor.sh   # downloads cascadio into step_import/_vendor/
scripts/install-dev.sh    # links step_import/ into IngeTrazo's plugins folder
```

Restart IngeTrazo. The Flatpak build is detected automatically.

For Windows or macOS, fetch the matching wheel, e.g.
`CASCADIO_PLATFORM=win_amd64 scripts/fetch-vendor.sh`, and copy
`step_import/` to `%APPDATA%\ingetrazo\plugins\`.

## Check

```sh
scripts/smoke.sh part.step [coarse|normal|fine]
```

Parses the file headlessly with the installed IngeTrazo Flatpak and prints
face count, size in metres and time.

## License

GPL-3.0-or-later, like IngeTrazo. The vendored cascadio is MIT.
