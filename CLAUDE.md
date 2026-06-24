# CLAUDE.md — mitoverse **code** repo

Build/access tooling for the MitoVerse benchmark. GitHub `PytorchConnectomics/mitoverse`, nested in
`pytorch_connectomics/lib/`. The **data** lives elsewhere — HuggingFace `pytc/MitoVerse`, cluster
path `/projects/weilab/dataset/mitoverse`. Keep code here; keep data/splits/zarr there.

## Design in one line

One zarr per **original-chunk** volume (`img` uint8 + `mito` instance + `.zattrs` metadata);
**instance labels only** (semantic is derived by consumers); splits are JSON overlays, never data
copies; **reuse** `mito/MitoLE` h5 as-is. Full rationale in `DESIGN.md`.

## Invariants — do not break

- DirectoryStore `.zarr/` (PyTC needs it), arrays named `img` + `mito` (+ optional `mask`). Not zip.
- `ingest.py` writes to the data repo via `--out-root` (default `/projects/weilab/dataset/mitoverse`)
  and updates the data repo's root `catalog.json`. It never re-segments — labels come from curated sources.
- No tiling, no physical train/val/test split, no stored semantic. One source volume → one store.
- `to_pytc.py` is the only bridge to PyTC config; splits are *defined* in the data repo's `splits/`.
- OpenOrganelle/COSEM volumes → `openorganelle/` folder (by imaging volume); annotation provenance is
  carried by split membership (`cellmap.json` = CellMap crops, `mitoem2.0.json` = lab self-annotated).
- After any move/rename, run `rebuild_index.py` then `build_web.py`.

## Scripts

`ingest.py` (one pair) · `ingest_dir.py` (batch a dir) · `ingest_stream.py` (huge volumes, slab-by-slab) ·
`to_pytc.py` (split→PyTC cfg) · `rebuild_index.py` (catalog.json from .zattrs) · `build_web.py`
(→ `docs/index.html` explorer).

## Environment

`pytc` conda env (zarr 2.18, h5py, numcodecs, nibabel, tifffile) runs everything except v3 reads.
Reading Peng's `MitoEM2.0_OMEZarr` (Zarr v3 multiscale) needs a separate `zarrv3` env
(`conda create -n zarrv3 -c conda-forge "zarr>=3" ...`). Don't `pip install zarr>=3` into `pytc`
(conflicts with `cellmap-flow`/`xarray-ome-ngff`).

## Status / TODO

- `DONE` ingest pipeline (h5/tiff/stream), loader, to_pytc, index, web explorer; 212 vols / 13 datasets.
- `DONE` openorganelle reorg; `cellmap.json` + `mitoem2.0.json` overlays; kunduri22 (v3 OME-Zarr).
- See the data repo's `TODO.md` for open questions (kunduri22 gt, MICrONS1 stitch, voxel TBDs, license,
  PyTC regions, HF push).

## Status vocabulary

`DONE` / `CURRENT` / `TODO` / `BLOCKED` (per `pytc-agent/standards.md`).
