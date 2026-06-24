"""Minimal access to a MitoVerse volume store.

Each volume is one zarr DirectoryStore with `img` (uint8) and `mito` (instance) arrays plus a
`.zattrs["mitoverse"]` metadata block. This loader is a convenience for analysis/QC; training reads
the same `<vol>.zarr/img` and `<vol>.zarr/mito` paths directly through PyTorchConnectomics.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field

import numpy as np

DATA_ROOT = os.environ.get("MITOVERSE_ROOT", "/projects/weilab/dataset/mitoverse")


@dataclass
class Volume:
    img: np.ndarray
    mito: np.ndarray | None = None
    mask: np.ndarray | None = None
    meta: dict = field(default_factory=dict)

    @property
    def semantic(self):
        return None if self.mito is None else (self.mito > 0).astype(np.uint8)

    def __repr__(self):
        n = 0 if self.mito is None else int(self.mito.max())
        return f"<Volume {self.meta.get('volume_id','?')} img{self.img.shape}/{self.img.dtype} n_inst={n}>"


def load_zarr(store_path) -> Volume:
    """Load a volume directly from its .zarr store path."""
    import zarr
    g = zarr.open_group(store_path, mode="r")
    arr = lambda k: g[k][:] if k in g else None
    return Volume(img=arr("img"), mito=arr("mito"), mask=arr("mask"),
                  meta=dict(g.attrs.get("mitoverse", {})))


def load(volume_id, data_root=None) -> Volume:
    """Load a volume by id, resolving its store from catalog/volumes.json (or by convention)."""
    data_root = data_root or DATA_ROOT
    idx_path = os.path.join(data_root, "catalog.json")
    zrel = None
    if os.path.exists(idx_path):
        idx = json.load(open(idx_path))
        if volume_id in idx:
            zrel = idx[volume_id]["zarr"]
    if zrel is None:                                  # convention: <dataset>_<vol> -> data/<dataset>/<vol>.zarr
        ds, _, vol = volume_id.partition("_")
        zrel = os.path.join("data", ds, f"{vol}.zarr")
    return load_zarr(os.path.join(data_root, zrel))
