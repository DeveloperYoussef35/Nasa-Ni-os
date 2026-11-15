import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import pipeline

CACHE = Path(__file__).resolve().parent.parent / "cache"
CACHE.mkdir(exist_ok=True)
PREVIEW_FRAMES = 12

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/cache", StaticFiles(directory=CACHE), name="cache")

# one lock per build, so two identical requests don't both start downloading
_locks = {}
_locks_guard = threading.Lock()

# progress of builds: key -> {state, done, total, error}
JOBS = {}
JOBS_LOCK = threading.Lock()
ACTIVE = ("queued", "querying", "building")


def _lock_for(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _set_job(key, **fields):
    with JOBS_LOCK:
        job = JOBS.setdefault(key, {"state": "queued", "done": 0, "total": 0, "error": None})
        job.update(fields)


def _resolve(ra, dec, fov, det, full):
    """Work out which cache folder serves this request, and whether it is a preview."""
    name = f"{ra:.4f}_{dec:.4f}_{int(fov)}"
    fname = f"D{det}.json"
    full_dir = CACHE / name
    preview_dir = CACHE / (name + "_preview")
    if (full_dir / fname).exists():
        return full_dir, False
    if not full and (preview_dir / fname).exists():
        return preview_dir, True
    return (full_dir, False) if full else (preview_dir, True)


def _build(ra, dec, fov, det, full):
    """Make sure the frames exist, building them if needed. Returns (folder, is_preview)."""
    folder, is_preview = _resolve(ra, dec, fov, det, full)
    json_path = folder / f"D{det}.json"
    if json_path.exists():
        return folder, is_preview

    key = str(json_path)
    with _lock_for(key):
        if json_path.exists():                # someone else built it while we waited
            return folder, is_preview
        _set_job(key, state="querying", done=0, total=0, error=None)
        try:
            results = pipeline.find_images(ra, dec)
            rows = int((results["detector"] == det).sum())
            total = min(rows, PREVIEW_FRAMES) if is_preview else rows
            _set_job(key, state="building", total=total)
            pipeline.build_detector(
                results, det, ra, dec, fov, folder,
                max_frames=PREVIEW_FRAMES if is_preview else None,
            )
        except Exception as e:
            _set_job(key, state="error", error=str(e))
            raise
        _set_job(key, state="ready", done=total)
    return folder, is_preview


def _build_in_background(ra, dec, fov, det, full):
    try:
        _build(ra, dec, fov, det, full)
    except Exception:
        pass            # the error is already recorded in JOBS for /status


def _status(ra, dec, fov, det, full):
    folder, is_preview = _resolve(ra, dec, fov, det, full)
    json_path = folder / f"D{det}.json"
    if json_path.exists():
        n = len(json.load(open(json_path)))
        return {"state": "ready", "done": n, "total": n, "error": None, "preview": is_preview}
    with JOBS_LOCK:
        job = dict(JOBS.get(str(json_path), {}))
    if not job:
        return {"state": "not_started", "done": 0, "total": 0, "error": None, "preview": is_preview}
    if job["state"] == "building":
        done = len(list(folder.glob(f"D{det}_*.png")))
        job["done"] = min(done, job["total"])
    job["preview"] = is_preview
    return job


@app.get("/frames")
def frames(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    fov: float = Query(120, ge=30, le=600),
    det: int = Query(3, ge=1, le=6),
    wmin: float | None = None,
    wmax: float | None = None,
    full: bool = False,
):
    try:
        folder, is_preview = _build(ra, dec, fov, det, full)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IRSA problem: {e}")

    data = json.load(open(folder / f"D{det}.json"))
    if wmin is not None and wmax is not None:
        data = [f for f in data
                if f["wavelength_um"] is not None and wmin <= f["wavelength_um"] < wmax]
    for f in data:
        f["image"] = f"/cache/{folder.name}/{f['image']}"
        f["preview"] = is_preview
    return data


@app.get("/start")
def start(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    fov: float = Query(120, ge=30, le=600),
    det: int = Query(3, ge=1, le=6),
    full: bool = False,
):
    """Begin building in the background and return at once. Poll /status."""
    current = _status(ra, dec, fov, det, full)
    if current["state"] in ("ready",) + ACTIVE:
        return current
    folder, _ = _resolve(ra, dec, fov, det, full)
    _set_job(str(folder / f"D{det}.json"), state="queued", done=0, total=0, error=None)
    threading.Thread(target=_build_in_background,
                     args=(ra, dec, fov, det, full), daemon=True).start()
    return _status(ra, dec, fov, det, full)


@app.get("/status")
def status(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    fov: float = Query(120, ge=30, le=600),
    det: int = Query(3, ge=1, le=6),
    full: bool = False,
):
    return _status(ra, dec, fov, det, full)


@app.get("/targets")
def targets():
    p = CACHE / "targets.json"
    return json.load(open(p)) if p.exists() else []


@app.get("/spectrum")
def spectrum(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    fov: float = Query(120, ge=30, le=600),
    det: int = Query(3, ge=1, le=6),
):
    path = CACHE / f"{ra:.4f}_{dec:.4f}_{int(fov)}" / f"S{det}.json"
    with _lock_for(str(path)):
        if not path.exists():
            try:
                points = pipeline.measure_detector(pipeline.find_images(ra, dec), det, ra, dec)
            except ValueError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"IRSA problem: {e}")
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(points, f, indent=2)
    return json.load(open(path))
