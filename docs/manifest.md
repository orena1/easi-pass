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
intensities. No landmarks, no 2P segmentation, no cross-modal step. Two ways in:

| | |
|---|---|
| Manifest has no `two_photon_imaging` section | Nothing to pass, it is inferred. Template: [`demo_hcr_only.hjson`](../examples/demo_hcr_only.hjson) |
| Manifest has one, but you want only the FISH half | `python master_pipeline.py --manifest your.hjson --only_hcr` |

`--only_hcr` is the one to reach for when the 2P data is not ready yet, or when you are
re-running the molecular side of a manifest you otherwise want to leave alone. It cannot be
combined with `--check_alignment`, which exists to align the 2P planes to FISH.

A single round is fine on its own: leave one entry in `rounds` and round-to-round registration
skips itself.

## `params`

| Section | Description |
|---|---|
| `HCR_to_HCR_registration` | Round-to-round global and local registration |
| `HCR_cellpose`, `2p_cellpose` | Cellpose model and parameters for each side |
| `twop_to_hcr_registration` | Cross-modal cascade: tile sizes, search ranges, thresholds |
| `intensity_extraction` | Background settings for probe intensity measurement |
| `rotation_2p_to_HCR` | `fliplr` / `flipud` to un-mirror the 2P image, plus an optional coarse `rotation`. The flip is the part that has to be right |

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
| `count_floor` / `match_floor` | lower, to let sparse regions contribute. ⚠ `match_floor` below ~8 is not safe: a 3D affine has 12 degrees of freedom and each match supplies 3 equations, so **4 points fit it exactly** — zero residual, nothing for RANSAC to reject, and the block emits an arbitrary transform it has no evidence for. Blocks like that are what produce swirls in the deform field |
| `max_spot_match_distance_um` | raise, if the tissue shifted a long way between rounds. Suspect this one when a region comes out untouched: set below the real shift, it rejects every candidate in a block, and the block silently falls back to no correction. ⚠ Too *high* fails the other way: in dense tissue a cap far above what a block can express lets the matcher pair cells that are simply near each other, and RANSAC fits a confident wrong answer. A reasonable ceiling is the block's own reach, `blocksize_xy × xy_resolution ÷ 2` |

Round-to-round registration uses cell centroids, not detected spots, so check the reference
round's Cellpose segmentation first.

### If a round will not lock at all

`global: … did not lock` or a coverage of 0 means the coarse affine failed, and no local setting
can recover it. Two causes account for most of them:

**The round is rotated relative to the reference.** The matcher correlates *axis-aligned* patches
and has no rotation invariance, so a residual angle θ displaces a feature at the patch edge by
`r·sin θ` — at an 80 µm radius that is 11 µm at 8°, comparable to the inlier gate. A few degrees
is tolerated; past roughly 5–8° the round dies. A coarse hand-rotation to `_to_HCR01` is not
enough on its own, and a 0/90/180/270 check cannot see the residual.

**`global.angle_search_deg` is `0`, so the scan is OFF until you ask for it.** Set it to `15` to
turn it on for a sample. There is a commented block ready to uncomment in
[`demo_hcr_only.hjson`](../examples/demo_hcr_only.hjson),
[`demo_tiff.hjson`](../examples/demo_tiff.hjson) and
[`param_example.hjson`](../examples/param_example.hjson):

```hjson
global: {
    context_radius_um: [40, 60, 80]
    match_threshold: 0.3
    select_metric: "mi"

    angle_search_deg: 15           // half-span: scans -15..+15. 0 = off
    angle_step_deg: 5              // step within the span
    angle_scan_radius_um: 80       // default: the largest context_radius_um
    angle_keep_zero_margin: 2.0    // how far a non-zero angle must beat 0° by
}
```

It corrects the angle in-pipeline and leaves the filed TIFF untouched. It is a **rescue, not a
re-optimisation**: a non-zero angle is only taken if it beats 0° by `angle_keep_zero_margin` on
above-chance inliers, so a healthy round is left exactly as it was. Widen the span if a round
still fails. The chosen angle appears in `registration_summary.csv` as `angle_deg` and in the
candidate tag as `_a+12`.

⚠ **Turning it on can move a round that already registers.** PS388_1L R03 and R07 took −10° and
+10° once it was enabled, and both improved, but that is a result to opt into per sample. This is
why the default is `0`: every existing dataset re-runs bit-identical unless you set the key.

**Nothing is resampled.** The volume is rotated nearest-neighbour and the centroids
analytically, so no intensity is interpolated or softened. Probe intensities are measured on the
acquired stack through `HCR/cellpose/` masks and never pass through the registration at all, so
no registration setting can alter a probe number.

| Knob | Default | |
|---|---|---|
| `angle_search_deg` | `0` | half-span in degrees; `0` disables the scan. Set `15` to enable |
| `angle_step_deg` | `5` | 5° is inside the matcher's own tolerance |
| `angle_keep_zero_margin` | `2.0` | how much a non-zero angle must beat 0° by. Lowering it re-optimises rounds that already work — measured across 5 samples, healthy rounds peak at 1.33× while a genuinely rotated one reached 2.6× |
| `angle_scan_radius_um` | largest `context_radius_um` | radius the scan is scored at |

**The rounds differ in pixel size.** Handled automatically — the moving round is resampled onto
the reference grid before matching, so one voxel radius is one physical radius in both. Nothing
to set.

## Registering rounds unattended

By default the round registration stops twice per round for a human to pick a row: once on the
coarse affine, once on the local warp. On a sample with eight rounds that is fourteen stops
spread over several hours, so a run left alone overnight gets no further than the first one.

```bash
python master_pipeline.py --manifest your.hjson --only_hcr --auto_hcr_registration
```

or, to make it a property of the sample, `params.automation.hcr_to_hcr: "auto"`.

Nothing is computed differently. Every coarse radius and every local blocksize is still run,
written and listed; only the asking goes away. The coarse row goes to whichever radius
`global.select_metric` favours and the local row to the top-ranked candidate:

| `select_metric` | Picks |
|---|---|
| `mi` (default) | best mutual information on the raw DAPI, an image-based verdict independent of the centroids the affine was fitted to |
| `median_resid` | lowest mutual-inlier residual, tie-broken by more inliers, ignoring any radius no better than chance |
| `above_chance` | most reciprocal inliers above the 45°-spin null |

A round that is already registered is kept rather than recomputed, and every round's selection
is written into the manifest as soon as it is made, so an interrupted run resumes where it
stopped instead of repeating deforms that are already on disk.

The review moves after the run: **`OUTPUT/HCR/registrations/registration_summary.csv`** holds
one row per round with its pick, MI, mutual-inlier residual, fraction of matched cells within
5 µm, block coverage, red-flag verdict and the path to its overlay. Read it before using the
rounds; open the overlay for anything marked `WARN` or `RED_FLAG`. To overrule a pick, edit
that round's entry in `HCR_selected_registrations` to another candidate tag (they are all on
disk) and re-run.
