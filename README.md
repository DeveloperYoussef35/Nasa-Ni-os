# Nasa-Ni-os

**Team Nasa Niños** · NASA Space Apps Challenge

A Python project that queries, downloads and caches SPHEREx infrared cutouts
from the IRSA archive and turns them into detector-by-detector frame sequences
for analysis and blink animations.

The repository contains a **FastAPI backend** that serves frame metadata and
image URLs, and a **processing pipeline** that reprojects SPHEREx FITS cutouts
onto a common sky-aligned grid and saves them as PNG frames.

| Role | Who |
|---|---|
| Frontend | decidedarcher35 / DeveloperYoussef35 |
| Backend | enamour / EN-D001 |


---

## What this project does

- Queries the SPHEREx DR1 catalog through `astroquery` / IRSA
- Finds every exposure covering a requested sky position and detector
- Downloads small FITS cutouts and reads each frame's wavelength from its WCS
- Reprojects every cutout onto one fixed, north-up grid so frames line up
- Normalises the data and saves PNG frame images
- Caches the results (PNGs plus a JSON list per detector) so repeat requests
  are instant
- Serves everything through an HTTP API

## Repository structure

| Path | Purpose |
|---|---|
| `backend/app.py` | FastAPI app serving frame metadata and the cached image files |
| `backend/pipeline.py` | Image lookup, cutout handling, reprojection, PNG generation and JSON metadata output |
| `backend/prefetch.py` | Builds the cache for the five built-in target stars |
| `backend/requirements.txt` | Python dependencies |
| `cache/` | Pre-built frames and `targets.json` for the five targets |

## Requirements

Python 3.10 or newer, and these libraries (all listed in
`backend/requirements.txt`):

- `astroquery`
- `astropy`
- `numpy`
- `Pillow`
- `reproject`
- `scipy`
- `fastapi`
- `uvicorn`

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

> On Windows PowerShell, if activating fails with "running scripts is
> disabled", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once,
> or use Command Prompt or Git Bash instead.

## Run the API

From the repository root:

```bash
uvicorn app:app --app-dir backend --reload
```

Then open <http://localhost:8000/docs> for an interactive test page.

The cache for the five built-in targets is included in the repository, so
those load instantly without contacting IRSA.

## API

### `GET /targets`

Returns the five pre-built targets stored in `cache/targets.json`, with
position, field of view and proper motion. Use the `ra`, `dec` and `fov` values
exactly as given so requests match the cache.

```bash
curl "http://localhost:8000/targets"
```

### `GET /frames`

Returns the frames for one detector, in time order.

| Parameter | Required | Meaning |
|---|---|---|
| `ra` | yes | Right ascension in degrees, 0 to 360 |
| `dec` | yes | Declination in degrees, -90 to 90 |
| `fov` | no | Field of view in arcseconds, 30 to 600 (default `120`) |
| `det` | no | Detector number, 1 to 6 (default `3`) |
| `wmin`, `wmax` | no | Wavelength range in micrometres. Send both or neither. |
| `full` | no | `true` to build the full set instead of a 12-frame preview |

Example (a pre-built target, so the answer is instant):

```bash
curl "http://localhost:8000/frames?ra=269.4463&dec=4.76777&fov=120&det=3"
```

Each frame looks like this:

```json
{
  "image": "/cache/269.4463_4.7678_120/D3_000.png",
  "date": "2025-08-15 20:45:11.376",
  "mjd": 60902.864715,
  "detector": 3,
  "wavelength_um": 2.308,
  "preview": false
}
```

Prepend the server address to `image` to load the picture.

### Positions that are not cached

Any valid position works, but building it live takes time. A new position
builds a **preview** of 12 frames spread evenly across the year, which takes
about 1.5 minutes per detector. Preview frames have `"preview": true`. Add
`full=true` to build every frame (5 to 10 minutes per detector). Finished
builds are cached.

Calling `/frames` for a new position waits until the build finishes. For a
loading bar, use these two endpoints instead:

1. `GET /start?ra=&dec=&fov=&det=` starts the build and returns at once.
2. `GET /status?ra=&dec=&fov=&det=` returns `{ state, done, total, error, preview }`.
   Poll it every couple of seconds. `state` is one of `not_started`, `queued`,
   `querying`, `building`, `ready` or `error`.

When `state` is `ready`, call `/frames` with the same parameters. It is
instant by then.

## Built-in targets

| Target | Notes |
|---|---|
| Barnard's Star | Bright, moves about 10.4 arcsec per year |
| Epsilon Indi B | Brown dwarf pair, shown as one point |
| WISE 0855 | Very faint, not clearly visible in single frames |
| RW Aur | Variable young star |
| R Dra | Very bright Mira variable |

Each target is centred on where it is during the SPHEREx observations
(around November 2025), found by moving its catalog position forward with its
proper motion. WISE 0855 uses a wider 300 arcsecond field because the epoch of
its published position is uncertain.

## Precomputing cache data

`prefetch.py` generates the target list and cached detector frames:

```bash
python backend/prefetch.py
```

You can restrict it to selected targets or detectors:

```bash
python backend/prefetch.py --targets wise0855 --dets 3
```

This writes the `cache/` directory, containing JSON metadata and PNG frames.
Detectors that are already cached are skipped.

## Known limitations

- SPHEREx pixels are about 6.15 arcseconds, so even fast movers shift only a
  pixel or two over the mission so far.
- Each frame is contrast-stretched on its own, so brightness changes in
  variable stars are not visible from frame to frame.
- Positions typed in by a user are not corrected for proper motion.
- Build progress is kept in server memory, so restarting the server loses a
  build in progress. Finished results stay cached.

## Data and acknowledgements

- SPHEREx data from the NASA/IPAC Infrared Science Archive (IRSA), operated by
  Caltech under contract with NASA.
- Target positions and proper motions from SIMBAD (CDS, Strasbourg).

## License

This project is licensed under the MIT License. See `LICENSE` for details.
