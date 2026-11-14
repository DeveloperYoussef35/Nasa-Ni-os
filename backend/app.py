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


def _lock_for(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


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
    name = f"{ra:.4f}_{dec:.4f}_{int(fov)}"
    full_dir = CACHE / name
    preview_dir = CACHE / (name + "_preview")
    fname = f"D{det}.json"

    if (full_dir / fname).exists():
        folder, is_preview = full_dir, False
    elif not full and (preview_dir / fname).exists():
        folder, is_preview = preview_dir, True
    else:
        folder, is_preview = (full_dir, False) if full else (preview_dir, True)
        with _lock_for(str(folder / fname)):
            if not (folder / fname).exists():       # someone else may have built it meanwhile
                try:
                    results = pipeline.find_images(ra, dec)
                except ValueError as e:
                    raise HTTPException(status_code=404, detail=str(e))
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"IRSA problem: {e}")
                pipeline.build_detector(
                    results, det, ra, dec, fov, folder,
                    max_frames=PREVIEW_FRAMES if is_preview else None,
                )

    data = json.load(open(folder / fname))
    if wmin is not None and wmax is not None:
        data = [f for f in data
                if f["wavelength_um"] is not None and wmin <= f["wavelength_um"] < wmax]
    for f in data:
        f["image"] = f"/cache/{folder.name}/{f['image']}"
        f["preview"] = is_preview
    return data


@app.get("/targets")
def targets():
    p = CACHE / "targets.json"
    return json.load(open(p)) if p.exists() else []