"""Build and cache SPHEREx frames for the challenge test targets.
"""
import argparse
import json
from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

import pipeline

CACHE = Path(__file__).resolve().parent.parent / "cache"
MID_EPOCH = Time("2025-11-07")      # roughly the middle of the SPHEREx coverage

# pos / pm / epoch from SIMBAD (WISE 0855: challenge text + Kirkpatrick et al. 2021)
# stretch: "asinh" for bright stars, "zscale" for faint targets
TARGETS = {
    "barnard":  dict(name="Barnard's Star", pos="17 57 48.4984700685 +04 41 36.113879676",
                     pmra=-801.551, pmdec=10362.394, epoch="J2000", fov=120, stretch="asinh"),
    "epsindib": dict(name="Epsilon Indi B", pos="22 04 10.5951812451 -56 46 58.239102418",
                     pmra=3981.977, pmdec=-2466.832, epoch="J2000", fov=120, stretch="zscale"),
    "wise0855": dict(name="WISE 0855", pos="08 55 10.831 -07 14 42.53",
                     pmra=-8123.7, pmdec=673.2, epoch="J2010.3", fov=300, stretch="zscale"),
    "rwaur":    dict(name="RW Aur", pos="05 07 49.5662483 +30 24 05.177426",
                     pmra=7.23, pmdec=-20.33, epoch="J2000", fov=120, stretch="asinh"),
    "rdra":     dict(name="R Dra", pos="16 32 40.2265999080 +66 45 17.925901992",
                     pmra=-20.643, pmdec=6.149, epoch="J2000", fov=120, stretch="asinh"),
}


def aim_point(t):
    c = SkyCoord(t["pos"], unit=(u.hourangle, u.deg), frame="icrs",
                 pm_ra_cosdec=t["pmra"] * u.mas / u.yr,
                 pm_dec=t["pmdec"] * u.mas / u.yr,
                 obstime=Time(t["epoch"]))
    now = c.apply_space_motion(new_obstime=MID_EPOCH)
    return round(float(now.ra.deg), 5), round(float(now.dec.deg), 5)


def folder_for(ra, dec, fov):
    # must match the folder name that app.py builds
    return CACHE / f"{ra:.4f}_{dec:.4f}_{int(fov)}"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--targets", nargs="+", default=list(TARGETS), choices=list(TARGETS))
    p.add_argument("--dets", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6])
    p.add_argument("--limit", type=int, default=None, help="frames per detector (for testing)")
    p.add_argument("--stretch", default=None, choices=["zscale", "asinh"],
                   help="override the per-target stretch")
    a = p.parse_args()

    CACHE.mkdir(exist_ok=True)

    # write the target list first, so the frontend can use it right away
    listing = []
    for key, t in TARGETS.items():
        ra, dec = aim_point(t)
        listing.append({
            "key": key, "name": t["name"], "ra": ra, "dec": dec, "fov": t["fov"],
            "pm_ra_mas_yr": t["pmra"], "pm_dec_mas_yr": t["pmdec"],
            "stretch": t["stretch"],
            "folder": folder_for(ra, dec, t["fov"]).name,
        })
    with open(CACHE / "targets.json", "w") as f:
        json.dump(listing, f, indent=2)

    for item in listing:
        if item["key"] not in a.targets:
            continue
        stretch = a.stretch or item["stretch"]
        print(f"\n=== {item['name']}  (RA {item['ra']}, Dec {item['dec']}, fov {item['fov']}, stretch {stretch}) ===")
        try:
            results = pipeline.find_images(item["ra"], item["dec"])
        except Exception as e:
            print("  could not find images:", e)
            continue
        print(" ", len(results), "images found")
        folder = CACHE / item["folder"]
        for det in a.dets:
            if (folder / f"D{det}.json").exists() and not a.limit:
                print(f"  D{det}: already cached, skipping")
                continue
            print(f"  D{det}: building...")
            try:
                frames = pipeline.build_detector(results, det, item["ra"], item["dec"],
                                                 item["fov"], folder, limit=a.limit,
                                                 stretch=stretch)
                print(f"  D{det}: {len(frames)} frames saved")
            except Exception as e:
                print(f"  D{det}: FAILED:", e)
    print("\nDone.")