#!/usr/bin/env python3
"""Expand a MitoVerse benchmark JSON into a PyTorchConnectomics data config block.

A benchmark file (e.g. splits/mitoEM2.0.json in the data repo) lists which volumes belong to a
benchmark and their role. PyTC consumes per-split lists of `*.zarr/<array>` paths, so this is the
thin adapter between the two — the split is *defined* in the data repo, *consumed* by PyTC here.

Benchmark JSON schema:
  {
    "name": "guay21",
    "arrays": {"image": "img", "label": "mito"},
    "volumes": [
      {"id": "guay21_vol0", "zarr": "data/guay21/vol0.zarr", "split": "train"},
      {"id": "guay21_vol2", "zarr": "data/guay21/vol2.zarr", "split": "test"}
      // future (pending PyTC region support): "regions": {"train": [[z0,z1],[y0,y1],[x0,x1]], ...}
    ]
  }

Usage:
  python to_pytc.py /projects/weilab/dataset/mitoverse/splits/guay21.json [--data-root <dir>]
"""
from __future__ import annotations
import argparse, json, os

SPLITS = ("train", "val", "test")


def build_data_cfg(bench_path, data_root=None):
    bench = json.load(open(bench_path))
    data_root = data_root or os.path.dirname(os.path.dirname(os.path.abspath(bench_path)))
    img_k = bench.get("arrays", {}).get("image", "img")
    lbl_k = bench.get("arrays", {}).get("label", "mito")
    out = {s: {"image": [], "label": [], "regions": []} for s in SPLITS}
    for v in bench["volumes"]:
        s = v.get("split", "train")
        store = v["zarr"] if os.path.isabs(v["zarr"]) else os.path.join(data_root, v["zarr"])
        out[s]["image"].append(f"{store}/{img_k}")
        out[s]["label"].append(f"{store}/{lbl_k}")
        if "regions" in v:                      # forward-compat; honored once PyTC supports regions
            out[s]["regions"].append({"zarr": store, **v["regions"]})
    return {"data": {s: {k: val for k, val in d.items() if val} for s, d in out.items() if d["image"]}}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("benchmark", help="path to a MitoVerse benchmark JSON")
    p.add_argument("--data-root", default=None, help="data repo root (default: parent of splits/)")
    a = p.parse_args(argv)
    cfg = build_data_cfg(a.benchmark, a.data_root)
    try:
        import yaml
        print(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False))
    except ModuleNotFoundError:
        print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
