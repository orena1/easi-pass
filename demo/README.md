# Demo: aligning a 2P image to an ex-vivo HCR volume (mouse JS078)

A small, real, end-to-end example you can run to confirm your install works and to
see the pipeline's inputs and outputs. It takes a single 2-photon mean image, aligns
it to a full-frame HCR confocal volume, segments cells in both, matches them, and writes
a per-cell table joining 2P identity to the 5 HCR gene channels.

This is the **stills / image-align** use case (`--tiff_only`): a static 2P image, not a
movie, so there are no activity traces — just cross-modal alignment + the molecular join.

## What's in this folder

```
demo/
├── README.md              ← you are here
├── JS078_demo.hjson       ← the manifest (edit base_path, then run)
├── make_demo_data.py      ← how the demo subset was assembled from full JS078 (reproducible)
├── fetch_demo_data.py     ← downloads the heavy inputs into to_run/
├── to_run/                ← the data you run the pipeline on (populated by fetch_demo_data.py)
│   └── JS078_demo/
│       ├── 2P/plane_0.tiff              (2P low-res mean image, ~1.6 MB)
│       ├── 2P/plane_0_hires.tiff        (2P hi-res stitched image, ~49 MB)
│       ├── HCR/JS078_demo_HCR01.tiff    (5-channel HCR volume, full frame, ~774 MB)
│       └── OUTPUT/2P/registered/        (pre-seeded so the run is reproducible)
│           ├── hires_stitched_plane0_to_HCR1_landmarks.csv   (18 BigWarp seed landmarks)
│           ├── lowres_plane0_masks_in_hires_space.tiff       (2P placement in hi-res space)
│           ├── lowres_meanImg_C0_plane0_rotated.tiff         (rotated 2P mean)
│           └── hires_stitched_plane0_rotated.tiff            (rotated 2P hi-res)
└── completed/             ← reference output to check your run against (small CSV)
```

`to_run/` is what a new user runs; `completed/` is the golden result to diff against.
Only the small text files are tracked in git — the imaging data lives on Zenodo
(see `fetch_demo_data.py`).

## Prerequisites

- The pipeline environment with **Cellpose 4 / cellpose-SAM** (the demo manifest uses
  `model_path: "cpsam"`, which auto-downloads — no model files to place). See the repo
  README's install section for the conda env.
- A GPU is recommended (`gpu: true` in the manifest); set `gpu: false` to run on CPU (slower).

## Run it

1. **Get the data:**
   ```bash
   cd demo
   python fetch_demo_data.py          # downloads into demo/to_run/JS078_demo/
   ```

2. **Point the manifest at it:** open `demo/JS078_demo.hjson` and set `base_path` to the
   absolute path of `demo/to_run` on your machine, e.g.
   `/home/you/ezfish_pipeline/demo/to_run`.

3. **Run the pipeline** (from the repo root):
   ```bash
   python master_pipeline.py --manifest demo/JS078_demo.hjson --tiff_only
   ```
   Stages: HCR segmentation → 2P segmentation → low-res→hi-res placement → 2P→HCR
   registration (using the shipped seed landmarks) → cell matching → merged table.

   **Answer the prompts as follows:**
   - `Verify 2P cellpose segmentations … press Enter` → press **Enter**.
   - `Output files exist. Overwrite all? [y/n]` (low-res→hi-res step) → **n**.
     This keeps the shipped 2P *placement*. The automated SIFT placement is fragile in
     the tiff-only path (on this plane it lands ~100 px off, which makes the 2P→HCR
     overlay come out stringy); the shipped placement is the production one, so the
     alignment reproduces the paper-quality overlay. Answering `y` regenerates it and
     may degrade the result.
   - `After checking QA images, choose [y/r/n]` (2P→HCR) → **y**.

## Expected output

The pipeline writes its results under `to_run/JS078_demo/OUTPUT/`. The key files:
```
OUTPUT/MERGED/aligned_masks/twop_plane0_to_HCR01.csv          # per-cell 2P<->HCR matches
OUTPUT/MERGED/aligned_extracted_features/full_table_*.pkl     # matches joined to the 5 HCR gene channels
OUTPUT/2P/registered/QualityCheck/plane0_AFTER_registration_overlay.tiff   # visual check
```
Compare `twop_plane0_to_HCR01.csv` against the golden copy in **`completed/`**
(`twop_plane0_to_HCR01.csv` + expected numbers in `completed/README.md`). Cell counts
and matches should be close; exact values depend on GPU / Cellpose version. The healthy
signal is a 2P→HCR cascade `Final: IoU ~0.48` with an accepted small global shift.

## Regenerating the demo data (maintainers)

`to_run/` is a *subset* of the full-resolution JS078 dataset — one functional plane
(plane 0) and one HCR round (01) — assembled with:
```bash
python make_demo_data.py \
  --src /mnt/nasquatch/data/2p/jonna/EASI_FISH/pipeline/JS078 \
  --dst ./to_run/JS078_demo
```
Everything is shipped at **full resolution and full frame** — the HCR volume is copied
verbatim (~774 MB, all 5 gene channels, all 39 Z slices), and the BigWarp landmarks are
copied verbatim (no coordinate shift, since nothing is cropped).

**Why no spatial crop:** an earlier version XY-cropped the HCR volume to save size, but
2P→HCR registration needs the surrounding HCR image context (and several landmark cells
sit near the tissue edge). Cropping halved alignment quality — plane0 best-match median
IoU dropped 0.38 → 0.16 vs the uncropped run — and made the overlay masks look
misaligned. The data lives on Zenodo anyway, so full-frame size is not a repo concern.
