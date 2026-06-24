#!/usr/bin/env python3
"""Streaming ingest for LARGE whole volumes (e.g. MitoEM): copy HDF5 -> zarr slab-by-slab so the
full array (tens of GB) never loads into RAM. Same output contract as ingest.py.

  python ingest_stream.py --dataset wei20 --volume mitoEM-H \
      --img  /projects/weilab/dataset/mito/mitoEM/EM30-H/im_train_val.h5 \
      --mito /projects/weilab/dataset/mito/mitoEM/EM30-H/mito-v2.h5 --zmax 500 \
      --voxel 8,8,30 --modality ssSEM --species Human --tissue "temporal lobe (L2)"
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np, h5py, zarr
from numcodecs import Blosc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest  # noqa: E402  (chunks_for, update_index, DEFAULT_OUT)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True); p.add_argument("--volume", required=True)
    p.add_argument("--img", required=True); p.add_argument("--mito", required=True)
    p.add_argument("--voxel", required=True)
    p.add_argument("--modality", default=""); p.add_argument("--species", default="")
    p.add_argument("--tissue", default=""); p.add_argument("--provenance", default="native_instance")
    p.add_argument("--zmax", type=int, default=0, help="take only first N z-slices (0 = all)")
    p.add_argument("--slab", type=int, default=32); p.add_argument("--out-root", default=ingest.DEFAULT_OUT)
    a = p.parse_args(argv)

    vid = f"{a.dataset}_{a.volume}"
    vx, vy, vz = (float(t) for t in a.voxel.split(","))
    fi = h5py.File(a.img, "r"); di = fi[list(fi.keys())[0]]
    fm = h5py.File(a.mito, "r"); dm = fm[list(fm.keys())[0]]
    assert di.shape[1:] == dm.shape[1:], f"XY mismatch {di.shape} vs {dm.shape}"
    Z = min(di.shape[0], dm.shape[0])
    if a.zmax:
        Z = min(Z, a.zmax)
    shape = (Z,) + tuple(di.shape[1:])
    print(f"[{vid}] streaming {shape} img/{di.dtype} + mito/{dm.dtype} (slab={a.slab})")

    zrel = os.path.join("data", a.dataset, f"{a.volume}.zarr")
    path = os.path.join(a.out_root, zrel)
    if os.path.exists(path):
        import shutil; shutil.rmtree(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
    ch = ingest.chunks_for(shape)
    root = zarr.group(store=zarr.DirectoryStore(path), overwrite=True)
    aimg = root.create_dataset("img",  shape=shape, chunks=ch, dtype="uint8",  compressor=comp)
    amito = root.create_dataset("mito", shape=shape, chunks=ch, dtype="uint16", compressor=comp)

    ids = set(); idmax = 0
    for z0 in range(0, Z, a.slab):
        z1 = min(z0 + a.slab, Z)
        im = di[z0:z1]
        if im.dtype != np.uint8:                       # MitoEM is uint8; guard anyway
            im = np.clip(im, 0, 255).astype(np.uint8)
        aimg[z0:z1] = im
        mt = dm[z0:z1]
        m = int(mt.max()); idmax = max(idmax, m)
        assert m < 65536, f"instance id {m} exceeds uint16 at z={z0}; needs relabel/uint32"
        amito[z0:z1] = mt.astype(np.uint16)
        ids.update(int(x) for x in np.unique(mt) if x)
        print(f"  z {z1}/{Z}  ({len(ids)} instances so far)", flush=True)

    meta = {
        "volume_id": vid, "dataset_id": a.dataset,
        "modality": a.modality, "species": a.species, "tissue": a.tissue,
        "voxel_nm": [vx, vy, vz], "shape_zyx": list(shape),
        "label_type": "instance", "n_instances": len(ids),
        "provenance": a.provenance, "normalization": f"{di.dtype}->uint8(passthrough)",
        "source": {"img": os.path.abspath(a.img), "mito": os.path.abspath(a.mito),
                   "zmax": a.zmax or None},
    }
    root.attrs["mitoverse"] = meta
    zarr.consolidate_metadata(root.store)
    ingest.update_index(a.out_root, vid, meta, zrel)
    fi.close(); fm.close()
    print(f"[{vid}] DONE -> {zrel} ({len(ids)} instances, max id {idmax})")


if __name__ == "__main__":
    main()
