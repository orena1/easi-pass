"""Download the JS078 demo imaging data from the GitHub release.

The demo's small text files (manifest, seed landmarks, expected output) live in the
git repo. The imaging volumes are attached to a GitHub release and fetched here so
the repo stays lightweight. There are two archives:

  demo_pre_run   the fresh dataset you run the pipeline on (~350 MB zipped). This is
                 all you need to run the demo. Fetched by default.
  demo_post_run  a full, correct completion to compare your run against (~1.2 GB).
                 Optional -- fetch with --with-reference. For a quick check without
                 this download, compare against the golden CSV in completed/ instead.

Usage:
    python fetch_demo_data.py                     # pre_run only (enough to run the demo)
    python fetch_demo_data.py --with-reference    # also fetch the completed reference
    python fetch_demo_data.py --force             # re-download even if data exists

MAINTAINER TODO: after attaching the archives to a GitHub release, set RELEASE_BASE
below and fill in the two SHA256s. Build each archive from a populated folder with:
    (cd demo && zip -r JS078_demo_pre_run.zip  demo_pre_run/JS078_demo)  && sha256sum demo/JS078_demo_pre_run.zip
    (cd demo && zip -r JS078_demo_post_run.zip demo_post_run/JS078_demo) && sha256sum demo/JS078_demo_post_run.zip
"""
import argparse
import hashlib
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- Fill in after attaching the archives to a GitHub release ------------------
# Create a release (e.g. tag v0.1.0), attach both zips, then replace OWNER/REPO/TAG
# here and paste the two sha256sums below. Release asset URLs look like:
#   https://github.com/OWNER/REPO/releases/download/TAG/JS078_demo_pre_run.zip
RELEASE_BASE = "https://github.com/OWNER/REPO/releases/download/TAG"

# Each archive extracts a "{name}/JS078_demo/" tree into demo/.
ARCHIVES = {
    "demo_pre_run": {
        "url": f"{RELEASE_BASE}/JS078_demo_pre_run.zip",
        "sha256": "PLACEHOLDER_SHA256_PRE_RUN",
        "marker": HERE / "demo_pre_run" / "JS078_demo" / "HCR" / "JS078_demo_HCR01.tiff",
    },
    "demo_post_run": {
        "url": f"{RELEASE_BASE}/JS078_demo_post_run.zip",
        "sha256": "PLACEHOLDER_SHA256_POST_RUN",
        "marker": HERE / "demo_post_run" / "JS078_demo" / "OUTPUT" / "MERGED" / "aligned_masks" / "twop_plane0_to_HCR01.csv",
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
    if "OWNER/REPO" in spec["url"] or "PLACEHOLDER" in spec["sha256"]:
        sys.exit(
            f"{name}: the release asset is not published yet.\n"
            "Generate the data locally with make_demo_data.py, or check the repo's\n"
            "releases page for a newer version of this script."
        )
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
    ap.add_argument("--with-reference", action="store_true",
                    help="also fetch demo_post_run (the completed reference, ~1.2 GB)")
    ap.add_argument("--force", action="store_true", help="re-download even if data exists")
    args = ap.parse_args()

    fetch("demo_pre_run", ARCHIVES["demo_pre_run"], args.force)
    if args.with_reference:
        fetch("demo_post_run", ARCHIVES["demo_post_run"], args.force)
    print("\nNext, from the repository root:\n"
          "    python master_pipeline.py --manifest demo/JS078_demo.hjson")


if __name__ == "__main__":
    main()
