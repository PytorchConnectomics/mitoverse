#!/usr/bin/env python3
"""Batch-ingest every `<vol>_im.h5` / `<vol>_mito.h5` (+ optional `_mask.h5`) pair in a MitoLE
dataset directory, with shared metadata. Thin loop over scripts/ingest.py.

  python ingest_dir.py --src-dir /projects/weilab/dataset/mito/MitoLE/guay21 --dataset guay21 \
      --voxel 10,10,50 --modality SBF-SEM --species Human --tissue platelet [--dry-run]
"""
from __future__ import annotations
import argparse, glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src-dir", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--voxel", required=True)
    p.add_argument("--modality", default=""); p.add_argument("--species", default="")
    p.add_argument("--tissue", default=""); p.add_argument("--provenance", default="native_instance")
    p.add_argument("--out-root", default=ingest.DEFAULT_OUT)
    p.add_argument("--relabel", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    ims = sorted(p for ext in ("h5", "tiff", "tif") for p in glob.glob(os.path.join(a.src_dir, f"*_im.{ext}")))
    if not ims:
        print(f"[{a.dataset}] no *_im.(h5|tiff|tif) in {a.src_dir}"); return
    n_ok = n_skip = 0
    for im in ims:
        base, ext = im.rsplit("_im.", 1)               # split off the _im.<ext> suffix
        vol = os.path.basename(base)
        mito = f"{base}_mito.{ext}"
        mask = f"{base}_mask.{ext}"
        if not os.path.exists(mito):
            print(f"  skip {vol}: no _mito.h5"); n_skip += 1; continue
        has_mask = os.path.exists(mask)
        if a.dry_run:
            print(f"  {a.dataset}_{vol:32s} im+mito{'+mask' if has_mask else '':5s} "
                  f"({os.path.getsize(im)/1e6:.0f}MB)")
            n_ok += 1; continue
        argv2 = ["--dataset", a.dataset, "--volume", vol, "--im", im, "--mito", mito,
                 "--voxel", a.voxel, "--modality", a.modality, "--species", a.species,
                 "--tissue", a.tissue, "--provenance", a.provenance, "--out-root", a.out_root]
        if has_mask:
            argv2 += ["--mask", mask]
        if a.relabel:
            argv2 += ["--relabel"]
        try:
            ingest.main(argv2); n_ok += 1
        except Exception as e:
            print(f"  ERROR {vol}: {e}"); n_skip += 1
    print(f"[{a.dataset}] {'planned' if a.dry_run else 'ingested'} {n_ok}, skipped {n_skip}")


if __name__ == "__main__":
    main()
