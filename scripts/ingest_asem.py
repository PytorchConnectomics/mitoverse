#!/usr/bin/env python3
"""Ingest ASEM mitochondria volumes (Gallusser/Kirchhausen, JCB 2022; doi:10.1083/jcb.202208005)
into MitoVerse.

Source: public Quilt/S3 bucket `s3://asem-project` (anonymous), zarr format. Of the 36 datasets,
six carry mito labels: 2E, 3A, 46, 58, 61, 64 (discovered by scanning volumes/labels/mito).

ASEM labels are SEMANTIC (binary) masks -> converted to instances with cc3d (26-conn). A few are
already stored as uint32; those are relabeled contiguous instead. Each label array is positioned in
the raw via a physical-nm `offset` attr; some are sub-crops and some overrun the raw bounds (the
"inconsistent" cells), so raw and label are aligned by their global nm boxes and clipped to the
intersection, then tightened to the annotated bounding box.

  out: <out-root>/data/asem/<cell>.zarr   img(uint8 ZYX) + mito(uintN instance) + .zattrs[mitoverse]

Run:  python ingest_asem.py --vols 2E 3A 46 58 61 64        (or --vol 46 for one)
"""
from __future__ import annotations
import argparse, os
import numpy as np

OUT_ROOT = "/projects/weilab/dataset/mitoverse"
DATASET  = "asem"
BUCKET   = "asem-project"
MITO_CELLS = ["2E", "3A", "46", "58", "61", "64"]
ZSCAN = 64  # z-slab for streaming bbox scan


def open_cell(cell):
    import s3fs, zarr
    fs = s3fs.S3FileSystem(anon=True)
    base = f"{BUCKET}/datasets/{cell}/{cell}.zarr"
    g = zarr.open(s3fs.S3Map(root=base, s3=fs, check=False), mode="r")
    return g["volumes/raw"], g["volumes/labels/mito"]


def vox_offset(arr):
    a = dict(arr.attrs)
    off = np.array(a.get("offset", [0, 0, 0]))
    res = np.array(a.get("resolution", [1, 1, 1]))
    return (off // res).astype(np.int64), res


def nonzero_bbox_streaming(mito, lz0, lz1, ly0, ly1, lx0, lx1, log):
    """Tight nonzero bbox of mito within the given label-local window, scanned in z-slabs."""
    zmin = ymin = xmin = None
    zmax = ymax = xmax = -1
    for z0 in range(lz0, lz1, ZSCAN):
        z1 = min(z0 + ZSCAN, lz1)
        blk = mito[z0:z1, ly0:ly1, lx0:lx1]
        nz = np.argwhere(blk > 0)
        if nz.size == 0:
            continue
        zz = nz[:, 0] + z0; yy = nz[:, 1] + ly0; xx = nz[:, 2] + lx0
        zmin = zz.min() if zmin is None else min(zmin, zz.min())
        ymin = yy.min() if ymin is None else min(ymin, yy.min())
        xmin = xx.min() if xmin is None else min(xmin, xx.min())
        zmax = max(zmax, zz.max()); ymax = max(ymax, yy.max()); xmax = max(xmax, xx.max())
    if zmin is None:
        return None
    return int(zmin), int(zmax) + 1, int(ymin), int(ymax) + 1, int(xmin), int(xmax) + 1


def pick_factor(res_nm, crop_shape, target=16, min_long=200):
    """Downsample factor toward ~target nm (x2 or x4), but step down (4->2->1) so the OUTPUT
    long side stays >= min_long voxels. Tiny crops (e.g. 200^3 @4nm) thus keep native res."""
    f = min((2, 4), key=lambda x: abs(res_nm * x - target))
    long = max(crop_shape)
    while f > 1 and long // f < min_long:
        f //= 2
    return f


def cc3d_instance(mask16, log):
    """Binary 16nm mask -> cc3d (26-conn) instances, contiguous, uint16/uint32."""
    import cc3d, fastremap
    inst = cc3d.connected_components((mask16 > 0).astype(np.uint8), connectivity=26)
    inst, _ = fastremap.renumber(inst, in_place=True)
    n = int(inst.max())
    dt = np.uint16 if n <= 65535 else np.uint32
    return inst.astype(dt), n


def ingest_cell(cell, log=print):
    import zarr
    from numcodecs import Blosc
    raw, mito = open_cell(cell)
    ro, rres = vox_offset(raw)
    lo, lres = vox_offset(mito)
    res = int(rres[0])
    rs = np.array(raw.shape); ls = np.array(mito.shape)
    # global nm-voxel boxes; intersect
    g0 = np.maximum(ro, lo); g1 = np.minimum(ro + rs, lo + ls)
    if np.any(g1 <= g0):
        log(f"[{cell}] raw/label boxes do not overlap; skip"); return None
    # label-local window of the intersection
    lz0, ly0, lx0 = (g0 - lo); lz1, ly1, lx1 = (g1 - lo)
    log(f"[{cell}] raw{tuple(rs)}@{ro.tolist()} mito{tuple(ls)}@{lo.tolist()} res={res}nm "
        f"-> overlap label-local z[{lz0}:{lz1}] y[{ly0}:{ly1}] x[{lx0}:{lx1}]")
    bb = nonzero_bbox_streaming(mito, lz0, lz1, ly0, ly1, lx0, lx1, log)
    if bb is None:
        log(f"[{cell}] no nonzero mito in overlap; skip"); return None
    bz0, bz1, by0, by1, bx0, bx1 = bb
    f = pick_factor(res, (bz1 - bz0, by1 - by0, bx1 - bx0))
    res16 = res * f
    Z2, Y2, X2 = (bz1 - bz0) // f, (by1 - by0) // f, (bx1 - bx0) // f
    rz0, ry0, rx0 = (np.array([bz0, by0, bx0]) + lo - ro)   # raw-local origin of the crop
    raw16 = np.empty((Z2, Y2, X2), np.uint8)
    mask16 = np.zeros((Z2, Y2, X2), bool)
    for k in range(Z2):                                     # downsample slab-wise (memory-bounded)
        mz = bz0 + k * f
        mslab = np.asarray(mito[mz:mz + f, by0:by0 + f * Y2, bx0:bx0 + f * X2]) > 0
        rslab = np.asarray(raw[rz0 + k * f:rz0 + k * f + f, ry0:ry0 + f * Y2,
                               rx0:rx0 + f * X2]).astype(np.uint16)
        raw16[k] = rslab.reshape(f, Y2, f, X2, f).mean(axis=(0, 2, 4)).astype(np.uint8)
        mask16[k] = mslab.reshape(f, Y2, f, X2, f).any(axis=(0, 2, 4))   # max-pool: keep any mito
    inst, n = cc3d_instance(mask16, log)
    raw_u8 = raw16
    log(f"[{cell}] native crop {(bz1-bz0,by1-by0,bx1-bx0)}@{res}nm -> x{f} -> "
        f"{inst.shape}@{res16}nm  instances={n}  dtype={inst.dtype}")

    zpath = os.path.join(OUT_ROOT, "data", DATASET, f"{cell}.zarr")
    if os.path.exists(zpath):
        import shutil; shutil.rmtree(zpath)
    os.makedirs(os.path.dirname(zpath), exist_ok=True)
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
    root = zarr.group(store=zarr.DirectoryStore(zpath), overwrite=True)
    ch = (min(64, inst.shape[0]), min(512, inst.shape[1]), min(512, inst.shape[2]))
    root.create_dataset("img",  data=raw_u8, chunks=ch, compressor=comp)
    root.create_dataset("mito", data=inst,   chunks=ch, compressor=comp)
    meta = {
        "volume_id": f"{DATASET}_{cell}", "dataset_id": DATASET,
        "modality": "FIB-SEM", "species": "", "tissue": f"cell ({cell})",
        "voxel_nm": [float(res16)] * 3, "shape_zyx": list(inst.shape),
        "label_type": "instance", "n_instances": n,
        "provenance": "original",
        "normalization": f"uint8(mean x{f} from {res}nm)",
        "label_note": f"ASEM semantic mito: max-pool x{f} -> cc3d-26 instances @ {res16}nm",
        "source": {"bucket": f"s3://{BUCKET}/datasets/{cell}/{cell}.zarr",
                   "doi": "10.1083/jcb.202208005",
                   "native_res_nm": res, "downsample_factor": f,
                   "label_global_offset_vox": (np.array([bz0, by0, bx0]) + lo).tolist()},
    }
    root.attrs["mitoverse"] = meta
    zarr.consolidate_metadata(root.store)
    log(f"[{cell}] WROTE {zpath} ({inst.shape}, {n} inst)")
    return meta


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--vols", nargs="*", default=None)
    p.add_argument("--vol", default=None)
    a = p.parse_args(argv)
    vols = [a.vol] if a.vol else (a.vols or MITO_CELLS)
    for v in vols:
        try:
            ingest_cell(v)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[{v}] FAILED: {e}")


if __name__ == "__main__":
    main()
