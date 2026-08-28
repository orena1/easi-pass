# Bringing your own masks

Hand in masks for either side and EASI-PASS skips Cellpose there, going straight to registering
and matching them. Each segmentation step looks for your masks first and skips itself if it
finds them, and the run prints which file it used, or says it found none and is segmenting.

| Masks you have | Put them here |
|---|---|
| Functional plane `N` | `OUTPUT/2P/cellpose/lowres_meanImg_C0_plane{N}_masks.tiff` |
| HCR FISH round `R` | `OUTPUT/HCR/cellpose/HCR{R}_masks.tiff` |
| HCR FISH masks already warped into the reference frame | `OUTPUT/HCR/cellpose_aligned/` instead, which skips the warping step |

Naming in `cellpose/` and `cellpose_aligned/`: the reference round is plain
`HCR01_masks.tiff`, and non-reference rounds are `HCR{R}_to_HCR{ref}_masks.tiff`, so round 02
against reference 01 is `HCR02_to_HCR01_masks.tiff`.

## Format

A label image is one integer per pixel: `0` background, `1, 2, 3…` cells, the way Cellpose
numbers them. Any integer type. `.npy` is accepted in place of `.tiff` under the same name, as
is Cellpose's own `_seg.npy` if you hand-corrected in its GUI.

Two rules, both checked before anything runs:

- **Same shape as the image they describe**: the functional mean image, or the HCR FISH volume
  as acquired, indexed `(Z, Y, X)`. Uncropped, unresampled.
- At most **65,535 cells** per image.

Give functional masks in the orientation of the mean image you supplied; the pipeline applies
`rotation_2p_to_HCR` to both together.

To segment again, delete the mask file and the `_seg.npy` beside it.

## Suite2p ROIs

No file needed: set `masks: "suite2p"` and the pipeline reads `stat.npy`, `iscell.npy` and
`ops.npy` from `2P/suite2p/plane{N}/`, painting every `iscell` ROI into a label image.

Your mask label is the **Suite2p ROI index + 1**, so you rejoin your own `F.npy` by `label - 1`.
EASI-PASS never reads your traces. It assumes the ROIs sit on the `ops['meanImg']` grid, true of
a plain Suite2p run.
