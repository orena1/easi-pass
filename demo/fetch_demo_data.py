"""Download the JS078 demo imaging data from the GitHub release.

The demo's small text files (manifest, seed landmarks, expected output) live in the
git repo. The imaging volumes are attached to a GitHub release and fetched here so
the repo stays lightweight. There are two archives:

One archive, demo_pre_run (~350 MB zipped): the dataset you run the pipeline on.
To check your result afterwards, diff it against the golden table tracked in
demo/completed/ -- see demo/completed/README.md for the numbers to expect.

Usage:
    python fetch_demo_data.py            # fetch the demo data
    python fetch_demo_data.py --force    # re-download even if it is already there

For maintainers -- to publish a new version of the demo data, rebuild the archive,
attach it to a release, then bump RELEASE_BASE and the sha256 below. Rebuild from a
demo_pre_run/ holding ONLY the four seed files under OUTPUT/, or the archive ships a
demo that has already been run:
    (cd demo && zip -r /tmp/JS078_demo_pre_run.zip demo_pre_run/JS078_demo)
    sha256sum /tmp/JS078_demo_pre_run.zip
"""
import argparse
import hashlib
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Assets attached to the GitHub release. To publish a new version: rebuild the zip,
# take its sha256sum, bump the tag here and paste the hash.
RELEASE_BASE = "https://github.com/orena1/easi-pass/releases/download/v0.1.0"

# Each archive extracts a "{name}/JS078_demo/" tree into demo/.
ARCHIVES = {
    "demo_pre_run": {
        "url": f"{RELEASE_BASE}/JS078_demo_pre_run.zip",
        "sha256": "1ac96d59bf7d52a522ac3ea0b963b15950b67c4d97c6c387407d863dccab011e",
        "marker": HERE / "demo_pre_run" / "JS078_demo" / "HCR" / "JS078_demo_HCR01.tiff",
    },
}
# ------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _progress(blocks, block_size, total):
    """urlretrieve reporthook. A silent multi-hundred-MB download looks like a hang."""
    if total <= 0:
        return
    done = min(blocks * block_size, total)
    sys.stdout.write(f"\r  {done / 1048576:,.0f} / {total / 1048576:,.0f} MB"
                     f" ({100.0 * done / total:.0f}%)")
    sys.stdout.flush()


def fetch(name: str, spec: dict, force: bool):
    if spec["marker"].exists() and not force:
        print(f"{name}: already present (use --force to re-download).")
        return
    archive = HERE / f"{name}.zip"
    print(f"{name}: downloading {spec['url']} ...")
    try:
        urllib.request.urlretrieve(spec["url"], archive, reporthook=_progress)
        print()
    except urllib.error.HTTPError as e:
        archive.unlink(missing_ok=True)
        sys.exit(f"\n{name}: download failed ({e.code} {e.reason}).\n"
                 f"  {spec['url']}\n"
                 "Check the repo's releases page for the current asset URL.")
    except urllib.error.URLError as e:
        archive.unlink(missing_ok=True)
        sys.exit(f"\n{name}: could not reach the server ({e.reason}).")

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
    ap.add_argument("--force", action="store_true", help="re-download even if data exists")
    args = ap.parse_args()

    fetch("demo_pre_run", ARCHIVES["demo_pre_run"], args.force)
    print("\nNext, from the repository root:\n"
          "    python master_pipeline.py --manifest demo/JS078_demo.hjson")


if __name__ == "__main__":
    main()
