"""Download the JS078 demo imaging data into demo/to_run/.

The demo's small text files (manifest, seed landmarks, expected output) live in the
git repo. The imaging volumes (~825 MB; the zip is smaller since the HCR volume is mostly
background) are hosted on Zenodo and fetched here so the repo stays lightweight.

Usage:
    python fetch_demo_data.py            # download + verify + extract into to_run/
    python fetch_demo_data.py --force    # re-download even if to_run/ exists

MAINTAINER TODO: after depositing the demo archive on Zenodo, set ZENODO_URL and
SHA256 below. Build the archive from a populated to_run/ with:
    (cd demo && zip -r JS078_demo.zip to_run/JS078_demo) && sha256sum demo/JS078_demo.zip
"""
import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

# --- Fill these in after the Zenodo deposit -----------------------------------
ZENODO_URL = "https://zenodo.org/records/PLACEHOLDER/files/JS078_demo.zip"
SHA256 = "PLACEHOLDER_SHA256"
# ------------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DEST = HERE / "to_run"
MARKER = DEST / "JS078_demo" / "HCR" / "JS078_demo_HCR01.tiff"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download even if data exists")
    args = ap.parse_args()

    if MARKER.exists() and not args.force:
        print(f"Demo data already present at {DEST}/JS078_demo (use --force to re-download).")
        return

    if "PLACEHOLDER" in ZENODO_URL or "PLACEHOLDER" in SHA256:
        sys.exit(
            "fetch_demo_data.py is not wired up yet: ZENODO_URL / SHA256 are placeholders.\n"
            "Until the Zenodo deposit exists, generate the data locally with make_demo_data.py."
        )

    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / "JS078_demo.zip"
    print(f"Downloading {ZENODO_URL} ...")
    urllib.request.urlretrieve(ZENODO_URL, archive)

    print("Verifying checksum ...")
    got = sha256(archive)
    if got != SHA256:
        archive.unlink(missing_ok=True)
        sys.exit(f"Checksum mismatch: expected {SHA256}, got {got}")

    print(f"Extracting into {DEST} ...")
    with zipfile.ZipFile(archive) as z:
        z.extractall(DEST)
    archive.unlink()
    print("Done. Now set base_path in demo/JS078_demo.hjson and run master_pipeline.py.")


if __name__ == "__main__":
    main()
