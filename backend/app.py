import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import pipeline

CACHE = Path(__file__).resolve().parent.parent / "cache"
CACHE.mkdir(exist_ok=True)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/cache", StaticFiles(directory=CACHE), name="cache")


@app.get("/frames")
def frames(
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    fov: float = Query(120, ge=30, le=600),
    det: int = Query(3, ge=1, le=6),
    wmin: float | None = None,
    wmax: float | None = None,
):
    folder = CACHE / f"{ra:.4f}_{dec:.4f}_{int(fov)}"
    json_path = folder / f"D{det}.json"

    if not json_path.exists():            # not cached yet: build it (slow!)
        try:
            results = pipeline.find_images(ra, dec)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        pipeline.build_detector(results, det, ra, dec, fov, folder)

    data = json.load(open(json_path))
    if wmin is not None and wmax is not None:
        data = [f for f in data
                if f["wavelength_um"] is not None and wmin <= f["wavelength_um"] < wmax]
    for f in data:
        f["image"] = f"/cache/{folder.name}/{f['image']}"
    return data