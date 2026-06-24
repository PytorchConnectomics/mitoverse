# mitoverse (code)

Build + access tooling for the **MitoVerse** 3D-EM mitochondria benchmark. Data + splits live in a
separate HuggingFace repo, [`pytc/MitoVerse`](https://huggingface.co/datasets/pytc/MitoVerse)
(cluster: `/projects/weilab/dataset/mitoverse`). See `DESIGN.md` for the format decision and
`.agent/plan.md` for the benchmark rationale. Current build: **212 volumes, 13 datasets, ~29.8k mitochondria.**

```
mitoverse/io.py          load(volume_id) -> Volume(img, mito, mask, meta)
catalog/datasets.yaml    per-dataset source metadata (modality/species/voxel/license)
scripts/
  ingest.py              one HDF5/TIFF image+instance pair -> one zarr in the data repo
  ingest_dir.py          batch-ingest every *_im/_mito(/_mask) pair in a directory
  ingest_stream.py       slab-by-slab ingest for huge volumes (e.g. MitoEM), no full RAM load
  to_pytc.py             a splits/*.json benchmark -> PyTorchConnectomics cfg.data block
  rebuild_index.py       regenerate data-repo catalog.json from every store's .zattrs
  build_web.py           generate docs/index.html — the multi-tab dataset explorer
docs/index.html           self-contained catalog explorer (All / by modality / organism / resolution / tissue / dataset / provenance)
```

## Layout & conventions

One zarr DirectoryStore per original-chunk volume: `data/<dataset>/<volume>.zarr/` with arrays `img`
(uint8 ZYX) and `mito` (instance, 0=bg), metadata in `.zattrs["mitoverse"]`. Datasets are
`<author><yy>` folders; OpenOrganelle/COSEM volumes live in `openorganelle/` and their annotation
provenance is carried by split membership (`splits/cellmap.json` vs `splits/mitoem2.0.json`).
Benchmarks are split overlays in the data repo's `splits/`, never duplicated data.

## Use

```bash
# add a volume (reuses existing curated h5/tiff; no re-annotation)
python scripts/ingest.py --dataset guay21 --volume vol0 \
    --im .../guay21/vol0_im.h5 --mito .../guay21/vol0_mito.h5 \
    --voxel 10,10,50 --modality SBF-SEM --species Human --tissue platelet

# batch a whole source dir, then refresh the index
python scripts/ingest_dir.py --src-dir .../betaSeg --dataset muller20 --voxel 16,16,16 --modality FIB-SEM --species Mouse --tissue pancreas
python scripts/rebuild_index.py

# a benchmark split -> PyTC data config
python scripts/to_pytc.py /projects/weilab/dataset/mitoverse/splits/mitoem2.0.json

# regenerate the explorer website
python scripts/build_web.py
```

```python
from mitoverse import load
v = load("guay21_vol0")        # v.img, v.mito, v.semantic (derived), v.meta
```

PyTorchConnectomics reads the stores natively — `image: <vol>.zarr/img`, `label: <vol>.zarr/mito`.

## Environments

- `pytc` conda env (zarr **2.18**, h5py, numcodecs, tifffile) runs everything except v3 OME-Zarr reads.
- Reading Peng's `MitoEM2.0_OMEZarr` (Zarr **v3** multiscale) needs a separate env:
  `conda create -n zarrv3 -c conda-forge "zarr>=3" numcodecs h5py tifffile`. Don't put zarr 3 in `pytc`.
