# MitoVerse Design

Decision record for the generalist 3D-mitochondria benchmark. **Code repo**
(`PytorchConnectomics/mitoverse`, this repo) holds ingestion/loader/adapter; **data repo**
(`pytc/MitoVerse` on HuggingFace, cluster path `/projects/weilab/dataset/mitoverse`) holds the zarr
volumes + splits. Benchmark rationale: `pytorch_connectomics`-adjacent `plan.md`.

## Problem

The same datasets existed three times, three ways: `pytc/MitoEM` (h5), `pytc/MitoEM2.0` (nnU-Net
NIfTI, **semantic**), `pytc/MitoLE` (h5, **instance**). Three formats, three split conventions,
constant drift. MitoVerse replaces them with one minimal master.

## Decisions

1. **One format: zarr.** Each volume is one zarr DirectoryStore with `img` (uint8 ZYX) and `mito`
   (instance, 0=bg). Chosen because it is chunked, self-describing (metadata in `.zattrs`), and
   **PyTorchConnectomics loads it directly** — `image: <vol>.zarr/img`, `label: <vol>.zarr/mito`
   (verified: `read_volume` and `LazyZarrVolumeDataset` both open the sub-arrays; pytc env zarr 2.18).
   DirectoryStore, not `.zarr.zip` — PyTC's `_split_zarr_path` only resolves a directory store + subkey.
2. **Minimal: instance labels only.** No stored semantic/boundary — `semantic = mito>0` is one line,
   so consumers derive it. No nnU-Net/h5 copies in the master; converting out is a few lines (their job).
3. **Original chunk, no physical splitting.** One zarr per source volume; never tiled or pre-cut into
   train/val/test. Splits are JSON overlays (`splits/<name>.json`) referencing whole volumes.
   Within-volume **region** splits (e.g. MitoEM z-ranges, the ME2-Pyra tiles) are expressed as a
   `regions` field and honored once PyTorchConnectomics gains region support — until then the volume
   stays whole.
4. **Reuse, don't redo.** Ingestion converts existing `mito/MitoLE` h5 as-is (no re-annotation),
   standardizing only: raw→uint8, axis order ZYX, background=0, voxel size in nm.
5. **Two repos.** Code (versioned on GitHub) is decoupled from data (LFS on HuggingFace). The loader
   resolves volumes from the data repo by id/convention.

## Layout inside one volume

```
data/<dataset>/<volume>.zarr/
  img    uint8   (Z,Y,X)
  mito   uint16  0=bg, 1..N         # uint8 when <256 instances
  mask   uint8   (optional)         # ignore region
  .zattrs["mitoverse"]              # volume_id, dataset_id, voxel_nm, modality, species, tissue,
                                    #   shape_zyx, n_instances, provenance, normalization, source
```

## Pipeline

- `scripts/ingest.py` — h5/tiff pair → one zarr in the data repo (`--out-root`) + `catalog.json`.
- `scripts/to_pytc.py` — a `splits/*.json` benchmark → the `cfg.data.{train,val,test}` block PyTC reads.
- `mitoverse.io.load(volume_id)` — convenience array access for analysis/QC.

## Verified end-to-end (pilot: lucchi + guay21)

ingest h5 → zarr; `read_volume(".../vol0.zarr/img")` → (50,800,800) uint8; `LazyZarrVolumeDataset`
samples `(1,16,128,128)` patches from `img`+`mito`; `to_pytc.py guay21.json` emits the PyTC data
config. Instance counts match the MitoLE README (lucchi 70, guay21 279).

## Open / deferred

- PyTC **region** support for within-volume train/val/test (then fill `regions` in split JSONs).
- Ingest the rest of MitoLE; reproduce `mitoEM.json` / `cellmap.json` like `mitoEM2.0.json`.
- BetaSeg/Müller'20 (`mito/xie23`) — in MitoEM2.0 but missing an instance master; convert it.
- zarr v3 sharding for very large working volumes (blocked: pytc env is zarr 2.18).
