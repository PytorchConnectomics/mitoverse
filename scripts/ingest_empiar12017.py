#!/usr/bin/env python3
"""Stream EMPIAR-12017 (MBLiver, Parlakgul'24) liver FIB-SEM imagesets, downsample 8nm->16nm
isotropic on the fly, and write self-describing MitoVerse zarr stores.

Per output voxel (2x2x2 block of 8nm input):
  img   = block MEAN  (anti-aliased image downsample)        -> uint8
  mito  = NEAREST     (take the [0,0,0] corner of the block)  -> uint32  (instance ids preserved)

Raw EM is a folder of per-slice TIFFs (range-downloadable, parallel prefetch). Mitochondria
instance labels are a single .zip of 32-bit per-slice TIFFs read via HTTP-range (remotezip);
only the EVEN slice of each z-pair is read since labels use nearest-neighbour in z.

Memory-bounded: processes one 64-slice z-chunk at a time, writing directly to disk-backed zarr.
Resumable: a sidecar `.ingest_progress.json` + `.seen_ids.npy` let an interrupted run continue
at the last completed z-chunk.

Run:
  python ingest_empiar12017.py --vols obese_lacz --max-chunks 1   # smoke test
  python ingest_empiar12017.py --all                              # full run (hours)
"""
from __future__ import annotations
import argparse, io, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

OUT_ROOT = "/projects/weilab/dataset/mitoverse"
DATASET  = "parlakgul24"
B12 = "https://ftp.ebi.ac.uk/empiar/world_availability/12017/data"
B10 = "https://ftp.ebi.ac.uk/empiar/world_availability/10791/data"
S1  = ("Parlakgul - Arruda et al - High resolution 3D imaging of liver subcellular "
       "architecture and its link to metabolic function/FIB-SEM Raw and Segmentation Data")

# raw_dir / mito_zip are given as UNENCODED paths; enc() handles spaces.
VOLS = {
    "lean_fasted": dict(
        raw_dir=f"{B12}/9428 Lean Fasted/Lean_Fasted_9428_raw_8-bit/",
        mito_zip=f"{B12}/9428 Lean Fasted/Lean_Fasted_9428_mitochondria_instance_32-bit.zip",
        z_skip=0, tissue="liver (lean, fasted)"),
    "obese_fasted": dict(
        raw_dir=f"{B12}/8970 Obese Fasted/Obese_Fasted_8970_raw_8-bit/",
        mito_zip=f"{B12}/8970 Obese Fasted/Obese_fasted_8970_mitochondria_instance_32-bit.zip",
        z_skip=0, tissue="liver (obese, fasted)"),
    "obese_lacz": dict(
        raw_dir=f"{B12}/Obese LacZ/ob_LacZ_2679_raw_8-bit/",
        mito_zip=f"{B12}/Obese LacZ/ob_LacZ_2679_mitochondria-instance_32-bit.zip",
        z_skip=0, tissue="liver (obese, LacZ control)"),
    "obese_rrbp1": dict(
        raw_dir=f"{B12}/Obese RRBP1/1858_Ob_RRBP1-OE_Raw_8-bit/",
        mito_zip=f"{B12}/Obese RRBP1/ob_RRBP1_OE_1858_mito-instance_32-bit.zip",
        z_skip=65, tissue="liver (obese, RRBP1-OE)"),   # first 65 = Durcupan resin
    "lean_fed": dict(
        raw_dir=f"{B10}/{S1}/6461 - Lean Liver/6461 Lean Liver - Raw/",
        mito_zip=f"{B12}/Lean Fed/Lean_Fed_6461_mitochondria_instance_32-bit.zip",
        z_skip=0, tissue="liver (lean, fed)"),
    "obese_fed": dict(
        raw_dir=f"{B10}/{S1}/6464 - Obese1 Liver/6464 Obese1 Liver - Raw/",
        mito_zip=f"{B12}/Obese Fed/Obese_fed_6464_mitochondria_instance_32-bit.zip",
        z_skip=0, tissue="liver (obese, fed)"),
}
ZCHUNK = 64
PREFETCH = 20            # raw slices kept in flight ahead of the cursor
# EBI refuses >~16 concurrent conns/IP; ~18-20 MB/s aggregate cap per IP. When running N parallel
# SLURM jobs that share one egress IP, keep sum(WORKERS) <= ~12 (set EMPIAR_WORKERS per job).
WORKERS = int(os.environ.get("EMPIAR_WORKERS", "10"))


def enc(url): return url.replace(" ", "%20")


def list_tifs(dir_url):
    """Return slice basenames in a raw TIFF folder, sorted by their Z index."""
    import requests
    html = requests.get(enc(dir_url), timeout=120).text
    names = re.findall(r'href="([^"]+\.tif{1,2})"', html)
    names = [n for n in names if "/" not in n]
    def zkey(n):
        m = re.search(r'[Zz](\d+)', n)
        return int(m.group(1)) if m else int(re.search(r'(\d+)', n).group(1))
    return sorted(set(names), key=zkey)


def mito_members(zip_url, timeout=180):
    # RemoteZip forwards **kwargs to requests.get(..., stream=True); a timeout turns an EBI
    # mid-stream stall (which otherwise blocks the read forever) into a raised ReadTimeout the
    # caller can retry. A fresh Session lets a reconnect drop the poisoned connection.
    import requests
    from remotezip import RemoteZip
    zf = RemoteZip(enc(zip_url), session=requests.Session(), timeout=timeout)
    names = [n for n in zf.namelist() if n.lower().endswith((".tif", ".tiff"))]
    def nkey(n):
        base = os.path.splitext(os.path.basename(n))[0]
        m = re.search(r'(\d+)', base)
        return int(m.group(1)) if m else base
    return zf, sorted(names, key=nkey)


def ds_img(a, b):
    """8 -> 1 block mean of two consecutive uint8 slices -> uint8 (Y2, X2)."""
    Y2, X2 = a.shape[0] // 2, a.shape[1] // 2
    a = a[:2 * Y2, :2 * X2].reshape(Y2, 2, X2, 2).sum((1, 3), dtype=np.uint16)
    b = b[:2 * Y2, :2 * X2].reshape(Y2, 2, X2, 2).sum((1, 3), dtype=np.uint16)
    return ((a + b) // 8).astype(np.uint8)


def ds_lbl(a):
    """Nearest-neighbour 2x: corner of each 2x2(x2) block (even z slice only) -> uint32."""
    Y2, X2 = a.shape[0] // 2, a.shape[1] // 2
    return a[:2 * Y2:2, :2 * X2:2].astype(np.uint32)


def finalize_uint16(zpath, log=print):
    """Renumber the (uint32, sparse EMPIAR ids) mito array to contiguous 1..N -> uint16 if it
    fits, else uint32. Original ids preserved in `.seen_ids.npy` (new id k -> ids[k-1]).
    Idempotent: skips if already relabeled."""
    import zarr, numpy as np, fastremap, os, shutil
    root = zarr.open_group(zpath, mode="a")
    meta = dict(root.attrs.get("mitoverse", {}))
    if meta.get("relabel"):
        log(f"[finalize] {os.path.basename(zpath)} already relabeled; skip"); return meta
    mito = root["mito"]
    seen_p = os.path.join(zpath, ".seen_ids.npy")
    if os.path.exists(seen_p):
        ids = np.load(seen_p)
    else:
        ids = np.zeros(0, np.uint32)
        for z0 in range(0, mito.shape[0], mito.chunks[0]):
            ids = fastremap.unique(np.concatenate([ids, fastremap.unique(mito[z0:z0+mito.chunks[0]])]))
    ids = np.unique(ids); ids = ids[ids > 0]
    N = int(len(ids))
    dt = np.uint16 if N <= 65535 else np.uint32
    mapping = {0: 0}
    for i, o in enumerate(ids.tolist()):
        mapping[int(o)] = i + 1
    log(f"[finalize] {os.path.basename(zpath)} N={N} -> {np.dtype(dt).name} "
        f"(raw max id {int(ids.max()) if N else 0})")
    new = root.create_dataset("mito_relabel", shape=mito.shape, chunks=mito.chunks,
                              dtype=dt, compressor=mito.compressor, overwrite=True)
    ZC = mito.chunks[0]
    for z0 in range(0, mito.shape[0], ZC):
        z1 = min(z0 + ZC, mito.shape[0])
        rs = fastremap.remap(mito[z0:z1], mapping, preserve_missing_labels=True)
        new[z0:z1] = rs.astype(dt)
    del mito, new, root
    shutil.rmtree(os.path.join(zpath, "mito"))
    os.rename(os.path.join(zpath, "mito_relabel"), os.path.join(zpath, "mito"))
    root = zarr.open_group(zpath, mode="a")
    meta["n_instances"] = N
    meta["mito_dtype"] = np.dtype(dt).name
    meta["relabel"] = "contiguous 1..N via fastremap; original EMPIAR ids in .seen_ids.npy"
    root.attrs["mitoverse"] = meta
    zarr.consolidate_metadata(root.store)
    return meta


def ingest_vol(vol, cfg, max_chunks=None, log=print):
    import requests, tifffile, zarr
    from numcodecs import Blosc
    zpath = os.path.join(OUT_ROOT, "data", DATASET, f"{vol}.zarr")
    prog_p = os.path.join(zpath, ".ingest_progress.json")
    seen_p = os.path.join(zpath, ".seen_ids.npy")

    log(f"[{vol}] listing raw slices …")
    raw_names = list_tifs(cfg["raw_dir"])
    zf, mito_names = mito_members(cfg["mito_zip"])
    zsk = cfg["z_skip"]
    raw_names, mito_names = raw_names[zsk:], mito_names[zsk:]
    n = min(len(raw_names), len(mito_names))
    if len(raw_names) != len(mito_names):
        log(f"[{vol}] WARN raw z={len(raw_names)} != mito z={len(mito_names)}; using {n}")
    raw_names, mito_names = raw_names[:n], mito_names[:n]
    Z2 = n // 2

    # probe shapes from first raw + first mito slice
    import threading
    _tl = threading.local()
    def _sess():
        s = getattr(_tl, "s", None)
        if s is None: s = _tl.s = requests.Session()
        return s
    def get_raw(idx):
        url = enc(cfg["raw_dir"]) + raw_names[idx]
        for k in range(8):
            try:
                r = _sess().get(url, timeout=180); r.raise_for_status()
                a = tifffile.imread(io.BytesIO(r.content))
                # EBI sometimes serves a 200 with a truncated/corrupt body: tifffile warns
                # "invalid offset to first page" and returns a degenerate (non-2D) array.
                # raise_for_status() doesn't catch this, so validate and force a re-fetch.
                if a.ndim != 2 or a.shape[0] < 2 or a.shape[1] < 2:
                    raise ValueError(f"corrupt raw slice {raw_names[idx]} shape={a.shape}")
                return a
            except Exception as e:
                if k == 7: raise
                _tl.s = None  # drop poisoned session/connection
                time.sleep(min(60, 5 * (k + 1)))  # backoff for Errno111 / corrupt page
    _mz = {"zf": zf}
    def get_mito(idx):
        # Mirror get_raw's resilience. get_mito runs synchronously in the main loop, so a
        # stalled RemoteZip read here freezes the entire ingest (observed: EBI throttle hung
        # the job at chunk 34 for 6.5h, no error, holding the allocation). Retry + reconnect.
        for k in range(8):
            try:
                with _mz["zf"].open(mito_names[idx]) as fp:
                    a = tifffile.imread(io.BytesIO(fp.read()))
                if a.ndim != 2 or a.shape[0] < 2 or a.shape[1] < 2:
                    raise ValueError(f"corrupt mito slice {mito_names[idx]} shape={a.shape}")
                return a
            except Exception:
                if k == 7: raise
                try: _mz["zf"].close()
                except Exception: pass
                time.sleep(min(60, 5 * (k + 1)))  # back off, then reconnect the remote zip
                _mz["zf"], _ = mito_members(cfg["mito_zip"])

    r0 = get_raw(0)
    Y2, X2 = r0.shape[0] // 2, r0.shape[1] // 2
    log(f"[{vol}] z={n} (->{Z2}) raw_slice={r0.shape} -> out=({Z2},{Y2},{X2}) uint8/uint32")

    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
    resume_chunk, seen = 0, set()
    if os.path.exists(prog_p) and os.path.exists(zpath):
        pr = json.load(open(prog_p))
        if pr.get("shape") == [Z2, Y2, X2]:
            resume_chunk = pr.get("chunks_done", 0)
            if os.path.exists(seen_p): seen = set(np.load(seen_p).tolist())
            log(f"[{vol}] resuming at chunk {resume_chunk}/{-(-Z2//ZCHUNK)}")
    if resume_chunk == 0:
        if os.path.exists(zpath):
            import shutil; shutil.rmtree(zpath)
        root = zarr.group(store=zarr.DirectoryStore(zpath), overwrite=True)
        root.create_dataset("img",  shape=(Z2, Y2, X2), chunks=(ZCHUNK, 512, 512),
                            dtype="u1", compressor=comp)
        root.create_dataset("mito", shape=(Z2, Y2, X2), chunks=(ZCHUNK, 512, 512),
                            dtype="u4", compressor=comp)
    else:
        root = zarr.open_group(zpath, mode="a")
    zimg, zmito = root["img"], root["mito"]

    n_chunks = -(-Z2 // ZCHUNK)
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futs = {}
    def ensure(idx):
        if idx not in futs and idx < n:
            futs[idx] = pool.submit(get_raw, idx)
    def take(idx):
        ensure(idx); f = futs.pop(idx); return f.result()

    t0 = time.time()
    for c in range(resume_chunk, n_chunks):
        z2a, z2b = c * ZCHUNK, min((c + 1) * ZCHUNK, Z2)
        nb = z2b - z2a
        img_buf = np.empty((nb, Y2, X2), np.uint8)
        mito_buf = np.empty((nb, Y2, X2), np.uint32)
        # prefetch raw window for this chunk
        for z2 in range(z2a, min(z2b + PREFETCH // 2, Z2)):
            ensure(2 * z2); ensure(2 * z2 + 1)
        for j, z2 in enumerate(range(z2a, z2b)):
            ia, ib = 2 * z2, 2 * z2 + 1
            ra, rb = take(ia), take(ib)
            # img and label volumes can differ by a few px in their native Y/X, so the
            # independently-downsampled slices may not match the buffer's (Y2,X2) exactly.
            # Fit each into the common top-left overlap (zero-fill any shortfall).
            di = ds_img(ra, rb)
            iy, ix = min(di.shape[0], Y2), min(di.shape[1], X2)
            img_buf[j] = 0; img_buf[j, :iy, :ix] = di[:iy, :ix]
            m = ds_lbl(get_mito(ia))
            my, mx = min(m.shape[0], Y2), min(m.shape[1], X2)
            mito_buf[j] = 0; mito_buf[j, :my, :mx] = m[:my, :mx]
            u = np.unique(m[:my, :mx]); seen.update(u[u > 0].tolist())
            # keep prefetch sliding
            ahead = z2 + PREFETCH // 2
            if ahead < Z2: ensure(2 * ahead); ensure(2 * ahead + 1)
        zimg[z2a:z2b] = img_buf
        zmito[z2a:z2b] = mito_buf
        json.dump({"chunks_done": c + 1, "shape": [Z2, Y2, X2], "n_instances": len(seen)},
                  open(prog_p, "w"))
        np.save(seen_p, np.array(sorted(seen), dtype=np.uint32))
        rate = (z2b) / max(1e-9, time.time() - t0)
        log(f"[{vol}] chunk {c+1}/{n_chunks}  z2={z2b}/{Z2}  "
            f"inst={len(seen)}  {rate:.1f} oz/s  {(time.time()-t0)/60:.1f}min")
        if max_chunks and (c + 1 - resume_chunk) >= max_chunks:
            log(f"[{vol}] stopping after {max_chunks} chunk(s) (test mode)")
            pool.shutdown(wait=False); return None

    pool.shutdown(wait=True)
    n_inst = len(seen)
    meta = {
        "volume_id": f"{DATASET}_{vol}", "dataset_id": DATASET,
        "modality": "FIB-SEM", "species": "Mouse", "tissue": cfg["tissue"],
        "voxel_nm": [16.0, 16.0, 16.0], "shape_zyx": [Z2, Y2, X2],
        "label_type": "instance", "n_instances": n_inst,
        "provenance": "original", "normalization": "uint8(mean 2x2x2 from 8nm)",
        "downsample": "img: mean 2x2x2; mito: nearest 2x (EMPIAR-12017 @8nm -> 16nm)",
        "source": {"raw": enc(cfg["raw_dir"]), "mito": enc(cfg["mito_zip"]),
                   "empiar": "EMPIAR-12017"},
    }
    root.attrs["mitoverse"] = meta
    zarr.consolidate_metadata(root.store)
    del root
    meta = finalize_uint16(zpath, log=log)   # renumber -> uint16 contiguous
    log(f"[{vol}] DONE  shape=({Z2},{Y2},{X2})  instances={meta['n_instances']}  "
        f"dtype={meta.get('mito_dtype')}  {(time.time()-t0)/60:.1f}min")
    return meta


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--vols", nargs="*", choices=list(VOLS))
    p.add_argument("--all", action="store_true")
    p.add_argument("--max-chunks", type=int, default=None)
    p.add_argument("--finalize", action="store_true",
                   help="only renumber existing volume(s) to uint16; no download")
    a = p.parse_args(argv)
    vols = list(VOLS) if a.all else (a.vols or [])
    if not vols:
        p.error("specify --vols ... or --all")
    for v in vols:
        try:
            if a.finalize:
                finalize_uint16(os.path.join(OUT_ROOT, "data", DATASET, f"{v}.zarr"))
            else:
                ingest_vol(v, VOLS[v], max_chunks=a.max_chunks)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[{v}] FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
