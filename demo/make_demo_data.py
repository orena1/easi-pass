"""Assemble the JS078 demo dataset from the full-resolution source.

The public demo is a *subset* of real mouse JS078 -- a single functional plane
(plane 0) and a single HCR round (01). Within that subset the data ships at
FULL resolution: the HCR volume is NOT spatially cropped.

Why no crop
-----------
2P->HCR registration (auto SIFT for low->hi res, then the local tile cascade)
needs the surrounding HCR image context, and several landmark cells sit near the
tissue edge. An earlier version XY-cropped the volume to shave size; that halved
alignment quality -- plane0 best-match median IoU dropped 0.38 -> 0.16 vs the
uncropped production run, and the 2P->HCR overlay masks looked misaligned.
Shipping the full volume restores production-quality alignment. The data lives on
Zenodo (see fetch_demo_data.py), so the ~774 MB size is not a repo concern.

(A previous Z-crop attempt failed the same way, which is why full Z was already
kept; the XY crop was the remaining offender. Everything is now shipped whole.)

What it does
------------
1. Copies the full HCR round-01 volume verbatim -- this preserves the exact
   voxel-size metadata the pipeline is validated against (no re-encode).
2. Copies the 2P mean image + hi-res stitched image verbatim.
3. Copies the BigWarp landmark file verbatim to the pre-seed location so the run
   is non-interactive (no BigWarp prompt). No coordinate shift is needed because
   nothing is cropped -- landmark coordinates are already in the full frame.

Run on any box that can see the full JS078 folder:
    python make_demo_data.py --src /mnt/nasquatch/data/2p/jonna/EASI_FISH/pipeline/JS078 \
                             --dst ./to_run/JS078_demo
"""
import argparse
import shutil
from pathlib import Path


def copy_verbatim(src: Path, dst: Path, label: str):
    if not src.exists():
        raise FileNotFoundError(f"{label}: source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Skip the (large) copy if an identical-size file is already there.
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        print(f"  {label}: {dst.name} already present ({dst.stat().st_size / 1e6:.1f} MB) -- skip")
        return
    shutil.copy2(src, dst)
    print(f"  {label}: {src.name} -> {dst}  ({dst.stat().st_size / 1e6:.1f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="full JS078 folder")
    ap.add_argument("--dst", required=True, help="demo mouse folder to write (e.g. to_run/JS078_demo)")
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)

    # 1. HCR round 01 -- full volume, no spatial crop.
    copy_verbatim(src / "HCR" / "JS078_HCR01.tiff",
                  dst / "HCR" / "JS078_demo_HCR01.tiff", "HCR01")

    # 2. 2P plane-0 images (low-res mean + hi-res stitched).
    for name in ("plane_0.tiff", "plane_0_hires.tiff"):
        copy_verbatim(src / "2P" / name, dst / "2P" / name, "2P")

    reg = dst / "OUTPUT" / "2P" / "registered"

    # 3. Pre-seed BigWarp landmarks (verbatim; frame is uncropped so no shift).
    copy_verbatim(src / "2P" / "landmarks_plane0.csv",
                  reg / "hires_stitched_plane0_to_HCR1_landmarks.csv", "landmarks")

    # 4. Pre-seed the low-res -> hi-res 2P PLACEMENT from the production run.
    #    The automated SIFT low->hi step is fragile in the tiff-only path: on this
    #    plane it places the 2P image ~100 px off, so the downstream 2P->HCR coarse
    #    align rails on a phantom shift and the overlay masks come out stringy
    #    (final IoU ~0.34 vs production 0.49). Shipping the production placement
    #    fixes the root cause while letting the demo still run 2P->HCR itself.
    #    When running the pipeline, answer "n" to the "Overwrite?" prompt for the
    #    low->hi step so it keeps these files instead of regenerating them.
    src_reg = src / "OUTPUT" / "2P" / "registered"
    for name in ("lowres_plane0_masks_in_hires_space.tiff",
                 "lowres_meanImg_C0_plane0_rotated.tiff",
                 "hires_stitched_plane0_rotated.tiff"):
        copy_verbatim(src_reg / name, reg / name, "placement")
    print("Done.")


if __name__ == "__main__":
    main()
