# Manifest

An [HJSON](https://hjson.github.io/) file (JSON with comments and relaxed syntax) with two
sections: `data` for what you are processing, `params` for how.

Start from a template rather than from scratch:

| Template | For |
|---|---|
| [`demo_tiff.hjson`](../examples/demo_tiff.hjson) | Functional + HCR FISH. **Start here** |
| [`demo_hcr_only.hjson`](../examples/demo_hcr_only.hjson) | HCR FISH rounds alone |
| [`param_example.hjson`](../examples/param_example.hjson) | Annotates the parameters in more depth. Has no `data` section, so read it alongside a template |

Hi-res and single-round cases need no manifest change: drop a `plane_{N}_hires.tiff` beside the
mean image, or leave one entry in `rounds`.

## `data`

| Field | Description |
|---|---|
| `base_path` | Folder containing your samples |
| `sample_name` | Folder name for this sample. Outputs are written under it. `mouse_name` is a synonym |
| `HCR_confocal_imaging.rounds` | One entry per round: `round` (e.g. `"01"`), `channels` (nuclear stain first), `resolution` (voxel size `[x, y, z]` in microns) |
| `HCR_confocal_imaging.reference_round` | The round all others register to. Pick the one with the best signal |
| `two_photon_imaging.sessions` | `functional_planes` (the first is the reference plane for landmarks), `input_format`, and optionally `masks`. Omit the whole section for HCR-FISH-only runs |

File naming is forgiving: `.tif` and `.tiff` both work, case is ignored, and a `{sample_name}_`
prefix is accepted.

## HCR FISH rounds only

Registers the rounds to the reference, segments them, matches them to each other, and extracts
intensities. No landmarks, no functional segmentation, no cross-modal step. Two ways in:

| | |
|---|---|
| Manifest has no `two_photon_imaging` section | Nothing to pass, it is inferred. Template: [`demo_hcr_only.hjson`](../examples/demo_hcr_only.hjson) |
| Manifest has one, but you want only the FISH half | `python master_pipeline.py --manifest your.hjson --only_hcr` |

`--only_hcr` is the one to reach for when the functional data is not ready yet, or when you are
re-running the molecular side of a manifest you otherwise want to leave alone. It cannot be
combined with `--check_alignment`, which exists to align the functional planes to FISH.

A single round is fine on its own: leave one entry in `rounds` and round-to-round registration
skips itself.

## `params`

| Section | Description |
|---|---|
| `HCR_to_HCR_registration` | Round-to-round global and local registration |
| `HCR_cellpose`, `2p_cellpose` | Cellpose model and parameters for each side |
| `twop_to_hcr_registration` | Cross-modal cascade: tile sizes, search ranges, thresholds |
| `intensity_extraction` | Background settings for probe intensity measurement |
| `rotation_2p_to_HCR` | `fliplr` / `flipud` to un-mirror the functional image, plus an optional coarse `rotation`. The flip is the part that has to be right |

Every section has working defaults in the templates.

## Functional input and masks

Two independent choices on the session. `input_format` says where the *image* comes from,
`masks` says where the *cells* come from, and they do not have to agree.

| Key | Value | Effect |
|---|---|---|
| `input_format` | `"tiff"` | **Use this.** Reads `2P/plane_{N}.tiff`, any microscope, any preprocessing |
| | `"suite2p"` / `"sbx"` | Legacy readers for the rig this was built on. Both work, neither is supported |
| `masks` | *omitted* | Cellpose segments the mean image |
| | `"suite2p"` | Reuse existing Suite2p ROIs, no segmentation. See [masks.md](masks.md) |

`input_format` is required whenever there is a `two_photon_imaging` section, with no default and
no override. `tiff` + `suite2p` is a normal pairing; both must describe the same pixel grid, so
export the TIFF from the same `ops['meanImg']` the ROIs were drawn on, uncropped.

## Hi-res structural images

Supply an already-stitched image as `2P/plane_{N}_hires.tiff`. The low-res mean image is placed
into it, and the alignment to the HCR FISH volume is computed at the higher resolution. Its
presence is the switch; there is no manifest change.

> `easipass/tiling.py` and `easipass/auto_stitching.py` do assemble tiles by phase correlation,
> but they assume our ScanBox tile geometry and naming, so this is not a general feature.
> Generalizing it needs an agreed tile-input format (per-tile files plus a nominal grid
> position), which is an open contribution we would welcome.

## When rounds register poorly

The knobs in `HCR_to_HCR_registration`:

| Knob | Try |
|---|---|
| `match_threshold` | lower, 0.3 to 0.2, to accept weaker correspondences |
| `count_floor` / `match_floor` | lower, to let sparse regions contribute |
| `max_spot_match_distance_um` | raise, if the tissue shifted a long way between rounds. Suspect this one when a region comes out untouched: set below the real shift, it rejects every candidate in a block, and the block silently falls back to no correction |

Round-to-round registration uses cell centroids, not detected spots, so check the reference
round's Cellpose segmentation first.
