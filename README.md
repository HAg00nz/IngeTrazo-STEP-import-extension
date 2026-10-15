# IngeTrazo-STEP-import-extension

Import STEP CAD models (`.step` / `.stp`, AP203 / AP214 / AP242) into
[IngeTrazo](https://github.com/ingelibre/ingetrazo).

- **Extensions ▸ Import STEP…**, or open/double-click a `.step` file.
- The file lands as one group named after the file, with one named group
  per CAD part inside, as one undo step.
- Part colours come from the STEP file. Units are read from it too and
  converted to metres.
- *Curve resolution* is the largest angle between neighbouring facets of a
  curved surface, from 45° (coarse) to 3° (fine). IngeTrazo hides the edges
  between facets flatter than ~32°, so at 30° and finer curves look smooth;
  at 45° the facets show. Fine settings on big assemblies reach millions of
  triangles; above one million the import asks before building.
- *Merge coplanar triangles* turns each flat CAD face back into one
  IngeTrazo face so it can be pushed/pulled (slower on big models).

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
scripts/smoke.sh part.step [max angle in degrees, default 20]
```

Parses the file headlessly with the installed IngeTrazo Flatpak and prints
parts, faces, colours, visible edges, size in metres and time.

## License

GPL-3.0-or-later, like IngeTrazo. The vendored cascadio is MIT.
