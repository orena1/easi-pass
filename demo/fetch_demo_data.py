"""Download the JS078 demo imaging data from Zenodo.

The demo's small text files (manifest, seed landmarks, expected output) live in the
git repo. The imaging volumes are hosted on Zenodo and fetched here so the repo stays
lightweight. There are two archives:

  demo_pre_run   the fresh dataset you run the pipeline on (~825 MB apparent; the zip
                 is smaller since the HCR volume is mostly background). Fetched by default.
  demo_post_run  a full, correct completion to compare your run against (several GB).
                 Optional -- fetch with --with-reference.

Usage:
    python fetch_demo_data.py                     # pre_run only (enough to run the demo)
    python fetch_demo_data.py --with-reference    # also fetch the completed reference
    python fetch_demo_data.py --force             # re-download even if data exists

MAINTAINER TODO: after depositing the archives on Zenodo, fill in the URL/SHA256 pairs
below. Build each archive from a populated folder with, e.g.:
    (cd demo && zip -r JS078_demo_pre_run.zip  demo_pre_run/JS078_demo)  && sha256sum demo/JS078_demo_pre_run.zip
    (cd demo && zip -r JS078_demo_post_run.zip demo_post_run/JS078_demo) && sha256sum demo/JS078_demo_post_run.zip
"""
import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- Fill these in after the Zenodo deposit -----------------------------------
# Each archive extracts a "{name}/JS078_demo/" tree into demo/.
ARCHIVES = {
    "demo_pre_run": {
        "url": "https://zenodo.org/records/PLACEHOLDER/files/JS078_demo_pre_run.zip",
        "sha256": "PLACEHOLDER_SHA256_PRE_RUN",
        "marker": HERE / "demo_pre_run" / "JS078_demo" / "HCR" / "JS078_demo_HCR01.tiff",
    },
    "demo_post_run": {
        "url": "https://zenodo.org/records/PLACEHOLDER/files/JS078_demo_post_run.zip",
        "sha256": "PLACEHOLDER_SHA256_POST_RUN",
        "marker": HERE / "demo_post_run" / "JS078_demo" / "MERGED" / "aligned_masks" / "twop_plane0_to_HCR01.csv",
    },
}
# ------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str, spec: dict, force: bool):
    if spec["marker"].exists() and not force:
        print(f"{name}: already present (use --force to re-download).")
        return
    if "PLACEHOLDER" in spec["url"] or "PLACEHOLDER" in spec["sha256"]:
        sys.exit(
            f"{name}: not wired up yet -- url/sha256 are placeholders.\n"
            "Until the Zenodo deposit exists, generate the data locally with make_demo_data.py."
        )
    archive = HERE / f"{name}.zip"
    print(f"{name}: downloading {spec['url']} ...")
    urllib.request.urlretrieve(spec["url"], archive)
    print(f"{name}: verifying checksum ...")
    got = sha256(archive)
    if got != spec["sha256"]:
        archive.unlink(missing_ok=True)
        sys.exit(f"{name}: checksum mismatch (expected {spec['sha256']}, got {got})")
    print(f"{name}: extracting into {HERE} ...")
    with zipfile.ZipFile(archive) as z:
        z.extractall(HERE)
    archive.unlink()
    print(f"{name}: done.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--with-reference", action="store_true",
                    help="also fetch demo_post_run (the completed reference, several GB)")
    ap.add_argument("--force", action="store_true", help="re-download even if data exists")
    args = ap.parse_args()

    fetch("demo_pre_run", ARCHIVES["demo_pre_run"], args.force)
    if args.with_reference:
        fetch("demo_post_run", ARCHIVES["demo_post_run"], args.force)
    print("\nNext: set base_path in demo/JS078_demo.hjson to demo/demo_pre_run, "
          "then run master_pipeline.py.")


if __name__ == "__main__":
    main()
