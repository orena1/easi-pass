# Demo: aligning a 2P image to an ex-vivo HCR volume (mouse JS078)

A small, real, end-to-end example you can run to confirm your install works and to
see the pipeline's inputs and outputs. It takes a single 2-photon mean image, aligns
it to a full-frame HCR confocal volume, segments cells in both, matches them, and writes
a per-cell table joining 2P identity to the 5 HCR gene channels.

This is the **stills / image-align** use case (`input_format: "tiff"`): a static 2P image, not a
movie, so there are no activity traces, just cross-modal alignment and the molecular join.

## What's in this folder

```
demo/
├── README.md              ← you are here
├── JS078_demo.hjson       ← the manifest; nothing to edit
├── make_demo_data.py      ← how the demo subset was assembled from full JS078 (reproducible)
├── fetch_demo_data.py     ← downloads the imaging data from the GitHub release
├── demo_pre_run/          ← FRESH: the data you run the pipeline on (191 MB download)
│   └── JS078_demo/
│       ├── 2P/plane_0.tiff              (2P low-res mean image, ~1.6 MB)
│       ├── 2P/plane_0_hires.tiff        (2P hi-res stitched image, ~49 MB)
│       ├── HCR/JS078_demo_HCR01.tiff    (5-channel HCR volume, full frame, ~774 MB)
│       └── OUTPUT/2P/registered/        (pre-seeded landmarks + placement, so the run reproduces)
│           ├── hires_stitched_plane0_to_HCR1_landmarks.csv   (18 BigWarp landmarks)
│           ├── lowres_plane0_masks_in_hires_space.tiff       (2P placement in hi-res space)
│           ├── lowres_meanImg_C0_plane0_rotated.tiff         (rotated 2P mean)
│           └── hires_stitched_plane0_rotated.tiff            (rotated 2P hi-res)
└── completed/             ← the golden matches table, tracked in git, to diff against
```

You run the pipeline on **`demo_pre_run/`**, then compare your result against the golden
table in **`completed/`**, which is 398 KB and tracked in git, so the check costs no
download. Only
the text files and that table are in the repo; the imaging data is a GitHub release asset
fetched by `fetch_demo_data.py`.

## Prerequisites

- The pipeline environment with **Cellpose 4 / cellpose-SAM** (the demo manifest uses
  `model_path: "cpsam"`, which auto-downloads, so there are no model files to place). See the repo
  README's install section for the conda env.
- No GPU needed. The demo is one plane and one volume, which segment in reasonable time on a
  CPU. If there is a GPU, Cellpose uses it; the manifest's `gpu: true` means "if there is one",
  and `gpu: false` pins it to the CPU.

## Run it

Both commands run from the repository root. There is nothing to edit: the manifest's
`base_path` is relative, so it finds its own data.

1. **Get the data:**
   ```bash
   python demo/fetch_demo_data.py
   ```
   Downloads 191 MB from this repo's
   [releases page](https://github.com/orena1/easi-pass/releases), checks its sha256, and
   unpacks it into `demo/demo_pre_run/`. Budget about **1.3 GB free**: 790 MB of input
   images, and roughly 450 MB the run itself writes under `OUTPUT/`.

   If the download fails, the archive `JS078_demo_pre_run.zip` can be fetched by hand from
   that releases page and unzipped into `demo/`. Re-running the script is safe: it skips the
   download when the data is already there, and `--force` re-fetches.

2. **Run the pipeline:**
   ```bash
   python master_pipeline.py --manifest demo/JS078_demo.hjson
   ```
   Stages: prep → landmarks (already shipped, so no prompt) → 2P segmentation → HCR
   segmentation → probe intensities → low-res→hi-res placement → 2P→HCR registration →
   cell matching → merged table.

   **Answer the prompts as follows:**
   - `Verify 2P cellpose segmentations … press Enter` → press **Enter**.
   - `Overwrite? [y/n]` (low-res→hi-res step) → **n**, which keeps the shipped 2P placement.
     Answering `y` recomputes it and the demo may no longer reproduce.
   - `After checking QA images, choose [y/r/n]` (2P→HCR) → **y**.

## Expected output

The pipeline writes its results under `demo_pre_run/JS078_demo/OUTPUT/`. The key files:
```
OUTPUT/MERGED/aligned_masks/twop_plane0_to_HCR01.csv          # per-cell 2P<->HCR matches
OUTPUT/MERGED/aligned_extracted_features/full_table_*.csv     # matches joined to the 5 HCR gene channels
OUTPUT/2P/registered/QualityCheck/plane0_AFTER_registration_overlay.tiff   # visual check
```
Compare `twop_plane0_to_HCR01.csv` against the golden copy in **`completed/`**
(`twop_plane0_to_HCR01.csv` + expected numbers in `completed/README.md`). Cell counts
and matches should be close; exact values depend on GPU and Cellpose version. The healthy
signal is a 2P→HCR cascade `Final: IoU ~0.48` with an accepted small global shift.

## Regenerating the demo data (maintainers)

`demo_pre_run/` is one functional plane (0) and one HCR round (01) of JS078, at full
resolution and full frame:
```bash
python make_demo_data.py \
  --src /path/to/EASI_FISH/pipeline/JS078 \
  --dst ./demo_pre_run/JS078_demo
```
Then build the archive as noted in `fetch_demo_data.py`, attach it to a GitHub release, and
update `RELEASE_BASE` and the sha256 there. The golden table in `completed/` is the match CSV
from a validated run.

Do not XY-crop the HCR volume to save size. Registration uses the surrounding tissue context
and several landmarks sit near the edge; cropping dropped median IoU from 0.38 to 0.16. The
data is a release asset, so its size is not a repo concern.
