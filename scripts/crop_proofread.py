#!/usr/bin/env python3
"""Center-crop MitoVerse raw-prediction volumes into proofreading seeds (round 2).

For each FINALIZED volume in <root>/tmp/data_raw/<dataset>/<vol>.zarr, extract the centered
CROP**3 cube of img (uint8) + mito (instance ids), run cc3d (26-connectivity) on the mito crop
to re-derive clean, contiguous connected-component instance ids, and write the pair to
<root>/tmp/data_proofread/<dataset>/<vol>.zarr as an UNPROOFREAD proofreading target.

Partial (still-ingesting) volumes are skipped: their center z-range may not be written yet
(the array is pre-allocated full-shape and zero-filled until each z-chunk lands).

  python crop_proofread.py --dataset parlakgul24                      # all finalized vols
  python crop_proofread.py --dataset parlakgul24 --vols obese_lacz    # one vol
  python crop_proofread.py --dataset parlakgul24 --crop 1024          # cube edge (default 1024)
"""
from __future__ import annotations
import argparse, glob, os, shutil
import numpy as np, zarr, cc3d
from numcodecs import Blosc

ROOT = "/projects/weilab/dataset/mitoverse"
CHUNK = (64, 512, 512)


def center_span(n, c):
    """Centered [start, stop) of length min(c, n) within an axis of size n."""
    if n <= c:
        return 0, n
    s = (n - c) // 2
    return s, s + c


def crop_one(src, dst, crop, log=print):
    g = zarr.open_group(src, "r")
    meta = dict(g.attrs.get("mitoverse", {}))
    img, mito = g["img"], g["mito"]
    Z, Y, X = img.shape
    z0, z1 = center_span(Z, crop)
    y0, y1 = center_span(Y, crop)
    x0, x1 = center_span(X, crop)
    log(f"  crop z[{z0}:{z1}] y[{y0}:{y1}] x[{x0}:{x1}] from {img.shape}")
    im = img[z0:z1, y0:y1, x0:x1]
    lb = mito[z0:z1, y0:y1, x0:x1]
    cc = cc3d.connected_components(lb, connectivity=26)
    N = int(cc.max())
    dt = np.uint16 if N <= 65535 else np.uint32
    cc = cc.astype(dt)
    log(f"  cc3d 26-conn -> {N} instances ({np.dtype(dt).name})")
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    root = zarr.group(store=zarr.DirectoryStore(dst), overwrite=True)
    root.create_dataset("img",  data=im, chunks=CHUNK, compressor=comp)
    root.create_dataset("mito", data=cc, chunks=CHUNK, compressor=comp)
    meta.update({
        "n_instances": N,
        "mito_dtype": np.dtype(dt).name,
        "crop": {"size": [int(z1 - z0), int(y1 - y0), int(x1 - x0)],
                 "offset_zyx": [int(z0), int(y0), int(x0)],
                 "source_shape": [int(Z), int(Y), int(X)]},
        "label_quality": ("UNPROOFREAD — center crop of automated prediction; cc3d 26-conn "
                          "relabel; proofreading target (round 2)"),
    })
    root.attrs["mitoverse"] = meta
    zarr.consolidate_metadata(root.store)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--vols", nargs="*", default=None)
    ap.add_argument("--crop", type=int, default=1024)
    ap.add_argument("--root", default=ROOT)
    a = ap.parse_args()
    src_dir = os.path.join(a.root, "tmp", "data_raw", a.dataset)
    dst_dir = os.path.join(a.root, "tmp", "data_proofread", a.dataset)
    os.makedirs(dst_dir, exist_ok=True)
    vols = a.vols or [os.path.basename(p)[:-5] for p in sorted(glob.glob(f"{src_dir}/*.zarr"))]
    for v in vols:
        src = os.path.join(src_dir, f"{v}.zarr")
        if not os.path.exists(src):
            print(f"[{v}] SKIP — not found at {src}")
            continue
        if not zarr.open_group(src, "r").attrs.get("mitoverse"):
            print(f"[{v}] SKIP — partial/unfinalized (no mitoverse attrs; center may be unwritten)")
            continue
        print(f"[{v}] cropping center {a.crop}^3 …")
        crop_one(src, os.path.join(dst_dir, f"{v}.zarr"), a.crop)
        print(f"[{v}] done -> {dst_dir}/{v}.zarr")


if __name__ == "__main__":
    main()
