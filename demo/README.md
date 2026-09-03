# Demo: one 2P plane aligned to an HCR FISH volume (mouse JS078)

A small, real, end-to-end example. It confirms your install works and shows the pipeline's
inputs and outputs: a single two-photon mean image aligned to a full-frame HCR FISH confocal
volume, cells segmented in both, matched, and written out as a per-cell table joining 2P
identity to the 5 HCR FISH gene channels.

There is nothing to edit. The manifest's `base_path` is relative, so it finds its own data.

```bash
python demo/fetch_demo_data.py                            # 191 MB
python master_pipeline.py --manifest demo/JS078_demo.hjson
```

Both commands run from the repository root. Budget about **1.3 GB free**: 790 MB of input
images, and roughly 450 MB the run itself writes under `OUTPUT/`.

## Prompts

The run pauses three times:

| Prompt | Answer |
|---|---|
| `Verify 2P cellpose segmentations … press Enter` | **Enter** |
| `Overwrite? [y/n]` (low-res to hi-res step) | **n**, which keeps the shipped 2P placement. Answering `y` recomputes it and the demo may no longer reproduce |
| `After checking QA images, choose [y/r/n]` (2P to HCR FISH) | **y** |

## Expected output

Results land under `demo_pre_run/JS078_demo/OUTPUT/`:

```
OUTPUT/MERGED/aligned_masks/twop_plane0_to_HCR01.csv        per-cell 2P <-> HCR FISH matches
OUTPUT/MERGED/aligned_extracted_features/full_table_*.csv   matches joined to the 5 gene channels
OUTPUT/2P/registered/QualityCheck/plane0_AFTER_registration_overlay.tiff
```

[`completed/`](completed/README.md) holds a tracked copy of the matching table and the numbers a
healthy run lands near, so you can check yourself without another download. Cell counts and
matches should be close, not identical; exact values depend on GPU and Cellpose version.

Notebook to explore the results:

```bash
jupyter lab demo/explore_results.ipynb        # or: python demo/explore_results.py
```

## Folder contents

```
demo/
├── JS078_demo.hjson       the manifest; nothing to edit
├── fetch_demo_data.py     downloads the imaging data from the GitHub release
├── make_demo_data.py      how the subset was assembled from full JS078 (maintainers)
├── explore_results.ipynb  plots of a finished run
├── demo_pre_run/          what you run on, created by fetch_demo_data.py
│   └── JS078_demo/
│       ├── 2P/plane_0.tiff                    2P low-res mean image
│       ├── 2P/plane_0_hires.tiff              2P hi-res stitched image
│       ├── HCR/JS078_demo_HCR01.tiff          5-channel HCR FISH volume, full frame
│       └── OUTPUT/2P/registered/              pre-seeded landmarks + placement
└── completed/             the golden matches table, tracked in git
```

The landmarks are shipped, so the demo does not prompt for BigWarp. To practise placing them
yourself, both images are here and [docs/BigWarp_Tips.md](../docs/BigWarp_Tips.md) walks through
it against this exact pair.

The demo manifest uses `model_path: "cpsam"` (cellpose-SAM), which auto-downloads, so there are
no model files to place. No GPU needed; one plane and one volume segment in reasonable time on a
CPU.

If `fetch_demo_data.py` fails, `JS078_demo_pre_run.zip` can be fetched by hand from the
[releases page](https://github.com/orena1/easi-pass/releases) and unzipped into `demo/`.
Re-running the script is safe: it skips the download when the data is already there, and
`--force` re-fetches.

## Regenerating the demo data (maintainers)

`demo_pre_run/` is one 2P plane (0) and one HCR FISH round (01) of JS078, at full
resolution and full frame:

```bash
python make_demo_data.py \
  --src /path/to/EASI_FISH/pipeline/JS078 \
  --dst ./demo_pre_run/JS078_demo
```

Then build the archive as noted in `fetch_demo_data.py`, attach it to a GitHub release, and
update `RELEASE_BASE` and the sha256 there. The golden table in `completed/` is the match CSV
from a validated run.

Do not XY-crop the HCR FISH volume to save size. Registration uses the surrounding tissue
context and several landmarks sit near the edge; cropping dropped median IoU from 0.38 to 0.16.
The data is a release asset, so its size is not a repo concern.
