# EASI-PASS

Match cells between two-photon functional imaging and multi-round in-situ molecular imaging.

Give EASI-PASS a mean image from a functional recording and one or more EASI-FISH volumes. It
segments cells in both, registers them onto each other, matches them across modalities, and
writes a per-cell table joining functional identity to molecular readout. It also runs on FISH
rounds alone, with no functional data.

Not included: processing raw recordings, ΔF/F, tile stitching. Those run upstream, and
EASI-PASS takes their output as input.

[What it needs](#what-it-needs) · [Ways to run this](#ways-to-run-this) · [Installation](#installation) · [Demo](#start-with-the-demo) · [Your own data](#running-your-own-data) · [What it does](#what-it-does) · [What you get](#what-you-get) · [Manifest](#manifest) · [Outputs](#what-the-pipeline-writes) · [Re-running](#re-running) · [Citation](#citation)

## What it needs

| Input | Format |
|---|---|
| Functional field of view | One 2D mean image per plane, TIFF |
| FISH rounds | One multi-channel 3D volume per round, TIFF |
| Hi-res structural image *(optional)* | One stitched 2D TIFF per plane. Improves the alignment when the mean image is too coarse to landmark directly |
| A few landmarks | Placed once in [BigWarp](https://imagej.net/plugins/bigwarp), between one functional plane and the reference FISH volume. Not needed for FISH-only runs, and the demo ships its own |

Everything else is set in a manifest. The run stops and waits at four points: to set the
orientation, place landmarks, check the segmentation, and accept the alignment. The rest is
automatic.

## Ways to run this

No mode flags to learn: the pipeline works out what to do from the manifest, and these combine.

| You have | What you do | Template |
|---|---|---|
| **Functional + FISH** | Place landmarks once, get a per-cell table joining the two. The main case, and the demo | [`demo_tiff.hjson`](examples/demo_tiff.hjson) |
| **…plus a hi-res structural image** | Drop it beside the mean image as `plane_{N}_hires.tiff`. Its presence is the switch, no manifest change | same |
| **FISH only** | Omit `two_photon_imaging`, or pass `--only_hcr` to skip the functional half of a manifest that has one | [`demo_hcr_only.hjson`](examples/demo_hcr_only.hjson) |
| **One FISH round** | Leave one entry in `rounds`. Round-to-round registration skips itself | same |
| **Masks already segmented** | Put them where the stage would have written them; that stage skips. [Details](#bringing-your-own-masks) | any |
| **Only the alignment, for now** | `--check_alignment` stops after the reference round, so later rounds need not be imaged yet | any |

## Installation

Two routes to the identical environment. Use whichever tool you already have; either takes
about four minutes.

**With conda:**

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass
conda env create -f environment.yml && conda activate easipass
pip install -e . -c requirements.txt
```

**With [uv](https://docs.astral.sh/uv/)**, which downloads its own copy of Python, so nothing
has to be set up first:

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e . -c requirements.txt
```

Activate again in every new shell: `conda activate easipass`, or `source .venv/bin/activate`
(`.venv\Scripts\activate` on Windows). Not plain `pip`, because the pipeline needs Python 3.12
and installing into an older one fails with errors that name the wrong thing.

`requirements.txt` pins the tested versions, so keep `-c` on any later install into the same
environment:

```bash
pip install -e ".[notebooks,analysis]" -c requirements.txt
```

<details>
<summary>Installing uv, if you do not have it</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                 # macOS, Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"      # Windows
```

Then open a new shell, or `export PATH="$HOME/.local/bin:$PATH"`.
</details>

<details>
<summary>Or plain venv, if you already have Python 3.12</summary>

Check the version first, because the failure otherwise is obscure:

```bash
python3 -V        # must be 3.12 or newer
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -c requirements.txt
```

If `python3 -m venv` itself fails, your distribution splits it into a separate package
(`sudo apt install python3-venv` on Debian and Ubuntu).
</details>

The pipeline is developed and tested on Linux, so that is where it is known to run end to end.
The CUDA libraries are Linux-only, so a GPU only helps there.

Cross-modal runs also need [Fiji](https://fiji.sc/)'s BigWarp for landmarks
(Plugins > BigDataViewer > Big Warp). [docs/landmarks.md](docs/landmarks.md) is what the
pipeline needs from you; [docs/BigWarp_Tips.md](docs/BigWarp_Tips.md) is how to drive BigWarp.

### Do you need a GPU?

No. Only Cellpose uses one. A full FISH volume (2500 x 2500 x 100 px) segments in a few minutes
on a GPU and an hour or two without one; the demo's single plane is fine either way. Set
`gpu: false` in a cellpose block to force the CPU. **RAM matters more:** budget roughly 25 GB
while a 2048 x 2048 x 100 round is registered.

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Both halves matter. The version should end `+cu124`, since a bare `2.5.1` is a CPU-only build.
Any NVIDIA GPU works given driver **525 or newer** and a card no newer than Hopper (CUDA 12.4
does not cover the RTX 50 series). Either bound gives `False` on a machine that plainly has a
GPU, so the pipeline names the card it found, says why it could not use it, and carries on with
the CPU.

## Start with the demo

[`demo/`](demo/README.md) is one two-photon plane from mouse JS078 aligned to a 5-channel FISH
volume, with a reference result to check yourself against. Nothing to edit.

```bash
python demo/fetch_demo_data.py
python master_pipeline.py --manifest demo/JS078_demo.hjson
```

The first command pulls 191 MB from the [releases page](https://github.com/orena1/easi-pass/releases)
and checks its sha256; allow about 1.3 GB of disk in total. The run pauses three times to let
you check intermediate output, and `demo/README.md` gives the answers.

Three warnings appear on every run and mean nothing: `pynwb not installed` from Suite2p,
`FutureWarning: You are using torch.load with weights_only=False` from Cellpose loading its own
model, and a `SyntaxWarning` from inside SimpleITK.

### Looking at what came out

A finished run leaves you with a table and no obvious place to start.
[`demo/explore_results.ipynb`](demo/explore_results.ipynb) opens it and plots what is worth
checking first: what the columns are, how far the two matchers agree, where the plane landed,
one map per probe, and three matched pairs as overlaid masks. That last one is what tells you a
match is real rather than merely counted.

```bash
jupyter lab demo/explore_results.ipynb
```

The same plots without Jupyter, saved as one figure beside your results. Both work on any
finished `OUTPUT` folder:

```bash
python demo/explore_results.py                        # the demo run
python demo/explore_results.py --output PATH/OUTPUT   # your own run
```

## Running your own data

**1. Copy a template.**

| Template | For |
|---|---|
| [`demo_tiff.hjson`](examples/demo_tiff.hjson) | **Start here.** A 2P mean image per plane as `plane_{N}.tiff` |
| [`demo_hcr_only.hjson`](examples/demo_hcr_only.hjson) | FISH rounds alone, no functional data |

Either runs as it stands once the paths are yours; hi-res and single-round cases need no
manifest change. [`param_example.hjson`](examples/param_example.hjson) annotates the parameters
in more depth, but has no `data` section, so read it alongside a template rather than starting
from it.

**2. Put your files where the manifest expects them.**

`base_path` is the folder that *contains* your samples, so several manifests can share one and
differ only by `sample_name`. For data at `/data/experiments/M12/`:

```
base_path:   "/data/experiments"
sample_name: "M12"
```
```
/data/experiments/M12/
├── 2P/
│   ├── plane_0.tiff        your functional mean image, one per plane
│   └── plane_0_hires.tiff  optional, and must already be stitched
├── HCR/
│   ├── HCR01.tiff          reference round
│   └── HCR02.tiff          any further rounds
└── OUTPUT/                 created by the pipeline
```

Only the numbers have to line up: `{N}` in `plane_{N}.tiff` matches an entry in
`functional_planes`, and `{R}` in `HCR{R}.tiff` matches a `round` value. `.tif` and `.tiff` both
work, case is ignored, a `{sample_name}_` prefix is accepted, and `mouse_name` is a synonym for
`sample_name`.

**3. Run.**

```bash
python master_pipeline.py --manifest examples/your_manifest.hjson
```

Cross-modal alignment is the step most likely to need another attempt, since it depends on your
landmarks, the functional segmentation, and whether the recovered tissue really contains the
imaged field. Settle it first:

```bash
python master_pipeline.py --manifest examples/your_manifest.hjson --check_alignment
```

That segments the reference round only, matches the functional planes to it, writes the match
tables and QA overlays, and stops. Review `OUTPUT/2P/registered/QualityCheck/`, then re-run
without the flag; everything the check produced is reused.

### Bringing your own masks

Hand in masks for either side and EASI-PASS skips Cellpose there, going straight to registering
and matching them. Each segmentation step looks for your masks first and skips itself if it
finds them, and the run prints which file it used, or says it found none and is segmenting.

| Masks you have | Put them here |
|---|---|
| Functional plane `N` | `OUTPUT/2P/cellpose/lowres_meanImg_C0_plane{N}_masks.tiff` |
| FISH round `R` | `OUTPUT/HCR/cellpose/HCR{R}_masks.tiff` |
| FISH masks you have already warped into the reference frame | `OUTPUT/HCR/cellpose_aligned/` instead, which skips the warping step |

A label image is one integer per pixel: `0` background, `1, 2, 3…` cells, the way Cellpose
numbers them. Any integer type. `.npy` is accepted in place of `.tiff` under the same name, as
is Cellpose's own `_seg.npy` if you hand-corrected in its GUI. Two rules, both checked before
anything runs:

- **Same shape as the image they describe**: the functional mean image, or the FISH volume as
  acquired, indexed `(Z, Y, X)`. Uncropped, unresampled.
- At most **65,535 cells** per image.

Give functional masks in the orientation of the mean image you supplied; the pipeline applies
`rotation_2p_to_HCR` to both together. To segment again, delete the mask file and the `_seg.npy`
beside it.

**Suite2p ROIs** need no file: set `masks: "suite2p"` and the pipeline reads `stat.npy`,
`iscell.npy` and `ops.npy` from `2P/suite2p/plane{N}/`, painting every `iscell` ROI into a label
image. Your mask label is the **Suite2p ROI index + 1**, so you rejoin your own `F.npy` by
`label - 1`; EASI-PASS never reads your traces. It assumes the ROIs sit on the `ops['meanImg']`
grid, true of a plain Suite2p run.

Naming, in `cellpose/` and `cellpose_aligned/`: the reference round is plain
`HCR01_masks.tiff`, and non-reference rounds are `HCR{R}_to_HCR{ref}_masks.tiff`, so round 02
against reference 01 is `HCR02_to_HCR01_masks.tiff`.

## What it does

**Before any segmentation**

| Step | |
|---|---|
| **1. Orient the functional image** | The pipeline prints both paths and waits. Open them, and if one is mirrored, add `fliplr` or `flipud` to `rotation_2p_to_HCR`. ScanBox input is stitched here too |
| **2. Place landmarks** | A handful of points in BigWarp, functional plane against the reference FISH volume. Before Cellpose on purpose, so you see a bad alignment in minutes rather than after an hour of segmentation |

**Segmentation**

| Step | |
|---|---|
| **3. Functional** | Cellpose on each mean image |
| **4. Molecular** | Cellpose per FISH plane, linked across planes into 3D cells |

**Molecular side**, once, covering all rounds

| Step | |
|---|---|
| **5. Round-to-round registration** | Each round onto the reference round. Cell centroids initialize a global affine (RANSAC), then a block-wise deformable refinement (BigStream). Labels are warped into the reference frame |
| **6. Probe intensity extraction** | Per-cell fluorescence per channel, with local background |

**Cross-modal**, per plane

| Step | |
|---|---|
| **7. Low-res to hi-res placement** | Only when a hi-res structural image is supplied |
| **8. Registration** | Landmarks define a thin-plate spline surface through the FISH volume, then a rigid search, a global affine, and a coarse-to-fine tile cascade |
| **9. Matching** | Mask overlap (IoU) and soma-print, both reported per cell |

**Output**

| Step | |
|---|---|
| **10. Merged table** | One row per cell: matched identities, per-gene intensities across rounds, match-quality scores |

FISH-only runs skip steps 1, 2, 3, 7 and 8, and at step 9 match rounds to each other instead of
to a functional plane.

Three things worth knowing:

- **A flip is not a rotation.** Only the flip has to be right at step 1, because BigWarp cannot
  mirror an image. You never set the rotation: the landmark pairs you place at step 2 already
  describe it.
- **Round-to-round registration uses cell centroids**, not detected spots. If rounds register
  poorly, check the reference round's Cellpose segmentation first, since every centroid is from
  it.
- **Step 5 shows you every alignment it tried.** It runs the global alignment once per entry in
  `context_radius_um` (40, 60, 80 µm by default) and writes each candidate's transform and QC
  image before you choose. The scores disagree often enough that it marks a suggestion rather
  than deciding, so look at the images.

If a round still registers poorly, the knobs in `HCR_to_HCR_registration` are:

| Knob | Try |
|---|---|
| `match_threshold` | lower, 0.3 to 0.2, to accept weaker correspondences |
| `count_floor` / `match_floor` | lower, to let sparse regions contribute |
| `max_spot_match_distance_um` | raise, if the tissue shifted a long way between rounds. Suspect this one when a region comes out untouched: set below the real shift, it rejects every candidate in a block, and the block silently falls back to no correction |

## What you get

**The per-cell matching table**, at `OUTPUT/MERGED/aligned_masks/twop_plane{N}_to_HCR01.csv`.
One row per candidate functional/FISH pair. The demo's first row, as it appears in the file:

| mask1 | mask2 | iou | iou_at_mask1_z | is_best_match | somaprint_hcr_label | somaprint_confident |
|---|---|---|---|---|---|---|
| 1 | 20646 | 0.064 | 0.287 | True | 20646 | True |

Functional cell 1 pairs with FISH cell 20646, both matchers agree, and overlap is weak in 3D but
better within the plane, which is normal for one plane cutting a volume. Every column:

| Column | Meaning |
|---|---|
| `mask1`, `mask2` | Functional cell id, FISH cell id |
| `iou`, `iou_at_mask1_z` | Mask overlap, in 3D and in the functional plane |
| `containment_2p`, `containment_hcr_at_z` | Directional overlap, each way |
| `mask1_size`, `mask2_size`, `mask2_size_at_mask1_z` | Mask sizes, in voxels |
| `intersection` | Shared voxels |
| `is_best_match` | The accepted overlap-based 1:1 match |
| `neighborhood_iou`, `neighborhood_window_px` | Overlap of the local neighbourhood, and the window it used |
| `somaprint_hcr_label` | Soma-print's call for this cell, independent of overlap |
| `somaprint_best_score`, `somaprint_second_score` | Its best and runner-up scores |
| `somaprint_confident` | Whether best separates significantly from runner-up |

Both matchers are reported for every cell and never reconciled, so you set your own thresholds.

### The feature table

`OUTPUT/MERGED/aligned_extracted_features/full_table_{feature}_twop_plane{N}.csv` (and `.pkl`)
joins those matches to per-gene intensities. One row per FISH cell in the reference round, one
file per feature, single header row.

These are the first three matched rows of the demo's `full_table_mean_twop_plane0.csv`, complete
except that the decimals are shortened. The demo is a single round with five channels, so this
is every column it has:

| mask_id_main | mean_round_01_DAPI | mean_round_01_GCAMP | mean_round_01_PV | mean_round_01_SST | mean_round_01_TDTOMATO | twoP_iou_match | twoP_iou | twoP_somaprint_match | twoP_somaprint_confident | plane |
|---|---|---|---|---|---|---|---|---|---|---|
| 6078 | 6.866 | 1.221 | 0.0607 | 0.0017 | 0.752 | 916 | 0.536 | 916 | True | 0 |
| 7372 | 5.861 | 1.044 | 0.0045 | 0.0002 | 0.493 | 629 | 0.390 | 629 | True | 0 |
| 8399 | 7.441 | 1.267 | 0.0070 | 0.0003 | 0.831 | 1194 | 0.028 | 1224 | True | 0 |

Read a row as: this FISH cell, its intensity in every channel, and which functional cell it is.
The third row is the one to understand before trusting either matcher, since overlap and
soma-print name different functional cells (1194 against 1224) on a weak overlap of 0.028.

| Column | Meaning |
|---|---|
| `mask_id_main` | The FISH cell, in the reference round. The row is about this cell |
| `plane` | The functional plane this file covers |
| `{feature}_round_{R}_{gene}` | One column per channel per round, named for the channels in your manifest |
| `twoP_iou_match`, `twoP_iou` | The functional cell matched by mask overlap, and how good that overlap was |
| `twoP_somaprint_match` | The functional cell soma-print picked, independently |
| `twoP_somaprint_confident` | Whether that pick cleared its gate. Always `True`/`False`, never blank |

**Multi-round runs add a group per later round `R`**, absent above because the demo has one
round:

| Column | Meaning |
|---|---|
| `round_{R}_iou_match`, `round_{R}_iou` | The cell by overlap alone, and that overlap |
| `round_{R}_hybrid_match` | The cell by the full matcher. **The gene columns are joined on this one** |
| `round_{R}_hybrid_matched_by` | `overlap` when overlap alone was trusted, `somaprint` when soma-print recovered it |
| `round_{R}_somaprint_score`, `_second_score` | Scores behind a soma-print recovery, blank for an overlap match |

```python
matched   = df.round_02_hybrid_match.notna()
by_iou    = df.round_02_iou_match.notna()
recovered = df.round_02_hybrid_matched_by == 'somaprint'
```

Three things that trip people up:

- **A blank means no match, not zero.** Reference-round gene columns are never blank, since
  measuring a cell does not depend on matching it.
- **A soma-print pick is not always a confident pick.** In the demo 1,387 cells get a pick and
  1,149 clear the gate, so `twoP_somaprint_match.notna()` and `twoP_somaprint_confident` ask
  different questions.
- **Sizes, containments and intersections are not repeated here.** They are columns of the
  matching table above.

In the demo, 1,199 of the 1,439 segmented functional cells get a 1:1 overlap match (83%) at a
median overlap of 0.29 in the plane, and soma-print confidently calls 1,149; the rates differ
because the matchers are independent. [`demo/completed/`](demo/completed/README.md) has a
tracked copy to diff your run against.

## Manifest

An [HJSON](https://hjson.github.io/) file (JSON with comments and relaxed syntax) with two
sections: `data` for what you are processing, `params` for how.

**`data`**

| Field | Description |
|---|---|
| `base_path` | Folder containing your samples |
| `sample_name` | Folder name for this sample. Outputs are written under it. `mouse_name` is a synonym |
| `HCR_confocal_imaging.rounds` | One entry per round: `round` (e.g. `"01"`), `channels` (nuclear stain used for registration first), `resolution` (voxel size `[x, y, z]` in microns, from your confocal metadata) |
| `HCR_confocal_imaging.reference_round` | The round all others register to. Pick the one with the best signal |
| `two_photon_imaging.sessions` | `functional_planes` (the first is the reference plane for landmarks), `input_format`, and optionally `masks`. Omit the whole section for FISH-only runs |

**`params`**

| Section | Description |
|---|---|
| `HCR_to_HCR_registration` | Round-to-round global and local registration |
| `HCR_cellpose`, `2p_cellpose` | Cellpose model and parameters for each side |
| `twop_to_hcr_registration` | Cross-modal cascade: tile sizes, search ranges, thresholds |
| `intensity_extraction` | Background settings for probe intensity measurement |
| `rotation_2p_to_HCR` | `fliplr` / `flipud` to un-mirror the functional image, plus an optional coarse `rotation`. The flip is the part that has to be right; see [step 1](#what-it-does) |

Every section has working defaults in the templates.
[`param_example.hjson`](examples/param_example.hjson) goes deeper on the registration and
matching knobs: what each does, and when it is worth changing.

### Functional input, and where cells come from

Two independent choices on the session. `input_format` says where the *image* comes from,
`masks` says where the *cells* come from, and they do not have to agree.

| Key | Value | Effect |
|---|---|---|
| `input_format` | `"tiff"` | **Use this.** Reads `2P/plane_{N}.tiff`, any microscope, any preprocessing. The only path the templates and demo use |
| | `"suite2p"` / `"sbx"` | Legacy readers for the rig this was built on: the mean image out of an existing Suite2p `ops.npy`, or ScanBox. Both work, neither is supported |
| `masks` | *omitted* | Cellpose segments the mean image |
| | `"suite2p"` | Reuse existing Suite2p ROIs, no segmentation at all. See [Bringing your own masks](#bringing-your-own-masks) |

`input_format` is required whenever there is a `two_photon_imaging` section, with no default and
no override. `tiff` + `suite2p` is a normal pairing; both must describe the same pixel grid, so
export the TIFF from the same `ops['meanImg']` the ROIs were drawn on, uncropped.

### Hi-res structural images

Supply an already-stitched image as `2P/plane_{N}_hires.tiff`. The low-res mean image is placed
into it, and the alignment to the FISH volume is computed at the higher resolution.

> `easipass/tiling.py` and `easipass/auto_stitching.py` do assemble tiles by phase correlation,
> but they assume our ScanBox tile geometry and naming, so this is not a general feature.
> Generalizing it needs an agreed tile-input format (per-tile files plus a nominal grid
> position), which is an open contribution we would welcome.

## What the pipeline writes

Everything lands under `{base_path}/{sample_name}/OUTPUT/`:

```
OUTPUT/
├── HCR/
│   ├── cellpose/                 3D FISH masks
│   ├── cellpose_aligned/         those masks warped into the reference frame
│   └── extract_intensities/      per-cell fluorescence per channel
├── 2P/
│   ├── cellpose/                 2D functional masks
│   └── registered/               landmarks, transforms, QC overlays
└── MERGED/
    ├── aligned_masks/            per-cell match tables
    └── aligned_extracted_features/   final tables, matches joined to genes
```

Tables are written as both `.csv` and `.pkl`. Start with
`MERGED/aligned_extracted_features/` for the result, and `2P/registered/QualityCheck/` for the
overlays that show whether alignment worked.

## Re-running

A step is skipped when its output exists, so an interrupted run resumes where it stopped. Delete
a step's output to redo it, or all of `OUTPUT/` for a clean run. Three steps differ:

| Step | Behaviour |
|---|---|
| Low-res to hi-res placement, and the cross-modal cascade | **Ask**, do not skip. You get `Overwrite? [y/n]` naming the file, and your answer is reused for every remaining plane. Answer `n` to keep what is there |
| Segmentation | Looks for your own masks before its own output, so deleting `_seg.npy` alone finds the `_masks.tiff` beside it and reuses that. Delete both to segment again |
| Merged feature tables | Rebuild when any intensity file is newer than the table, so they refresh on their own |

Re-orienting the functional image is the one thing the manifest alone cannot redo, since the
flip is applied once, on the first run. Delete
`OUTPUT/2P/registered/lowres_meanImg_C0_plane{N}_rotated.tiff` to be asked again, and delete the
landmarks with it, since they were placed on the old orientation.

## Source layout

| File | Purpose |
|---|---|
| `master_pipeline.py` | The command line, and the order every step runs in |
| `easipass/meta.py` | Manifest parsing and validation |
| `easipass/importers.py` | Picks the reader for your `input_format` |
| `easipass/functional.py` | Reads the functional side, applies the flip and rotation |
| `easipass/segmentation.py` | Cellpose segmentation, mask matching, merged tables |
| `easipass/registrations.py` | Runs the registration steps in order |
| `easipass/registrations_utils.py` | Cross-modal registration algorithms |
| `easipass/hcr_centroid_registration.py` | Centroid-seeded round-to-round registration |
| `easipass/somaprint.py`, `somaprint_hcr.py` | Soma-print matchers, cross-modal and round-to-round |

The rest of `easipass/` is supporting code: tile stitching, automation checkpoints, BigStream
wrappers, and analysis helpers.

## Citation

If you use EASI-PASS, please cite the accompanying paper. Details will be added here on
publication; see [CITATION.cff](CITATION.cff).

## License

BSD 3-Clause. See [LICENSE](LICENSE).
