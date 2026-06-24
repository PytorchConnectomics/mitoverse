#!/usr/bin/env python3
"""Ingest one ORIGINAL-CHUNK volume (HDF5 image + instance labels) into the MitoVerse data repo.

Writes a self-describing zarr store, one per source volume — no tiling, no train/val/test
splitting (regions are specified later, in PyTorchConnectomics):

  <out-root>/data/<dataset>/<volume>.zarr/      DirectoryStore, loadable by PyTC as `<vol>.zarr/img`
      img    uint8   (Z,Y,X)          raw image
      mito   uintN   0=bg, instance   instance ground truth  (semantic is derived by consumers)
      mask   uint8   (optional)       ignore mask
      .zattrs["mitoverse"]            voxel_nm, modality, species, tissue, provenance, source

Reuses existing curated labels as-is (no re-segmentation). Standardizes: raw->uint8, ZYX, bg=0.
Default out-root is the HF data repo at /projects/weilab/dataset/mitoverse.

Example:
  python ingest.py --dataset guay21 --volume vol0 \
      --im /projects/weilab/dataset/mito/MitoLE/guay21/vol0_im.h5 \
      --mito /projects/weilab/dataset/mito/MitoLE/guay21/vol0_mito.h5 \
      --voxel 10,10,50 --modality SBF-SEM --species Human --tissue platelet
"""
from __future__ import annotations
import argparse, json, os
import numpy as np

DEFAULT_OUT = "/projects/weilab/dataset/mitoverse"


def read_h5(path, key=None):
    import h5py
    with h5py.File(path, "r") as f:
        return f[key or list(f.keys())[0]][:]


def read_vol(path, key=None):
    """Read a 3D volume from HDF5, a TIFF stack, or a directory of 2D slices."""
    import os
    p = str(path)
    if os.path.isdir(p):
        import glob, tifffile
        files = sorted(glob.glob(os.path.join(p, "*.tif*")))
        return tifffile.imread(files)
    if p.endswith((".tif", ".tiff")):
        import tifffile
        return tifffile.imread(p)
    if p.endswith((".h5", ".hdf5")):
        return read_h5(p, key)
    raise ValueError(f"unsupported volume format: {p}")


def to_uint8(raw):
    if raw.dtype == np.uint8:
        return raw, "uint8(passthrough)"
    a = raw.astype(np.float32)
    lo, hi = np.percentile(a, [0.5, 99.5])
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max() or 1.0)
    out = np.clip((a - lo) / (hi - lo), 0, 1) * 255.0
    return out.round().astype(np.uint8), f"{raw.dtype}->uint8(p0.5={lo:.0f},p99.5={hi:.0f})"


def relabel_contiguous(seg):
    ids = np.unique(seg); ids = ids[ids != 0]
    lut = np.zeros(int(seg.max()) + 1, dtype=np.uint32); lut[ids] = np.arange(1, len(ids) + 1)
    out = lut[seg]
    return (out.astype(np.uint16) if len(ids) < 65535 else out), len(ids)


def chunks_for(shape):
    z, y, x = shape
    return (min(z, 64), min(y, 512), min(x, 512))


def write_zarr(path, raw, inst, mask, meta):
    import zarr
    from numcodecs import Blosc
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
    if os.path.exists(path):
        import shutil; shutil.rmtree(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    root = zarr.group(store=zarr.DirectoryStore(path), overwrite=True)
    root.create_dataset("img",  data=raw,  chunks=chunks_for(raw.shape),  compressor=comp)
    root.create_dataset("mito", data=inst, chunks=chunks_for(inst.shape), compressor=comp)
    if mask is not None:
        root.create_dataset("mask", data=mask, chunks=chunks_for(mask.shape), compressor=comp)
    root.attrs["mitoverse"] = meta
    zarr.consolidate_metadata(root.store)


def update_index(out_root, vid, meta, zrel):
    idx_path = os.path.join(out_root, "catalog.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    idx[vid] = {**meta, "zarr": zrel}
    json.dump(idx, open(idx_path, "w"), indent=2, sort_keys=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True)
    p.add_argument("--volume", required=True, help="volume_id = <dataset>_<volume>")
    p.add_argument("--im", required=True); p.add_argument("--mito", required=True)
    p.add_argument("--mask", default=None)
    p.add_argument("--voxel", required=True, help="x,y,z nm, e.g. 10,10,50")
    p.add_argument("--modality", default=""); p.add_argument("--species", default="")
    p.add_argument("--tissue", default=""); p.add_argument("--provenance", default="native_instance")
    p.add_argument("--out-root", default=DEFAULT_OUT, help="MitoVerse data repo root")
    p.add_argument("--relabel", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    vid = f"{a.dataset}_{a.volume}"
    vx, vy, vz = (float(t) for t in a.voxel.split(","))
    raw_src = read_vol(a.im); inst_src = read_vol(a.mito)
    assert raw_src.shape == inst_src.shape, f"shape mismatch {raw_src.shape} vs {inst_src.shape}"
    mask = read_vol(a.mask) if a.mask else None

    raw, norm = to_uint8(raw_src)
    if a.relabel:
        inst, n_inst = relabel_contiguous(inst_src.astype(np.int64))
    else:
        inst = inst_src
        n_inst = int(len(np.unique(inst_src)) - (1 if (inst_src == 0).any() else 0))
    if inst.dtype not in (np.uint8, np.uint16, np.uint32):
        inst = inst.astype(np.uint32)

    zrel = os.path.join("data", a.dataset, f"{a.volume}.zarr")
    meta = {
        "volume_id": vid, "dataset_id": a.dataset,
        "modality": a.modality, "species": a.species, "tissue": a.tissue,
        "voxel_nm": [vx, vy, vz], "shape_zyx": list(raw.shape),
        "label_type": "instance", "n_instances": n_inst,
        "provenance": a.provenance, "normalization": norm,
        "source": {"im": os.path.abspath(a.im), "mito": os.path.abspath(a.mito)},
    }
    print(f"[{vid}] raw {raw_src.shape}/{raw_src.dtype} -> {norm}; instances={n_inst}; mask={'yes' if mask is not None else 'no'}")
    if a.dry_run:
        return
    write_zarr(os.path.join(a.out_root, zrel), raw, inst, mask, meta)
    update_index(a.out_root, vid, meta, zrel)
    print(f"[{vid}] wrote {a.out_root}/{zrel}/  (img,mito{',mask' if mask is not None else ''}) + index")


if __name__ == "__main__":
    main()
