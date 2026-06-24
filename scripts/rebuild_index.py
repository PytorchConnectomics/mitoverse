#!/usr/bin/env python3
"""Rebuild catalog/volumes.json from scratch by scanning every data/<dataset>/<vol>.zarr store's
.zattrs["mitoverse"] block. Use after moving/renaming/merging stores so the index matches reality.

  python rebuild_index.py [data-root]
"""
import glob, json, os, sys
import zarr

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/projects/weilab/dataset/mitoverse"
idx = {}
for store in sorted(glob.glob(os.path.join(ROOT, "data", "*", "*.zarr"))):
    try:
        g = zarr.open_group(store, mode="r")
        m = dict(g.attrs.get("mitoverse", {}))
        if not m:
            print("  no mitoverse attrs:", store); continue
        vid = m.get("volume_id") or os.path.basename(store)[:-5]
        m["zarr"] = os.path.relpath(store, ROOT)
        idx[vid] = m
    except Exception as e:
        print("  skip", store, e)
json.dump(idx, open(os.path.join(ROOT, "catalog.json"), "w"), indent=2, sort_keys=True)
print(len(idx), "volumes indexed")
