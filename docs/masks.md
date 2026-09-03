# Bringing your own masks

Drop your masks in the locations below and Cellpose is skipped there. The run always names the
file it used, so you can see which happened:

```
HCR01: using masks already in place — HCR01_masks.tiff (619 MB), (39, 1993, 1992)
2P plane 0: no masks supplied (lowres_meanImg_C0_plane0_masks.tiff), segmenting
```

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

Two rules, both checked. Break either and the run stops, naming your file and the shape it
expected:

- **Same shape as the image they describe**: the functional mean image, or the HCR FISH volume
  as acquired, indexed `(Z, Y, X)`. Uncropped, unresampled.
- At most **65,535 cells** per image.

Give functional masks in the orientation of the mean image you supplied; the pipeline applies
`rotation_2p_to_HCR` to both together.

To segment again, delete the mask file and the `_seg.npy` beside it.

## If you already ran the pipeline

Steps skip when their output exists. So if you change the masks after a run, **delete
everything downstream of them** — otherwise your new masks are ignored and the run finishes
with the old cells.

Everything below is rebuilt from your masks.

Functional plane `N`:

```
2P/cellpose/lowres_meanImg_C0_plane{N}_seg.npy          ← this one shadows your masks
2P/cellpose/lowres_meanImg_C0_plane{N}_seg_rotated.tiff
2P/registered/lowres_plane{N}_masks_in_hires_space.tiff   (hi-res runs only)
2P/registered/twop_plane{N}_registration_params.npz
2P/registered/twop_plane{N}_aligned_3d.tiff
2P/registered/cascade_snapshots_plane{N}.pkl
MERGED/aligned_masks/twop_plane{N}_to_HCR01.csv
```

Keep `lowres_meanImg_C0_plane{N}.tiff` — that is the mean image, not a mask.

HCR FISH round `R`:

```
HCR/cellpose_aligned/{same filename as yours}
HCR/extract_intensities/{round}_probs_intensities.csv and .pkl
HCR/registrations/  entries for that round   (multi-round only)
MERGED/aligned_masks/*.csv
```

`MERGED/aligned_extracted_features/` rebuilds itself.

## Suite2p ROIs

No file needed: set `masks: "suite2p"` and the pipeline reads `stat.npy`, `iscell.npy` and
`ops.npy` from `2P/suite2p/plane{N}/`, painting every `iscell` ROI into a label image.

Your mask label is the **Suite2p ROI index + 1**, so you rejoin your own `F.npy` by `label - 1`.
EASI-PASS never reads your traces. It assumes the ROIs sit on the `ops['meanImg']` grid, true of
a plain Suite2p run.
