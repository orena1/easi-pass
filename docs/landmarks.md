# Placing 2P-to-HCR landmarks in BigWarp

The cross-modal step needs a small set of hand-placed correspondences between the
two-photon image and the FISH volume. The pipeline pauses and asks for them the first
time it needs them; this page covers what to install, where the file goes, and what it
has to contain.

Landmarks are placed in [Fiji](https://fiji.sc/)'s BigWarp, under
**Plugins > BigDataViewer > Big Warp**.

## What the pipeline asks for

When landmarks are missing, the pipeline prints the two images to open and the exact path
to save to, then waits:

```
Moving: .../OUTPUT/2P/registered/hires_stitched_plane0_rotated.tiff
Target: .../JS078_demo/HCR/JS078_demo_HCR01.tiff
```

Both files already exist at that point: the target is your acquired reference
volume, read where it is. The moving image is intensity data, not masks, and
segmentation has not run yet, which is deliberate: a bad alignment shows up before you
spend time on Cellpose.

Save to the path the prompt names. It follows this pattern, under
`{base_path}/{sample_name}/OUTPUT/2P/registered/`:

| Mode | Filename |
|---|---|
| Standard (low-res mean image) | `plane{N}_to_HCR{R}_landmarks.csv` |
| Hi-res stitched | `hires_stitched_plane{N}_to_HCR{R}_landmarks.csv` |

`{R}` is the reference round with leading zeros stripped, so round `01` gives `HCR1`.

## Placing the points

Landmarks are placed on the reference plane only. Other planes reuse them.

- **Count.** The shipped demo uses 18. Roughly 15 to 25 works well. Below about 10 the
  thin-plate spline is underdetermined and the warp drifts between points.
- **Spread.** Cover the whole field, including near the edges. Points clustered in the
  centre leave the rim unconstrained, which is where cross-modal alignment degrades first.
  Do not crop the FISH volume to save space: the registration uses the surrounding tissue
  context, and several useful landmarks sit near the tissue boundary.
- **What to match.** Cell bodies and vasculature that you can identify unambiguously in
  both modalities. Distinctive spacing between neighbours is more reliable than any single
  bright object.
- **Z.** The 2P image is a single plane, so its `z` is 0 throughout. Set the FISH `z` to the
  slice where the matched cell is actually in focus. That varies across the field, and the
  pipeline expects it to.

Export with **File > Export landmarks**.

## File format

BigWarp writes a headerless CSV. The pipeline accepts the 2D (6 column) and 3D (8 column)
exports; 3D is what you get from a volume target and is what you want.

```
"Pt-0","true","1518.4338","1961.0442","0.0","1450.5525","1997.8493","183.4880"
```

| Position | Column | Units |
|---|---|---|
| 1 | name | any label |
| 2 | enabled | `true` / `false` |
| 3, 4, 5 | 2P x, y, z | **pixels** (BigWarp treats the 2P image as uncalibrated) |
| 6, 7, 8 | FISH x, y, z | **microns** |

Rows with `enabled` set to `false` are ignored, so you can disable a bad point without
deleting it.

### The FISH volume must be calibrated

The units in columns 6 to 8 are whichever units the volume declares. If the FISH TIFF
carries no ImageJ micron calibration, BigWarp exports **pixels**, the pipeline divides them
by a micron resolution anyway, and every landmark lands at the wrong scale. Nothing
downstream can detect this, so the pipeline now refuses to run instead of guessing.

Check with **Image > Properties** in Fiji: unit should be `micron`, with pixel
width/height/depth set to your acquisition's voxel size. Fix it and re-export the landmarks
if it is wrong. A `resolution` entry in the manifest does not substitute, because it says
how big a voxel is and not which units BigWarp wrote.

## Settling the alignment before committing to a full run

Cross-modal alignment is the step most likely to need another attempt. `--check_alignment`
stops after registering and matching 2P to the reference round, so you can judge the result
without acquiring or processing later rounds:

```bash
python master_pipeline.py --manifest your_manifest.hjson --check_alignment
```

Re-run without the flag to continue. Check the QA overlays under
`OUTPUT/2P/registered/QualityCheck/` before you do.

## If the alignment looks wrong

- **Everything offset by a constant amount.** Usually the 2P orientation. Check
  `params.rotation_2p_to_HCR` and answer the orientation prompt with the flip that matches.
- **Centre fine, edges stretched.** Too few landmarks, or none near the rim. Add points
  toward the boundary.
- **Overlay looks stringy or scrambled.** The 2P placement is off rather than the landmarks.
  In hi-res mode, check the low-res to hi-res placement step.
- **Overlay looks right, merged table looks wrong.** Suspect z. Confirm the FISH `z` values
  are per-cell focal slices and not all the same value.
