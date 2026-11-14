"""find images fetches cutouts algins them saves as PNGs + JSON."""
import argparse
import json
import logging
import time
import urllib.error
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.utils.data import conf
from astropy.visualization import ZScaleInterval
from astropy.wcs import WCS
from astroquery.ipac.irsa import Irsa
from PIL import Image
from reproject import reproject_interp

logging.getLogger("astropy").setLevel(logging.WARNING)
conf.remote_timeout = 120
COLLECTION = "spherex_dr1"


def find_images(ra, dec, radius_arcsec=50):
    """Ask IRSA for every SPHEREx exposure covering this position."""
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    results = Irsa.query_sia(pos=(coord, radius_arcsec * u.arcsec), collection=COLLECTION)
    if len(results) == 0:
        raise ValueError("IRSA found no images at that position")
    results["detector"] = [int(n[-1]) for n in results["energy_bandpassname"]]
    results["date"] = Time(np.asarray(results["t_min"], dtype=float), format="mjd").iso
    results.sort("t_min")
    return results


def open_with_retry(url, tries=4):
    for attempt in range(tries):
        try:
            return fits.open(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            wait = 5 * (attempt + 1)
            print(f"  attempt {attempt + 1} failed ({e}); waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError("IRSA kept failing for: " + url)


def common_grid(ra, dec, size_arcsec, pix_arcsec=6.15):
    n = int(round(size_arcsec / pix_arcsec))
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pix_arcsec / 3600, pix_arcsec / 3600]
    return w, (n, n)


def get_wavelength(hdul, ra, dec):
    header = hdul["IMAGE"].header
    try:
        spatial_wcs = WCS(header, fobj=hdul)
        x, y = spatial_wcs.world_to_pixel(SkyCoord(ra=ra, dec=dec, unit="deg", frame="icrs"))
        spectral_wcs = WCS(header, fobj=hdul, key="W")
        spectral_wcs.sip = None
        wavelength, _ = spectral_wcs.pixel_to_world(x, y)
        return float(wavelength.to(u.micrometer).value)
    except Exception as e:
        print("  wavelength lookup failed:", e)
        return float("nan")


def make_frame(row, ra, dec, size_arcsec, out_path, scale=20, pad=1.5):
    """Download one cutout, align it north-up, stretch it, save a PNG.
    Returns the wavelength in micrometres, or None if the frame was skipped."""
    url = f"{row['access_url']}?center={ra},{dec}d&size={size_arcsec * pad / 3600}"
    with open_with_retry(url) as hdul:
        data = hdul["IMAGE"].data.astype(float)
        header = hdul["IMAGE"].header
        wavelength = get_wavelength(hdul, ra, dec)

    target_wcs, shape = common_grid(ra, dec, size_arcsec)
    data, _ = reproject_interp((data, WCS(header)), target_wcs, shape_out=shape)

    valid = np.isfinite(data)
    if valid.mean() < 0.95:
        return None

    lo, hi = ZScaleInterval().get_limits(data[valid])
    img = np.clip((data - lo) / (hi - lo), 0, 1)
    img = (np.nan_to_num(img, nan=0.0) * 255).astype("uint8")

    im = Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST)
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    im.save(out_path)
    return wavelength


def build_detector(results, det, ra, dec, size_arcsec, out_dir, limit=None):
    """Make every frame for one detector, plus a D<det>.json describing them."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = results[results["detector"] == det]
    if limit:
        rows = rows[:limit]

    frames = []
    for i, r in enumerate(rows):
        name = f"D{det}_{i:03d}.png"
        try:
            wl = make_frame(r, ra, dec, size_arcsec, out_dir / name)
        except Exception as e:
            print(f"  skip {i}: {e}")
            continue
        if wl is not None:
            frames.append({
                "image": name,
                "date": str(r["date"]),
                "mjd": float(r["t_min"]),
                "detector": det,
                "wavelength_um": None if np.isnan(wl) else round(wl, 3),
            })
    with open(out_dir / f"D{det}.json", "w") as f:
        json.dump(frames, f, indent=2)
    return frames


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build SPHEREx frames for one detector")
    p.add_argument("ra", type=float)
    p.add_argument("dec", type=float)
    p.add_argument("--det", type=int, default=3)
    p.add_argument("--fov", type=float, default=120, help="field of view in arcsec")
    p.add_argument("--out", default="cache/test")
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args()

    res = find_images(a.ra, a.dec)
    print(len(res), "images found")
    out = build_detector(res, a.det, a.ra, a.dec, a.fov, a.out, limit=a.limit)
    print(len(out), "frames saved to", a.out)