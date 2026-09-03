# Bringing your own masks

Hand in masks for either side and EASI-PASS skips Cellpose there, going straight to registering
and matching them. Put the files in the locations below, alongside what the pipeline writes
itself, and the run reports which of the two happened for every plane and round:

```
HCR01: using masks already in place — HCR01_masks.tiff (619 MB), (39, 1993, 1992)
2P plane 0: no masks supplied (lowres_meanImg_C0_plane0_masks.tiff), segmenting
```

Cellpose runs only in the second case. The message always names the file, so you can see at a
glance whether the masks in play are the ones you put there.

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

Two rules, both checked, and a mask that breaks either stops the run naming the file and the
shape expected rather than producing plausible wrong cells:

- **Same shape as the image they describe**: the functional mean image, or the HCR FISH volume
  as acquired, indexed `(Z, Y, X)`. Uncropped, unresampled.
- At most **65,535 cells** per image.

Functional masks are checked as they are read. HCR FISH masks placed at the canonical
`cellpose/` name are checked at the round-to-round and intensity steps instead, which compare
every mask against its own volume — the same error, just further into the run.

Give functional masks in the orientation of the mean image you supplied; the pipeline applies
`rotation_2p_to_HCR` to both together.

To segment again, delete the mask file and the `_seg.npy` beside it.

## Substituting masks into a run that already happened

On a fresh run, dropping the files in is all there is to it — there is nothing of the
pipeline's there yet, so anything it finds is yours.

Into a run that has already segmented, **delete everything downstream of the masks first.**
The pipeline skips any step whose output exists, so otherwise your new masks sit there unused
and the run finishes with the old cells. On the functional side it will at least tell you
this is happening — a `_masks.tiff` newer than its `_seg.npy` gets called out by name — but on
the FISH side nothing notices.

Deleting the whole `OUTPUT/` folder is the simple option, **but your masks live inside it**, so
copy them somewhere else first or you will delete your own input. Otherwise work down the chain;
everything listed is derived and will be rebuilt.

**Functional plane `N`** — your file is `2P/cellpose/lowres_meanImg_C0_plane{N}_masks.tiff`:

| Delete | Why |
|---|---|
| `2P/cellpose/lowres_meanImg_C0_plane{N}_seg.npy` | Read in preference to your masks. **The one that silently shadows them** |
| `2P/cellpose/lowres_meanImg_C0_plane{N}_seg_rotated.tiff` | Your masks flipped to the HCR FISH orientation |
| `2P/registered/lowres_plane{N}_masks_in_hires_space.tiff` | Placed into the hi-res image. Hi-res runs only |
| `2P/registered/twop_plane{N}_registration_params.npz` | The cross-modal transform, fitted to the old cells |
| `2P/registered/twop_plane{N}_aligned_3d.tiff`, `cascade_snapshots_plane{N}.pkl` | Cascade output and its QA snapshots |
| `MERGED/aligned_masks/twop_plane{N}_to_HCR01.csv` | The match table |

Keep `lowres_meanImg_C0_plane{N}.tiff` — that is the mean image, not a mask.

**HCR FISH round `R`** — your file is `HCR/cellpose/HCR{R}_masks.tiff`, or
`HCR{R}_to_HCR{ref}_masks.tiff` for a non-reference round:

| Delete | Why |
|---|---|
| `HCR/cellpose_aligned/{same name}` | Your masks warped into the reference frame |
| `HCR/extract_intensities/{round}_probs_intensities.csv` and `.pkl` | Per-cell intensities measured through the old masks |
| `HCR/registrations/` entries for that round | Round-to-round registration is centroid-seeded, so it is fitted to the masks. Multi-round only |
| `MERGED/aligned_masks/*.csv` | Match tables against this round |

The merged feature tables in `MERGED/aligned_extracted_features/` look after themselves: they
rebuild whenever an intensity file is newer.

## Suite2p ROIs

No file needed: set `masks: "suite2p"` and the pipeline reads `stat.npy`, `iscell.npy` and
`ops.npy` from `2P/suite2p/plane{N}/`, painting every `iscell` ROI into a label image.

Your mask label is the **Suite2p ROI index + 1**, so you rejoin your own `F.npy` by `label - 1`.
EASI-PASS never reads your traces. It assumes the ROIs sit on the `ops['meanImg']` grid, true of
a plain Suite2p run.
