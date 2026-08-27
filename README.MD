# EASI-PASS

Align two-photon functional imaging to multi-round in-situ molecular imaging. 

EASI-PASS takes a mean image from a functional recording and one or more EASI-FISH confocal
volumes, segments cells in both, registers them onto each other, matches cells across
modalities, and writes a per-cell table joining functional identity to molecular readout. It
also runs without any functional data, registering and matching cells across successive FISH
rounds alone.

It does not process raw recordings, compute ΔF/F, or stitch image tiles. Those happen
upstream, and EASI-PASS takes their output as input.

**Getting started:** [What it needs](#what-it-needs) · [Ways to run this](#ways-to-run-this) · [Installation](#installation) · [Start with the demo](#start-with-the-demo) · [Running your own data](#running-your-own-data)

**Using it:** [Bringing your own masks](#bringing-your-own-masks) · [What it does](#what-it-does) · [What you get](#what-you-get) · [The feature table](#the-feature-table) · [Manifest](#manifest)

**Reference:** [What the pipeline writes](#what-the-pipeline-writes) · [Re-running](#re-running) · [Source layout](#source-layout) · [Citation](#citation)

## What it needs

| Input | Format |
|---|---|
| Functional field of view | One 2D mean image per plane, TIFF |
| FISH rounds | One multi-channel 3D volume per round, TIFF |
| Hi-res structural image *(optional)* | One stitched 2D TIFF per plane. Improves the alignment when the mean image is too coarse to landmark directly |
| A few landmarks | Placed once in [BigWarp](https://imagej.net/plugins/bigwarp), between one functional plane and the reference FISH volume. Not needed for FISH-only runs, and the demo ships its own |

Everything else is set in a manifest.

The run pauses for you a few times: to settle the image orientation, place landmarks, check the
segmentation, and accept the alignment it found. Everything in between is automatic.

## Ways to run this

Find the line that describes what you have. There are no mode flags to learn: the pipeline
works out what to do from what your manifest contains.

**Functional + FISH.** A 2D mean image per functional plane, one multi-channel 3D volume per
FISH round. You place landmarks once in BigWarp, and get back a per-cell table joining the two.
This is the demo and the main case. Template: [`demo_tiff.hjson`](examples/demo_tiff.hjson).

**Functional + FISH, with a hi-res bridge.** The same, plus an already-stitched structural
image per plane. The functional mean image is often too coarse to landmark against a FISH
volume directly; the hi-res image bridges the two. Drop it next to the mean image as
`plane_{N}_hires.tiff`. No manifest change; its presence is the switch.

**FISH only.** One or more FISH rounds and no functional data, registered and matched to each
other. No landmarks, no functional segmentation. Omit the `two_photon_imaging` section
entirely, or pass `--only_hcr` to skip the functional half of a manifest that has one.
Template: [`demo_hcr_only.hjson`](examples/demo_hcr_only.hjson).

**A single FISH round.** Nothing to register it against, so round-to-round registration is
skipped on its own. Leave one entry in `rounds`; nothing else changes.

**Masks already segmented.** You have masks for one or both sides: your own Cellpose run,
hand-corrected masks, Suite2p ROIs, another tool entirely. Put them where the stage would have
written them and that stage skips. See [Bringing your own masks](#bringing-your-own-masks).

**Check the alignment before committing to the rest.** Cross-modal alignment is the step most
likely to need a second attempt, and the later rounds need not even be imaged yet.
`--check_alignment` stops after matching to the reference round; re-run without it to finish,
and everything the check produced is reused.

These combine. A FISH-only run can bring its own masks; a hi-res run can check alignment first.

## Installation

Two routes that produce the identical environment. Use whichever tool you already have.

**With conda:**

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass
conda env create -f environment.yml && conda activate easipass
pip install -e . -c requirements.txt
```

**With [uv](https://docs.astral.sh/uv/)**, a Python installer that downloads its own copy of
Python, so nothing has to be set up first:

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e . -c requirements.txt
```

Either takes about four minutes. In every new shell, activate the environment again:
`conda activate easipass`, or `source .venv/bin/activate` (on Windows,
`.venv\Scripts\activate`).

Why two routes, and why not plain `pip`: the pipeline needs Python 3.12, most machines ship
something older, and installing into an older one fails with errors that name the wrong thing.
conda and uv each supply 3.12 themselves. Plain `pip` uses whatever is already there.

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

`requirements.txt` lists the exact versions the pipeline was tested with, and `-c` holds the
install to them, so you get that environment and not whatever released this week. Keep `-c` on
any later install into the same environment:

```bash
pip install -e ".[notebooks,analysis]" -c requirements.txt      # notebooks and analysis
```

These commands work the same on Linux, macOS and Windows, and give the same versions on each.
The pipeline is developed and tested on Linux, so that is where it is known to run end to end.
The CUDA libraries are Linux-only, so a GPU only helps there.

Cross-modal runs also need [Fiji](https://fiji.sc/)'s BigWarp for placing landmarks
(Plugins > BigDataViewer > Big Warp). See [docs/landmarks.md](docs/landmarks.md).

### Do you need a GPU?

No. Only Cellpose uses one; registration, matching and intensity extraction are CPU-only. The
install is the same either way, and EASI-PASS names the device it got at the start of
segmentation, so an unintended CPU fallback is visible and not silent.

A full FISH volume (2500 x 2500 x 100 px) segments in a few minutes on a GPU and an hour or
two without one. The demo 2P is a single plane and fine either way. To confirm a GPU before a
long run:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Both halves matter. The version should end `+cu124`; a bare `2.5.1` is a CPU-only build.
`True` means torch can actually drive the card. **Any NVIDIA GPU works, within two bounds
this pins:** the driver must be **525 or newer**, and cards past Hopper (the RTX 50 series and
later) are outside what CUDA 12.4 covers. Either one gives `False` on a machine that plainly
has a GPU, so the pipeline says which card it found and why it could not use it, and carries
on using the CPU.

`gpu` in each cellpose block defaults to true, meaning use an accelerator if one exists. Set
`gpu: false` to force the CPU. If you already have masks you can skip segmentation entirely,
see [Bringing your own masks](#bringing-your-own-masks).

RAM matters more than the GPU, and scales with volume size: budget roughly 25 GB while a
2048 x 2048 x 100 round is registered.

## Start with the demo

[`demo/`](demo/README.md) is one two-photon plane from mouse JS078 aligned to a 5-channel
FISH volume, with a reference result to check yourself against. It is the quickest way to
confirm your install works and see what goes in and what comes out.

```bash
python demo/fetch_demo_data.py
python master_pipeline.py --manifest demo/JS078_demo.hjson
```

Three warnings appear on every run and none of them mean anything is wrong: `pynwb not
installed` from Suite2p, `FutureWarning: You are using torch.load with weights_only=False`
from Cellpose loading its own model, and a `SyntaxWarning` from inside SimpleITK.

### Looking at what came out

A finished run leaves you with a table and no obvious place to start.
[`demo/explore_results.ipynb`](demo/explore_results.ipynb) opens it, shows how it is put
together, and plots what is worth checking first. Run it after the demo to confirm your output
looks like it should, then point it at your own runs.

```bash
jupyter lab demo/explore_results.ipynb
```

It walks through seven short steps:

| | |
|---|---|
| The main table | What each row and column is |
| The two matchers | How many cells each found, and how often they agree |
| Adding positions | Joining centroids on, since the main table has none |
| Did it work | Every functional cell coloured by whether it matched, and where the plane landed |
| Every probe | One small map per probe, each on its own scale |
| A few matches up close | Three matched pairs as overlaid masks, green functional and magenta EASI-FISH |

The masks-up-close step is the one that tells you a match is real rather than merely counted.
Everything else reads only the small tables and takes seconds; that step reads a full mask
volume, so give it about ten seconds.

The same plots without Jupyter, saved as one figure next to your results:

```bash
python demo/explore_results.py                       # the demo run
python demo/explore_results.py --output PATH/OUTPUT   # your own run
```

Both work on any finished `OUTPUT` folder, not just the demo.

The first command pulls 191 MB from this repo's
[releases page](https://github.com/orena1/easi-pass/releases) and checks its sha256; allow
about 1.3 GB of disk for the images and what the run writes. Nothing to edit. The run pauses
three times to let you check intermediate output, and `demo/README.md` gives the answers.

## Running your own data

**1. Copy a template.**

| Template | For |
|---|---|
| [`demo_tiff.hjson`](examples/demo_tiff.hjson) | **Start here.** You supply a 2P mean image per plane as `plane_{N}.tiff` |
| [`demo_hcr_only.hjson`](examples/demo_hcr_only.hjson) | FISH rounds alone, no functional data |

A hi-res image and the single-round case both work with no manifest change; see the notes at
the top of `demo_tiff.hjson`. Either template runs as it stands once the paths are yours.
[`param_example.hjson`](examples/param_example.hjson) annotates the registration and matching
parameters in more depth than the templates do; it has no `data` section, so read it alongside
a template, not as a starting point.

**2. Put your files where the manifest expects them.**

`base_path` is the folder that contains your samples, not the sample itself, so several
manifests can share one `base_path` and differ only by `sample_name`. For data at
`/data/experiments/M12/`:

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
`functional_planes`, and `{R}` in `HCR{R}.tiff` matches a `round` value. `.tif` and `.tiff`
both work, case is ignored, and a `{sample_name}_` prefix is accepted. `mouse_name` works as
a synonym for `sample_name`.

**3. Run.**

```bash
python master_pipeline.py --manifest examples/your_manifest.hjson
```

A manifest with no `two_photon_imaging` section runs FISH rounds only, with nothing extra to
pass. Use `--only_hcr` to skip the functional half of a manifest that has one.

Cross-modal alignment is the step most likely to need another attempt, since it depends on
your landmarks, the functional segmentation, and whether the recovered tissue actually
contains the imaged field. `--check_alignment` settles that first:

```bash
python master_pipeline.py --manifest examples/your_manifest.hjson --check_alignment
```

That segments the reference round only, registers and matches the functional planes to it,
writes the per-cell match tables and QA overlays, and stops, so the later rounds need not even
be imaged yet. Review the overlays in `OUTPUT/2P/registered/QualityCheck/`, then re-run without
the flag to finish. Everything the check produced is reused.

### Bringing your own masks

If you have already segmented one side, hand those masks in and EASI-PASS skips Cellpose and
goes straight to registering and matching them.

**Suite2p ROIs, on the functional side.** Set `masks: "suite2p"` on the session. The pipeline
reads `stat.npy`, `iscell.npy` and `ops.npy` from `2P/suite2p/plane{N}/` and paints every
`iscell` ROI into a label image, giving a shared pixel to whichever ROI weights it higher.

Your mask label is the **Suite2p ROI index + 1**, so you rejoin your own `F.npy` by
`label - 1`. EASI-PASS never reads your traces. This assumes the ROIs sit on the
`ops['meanImg']` grid, which is true of a plain Suite2p run.

**Anything else: save a label image where the pipeline would have written one.** Each
segmentation step looks for your masks first, and skips itself if it finds them.

| Masks you have | Put them here |
|---|---|
| Functional plane `N` | `OUTPUT/2P/cellpose/lowres_meanImg_C0_plane{N}_masks.tiff` |
| FISH round `R` | `OUTPUT/HCR/cellpose/HCR{R}_masks.tiff` |

A label image is one integer per pixel: `0` for background, `1, 2, 3…` for cells, the way
Cellpose numbers them. Any integer type works. `.npy` is accepted in place of `.tiff` under
the same name, as is Cellpose's own `_seg.npy` if you hand-corrected in its GUI.

Two rules, both checked before anything runs:

- Masks must be the **same shape as the image they describe**: the functional mean image, or
  the FISH volume as acquired, indexed `(Z, Y, X)`. Uncropped, unresampled.
- At most **65,535 cells** per image.

Give functional masks in the same orientation as the mean image you supplied. The pipeline
applies your `rotation_2p_to_HCR` to both together.

The run prints which file it used, or says it found none and is segmenting, so you always know
which happened. To segment again, delete the mask file and the `_seg.npy` next to it.

**Multi-round runs, if your rounds are already registered to each other.** FISH masks normally
go in `cellpose/` as acquired, and the pipeline warps them into the reference round's frame
for you. If you have already done that warping yourself, put the warped masks in
`OUTPUT/HCR/cellpose_aligned/` instead and that step is skipped. Round-to-round registration
still runs either way, since later stages read its output. Single-round runs never need this.

One naming wrinkle to know about: in `cellpose/` and `cellpose_aligned/`, non-reference rounds
are named `HCR{R}_to_HCR{ref}_masks.tiff`, so round 02 against reference 01 is
`HCR02_to_HCR01_masks.tiff`. The reference round is plain `HCR01_masks.tiff`.

## What it does

**Before any segmentation**

| Step | |
|---|---|
| **1. Orient the functional image** | Settle any mirror flip between the functional image and the FISH volume. On a first run the pipeline prints both file paths and waits: open them, and if one is mirrored, add `fliplr` or `flipud` to `rotation_2p_to_HCR` in your manifest before continuing. ScanBox input is stitched at this step too. |
| **2. Place landmarks** | A handful of points in BigWarp, functional plane against the reference FISH volume. This comes before Cellpose on purpose, so a bad alignment surfaces in minutes, not after an hour of segmentation. |

**Segmentation**

| Step | |
|---|---|
| **3. Functional** | Cellpose on each mean image |
| **4. Molecular** | Cellpose per FISH plane, linked across planes into 3D cells |

**Molecular side**, once, covering all rounds

| Step | |
|---|---|
| **5. Round-to-round registration** | Each round onto the reference round. Cell centroids initialize a global affine (RANSAC), then a block-wise deformable refinement (BigStream). Labels are warped into the reference frame. |
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

FISH-only runs skip steps 1, 2, 3, 7 and 8. At step 9 they match rounds to each other instead
of to a functional plane.

**A flip is not the same as a rotation.** Only the flip has to be right at step 1, because
BigWarp cannot mirror an image, and nothing downstream can recover from getting it wrong. Rotation is
absorbed by the landmarks you place at step 2, so you do not need to set it. If your manifest
already carries `rotation_2p_to_HCR` the pipeline applies it and does not ask.

Round-to-round registration uses cell centroids from the segmentation, not detected
fluorescent spots. So if rounds register poorly, check the reference round's Cellpose
segmentation first: every centroid comes from it.

**Step 5 tries several alignments and shows you all of them.** It does not pick one setting and
hope. It runs the whole global alignment once per entry in `context_radius_um` (by default 40,
60 and 80 µm), scores each, and writes every candidate's transform and QC image to disk before
you choose. The scores disagree often enough that the pipeline marks a suggestion and leaves
the decision to you, so look at the images and not the numbers alone.

If it still registers poorly, the knobs in `HCR_to_HCR_registration` are: lower
`match_threshold` (0.3 to 0.2) to accept weaker correspondences, lower `count_floor` /
`match_floor` to let sparse regions contribute, and raise `max_spot_match_distance_um` if the
tissue shifted a long way between rounds. That last one is the one to suspect when a region
comes out untouched: set below the real shift, it rejects every candidate in a block and the
block silently falls back to no correction.

## What you get

The main product is a per-cell matching table at
`OUTPUT/MERGED/aligned_masks/twop_plane{N}_to_HCR01.csv`. Each row is a candidate
functional/FISH cell pair, and `is_best_match` marks the accepted 1:1 call.

| Column | Meaning |
|---|---|
| `mask1`, `mask2` | Functional cell id, FISH cell id |
| `iou`, `iou_at_mask1_z` | Mask overlap, in 3D and in the functional plane |
| `containment_2p`, `containment_hcr_at_z` | Directional overlap, each way |
| `mask1_size`, `mask2_size`, `mask2_size_at_mask1_z` | Mask sizes, in voxels |
| `is_best_match` | The accepted overlap-based 1:1 match |
| `somaprint_hcr_label` | Soma-print's call for this cell, independent of overlap |
| `somaprint_best_score`, `somaprint_second_score` | Its best and runner-up scores |
| `somaprint_confident` | Whether best separates significantly from runner-up |

Both matchers are reported for every cell and never reconciled, so you set your own
thresholds.

### The feature table

`OUTPUT/MERGED/aligned_extracted_features/full_table_{feature}_twop_plane{N}.csv` (and `.pkl`)
joins those matches to per-gene intensities. One row per FISH cell in the reference round, one
file per feature, single header row.

Every row answers the same three questions about one FISH cell: what are its genes, which
functional cell is it, and which cell is it in each later round.

| Column | Example | Meaning |
|---|---|---|
| **Which cell this row is about** | | |
| `mask_id_main` | `1` | The FISH cell, in the reference round |
| `plane` | `0` | The functional plane this file covers |
| **Its genes** | | |
| `{feature}_round_{R}_{gene}` | `mean_round_01_SST` → `0.0` | One column per channel per round |
| **Which functional cell it is.** Two independent matchers, which can disagree | | |
| `twoP_iou_match` | `412` | The cell matched by mask overlap |
| `twoP_iou` | `0.51` | How good that overlap was |
| `twoP_somaprint_match` | `412` | The cell soma-print picked |
| `twoP_somaprint_confident` | `True` | Whether that pick cleared its gate. Always `True`/`False`, never blank |
| **Which cell it is in each later round `R`.** Absent for single-round runs | | |
| `round_{R}_iou_match` | `310` | The cell by overlap alone |
| `round_{R}_iou` | `0.44` | That overlap |
| `round_{R}_hybrid_match` | `310` | The cell by the full matcher. **The gene columns are joined on this one** |
| `round_{R}_hybrid_matched_by` | `overlap` | How it got there: `overlap` when overlap alone was trusted, `somaprint` when soma-print recovered it |
| `round_{R}_somaprint_score`, `_second_score` | | Scores behind a soma-print recovery, blank for an overlap match |

Three things that trip people up:

- **A blank means no match, not zero.** Gene columns for the reference round are never blank,
  since measuring a cell does not depend on matching it.
- **A soma-print pick is not always a confident pick.** In the demo 1,387 cells get a pick and
  1,149 of those clear the gate, so `twoP_somaprint_match.notna()` and
  `twoP_somaprint_confident` ask different questions.
- **`hybrid_match` is whose genes are on the row**; `iou_match` is what overlap alone would
  have said. They usually agree.

The gene columns are joined on `round_{R}_hybrid_match`, so that column says whose intensities
are on the row, and `round_{R}_iou_match` is what overlap alone would have said:

```python
matched   = df.round_02_hybrid_match.notna()
by_iou    = df.round_02_iou_match.notna()
recovered = df.round_02_hybrid_matched_by == 'somaprint'
```

No sizes, containments or intersections are repeated in this table. They are all columns of
the matching table above, which is the full per-pair record, and 3D cell sizes come from the
published mask TIFFs with one `np.unique`.

In the demo, 1,199 of the 1,439 segmented functional cells get a 1:1 overlap match (83%),
with a median overlap of 0.29 in the functional plane. Soma-print confidently calls 1,149.
The two rates differ because the matchers are independent. A tracked copy of the table is in
[`demo/completed/`](demo/completed/README.md) to diff your run against.

## Manifest

An [HJSON](https://hjson.github.io/) file (JSON with comments and relaxed syntax) with two
sections: `data` for what you are processing, `params` for how.

**`data`**

| Field | Description |
|---|---|
| `base_path` | Folder containing your samples |
| `sample_name` | Folder name for this sample. Outputs are written under it. `mouse_name` is a synonym |
| `HCR_confocal_imaging.rounds` | One entry per round: id, channel names, voxel resolution |
| `HCR_confocal_imaging.reference_round` | The round all others register to. Pick the one with the best signal |
| `two_photon_imaging.sessions` | Functional session config. Omit for FISH-only runs |

Per round: `round` (e.g. `"01"`), `channels` (the nuclear stain used for registration comes
first), `resolution` (voxel size `[x, y, z]` in microns, from your confocal metadata).

Per session: `functional_planes` (the first is the reference plane for landmark alignment),
`input_format`, and optionally `masks` to reuse Suite2p ROIs in place of segmenting
(see [Bringing your own masks](#bringing-your-own-masks)).

**`params`**

| Section | Description |
|---|---|
| `HCR_to_HCR_registration` | Round-to-round global and local registration |
| `HCR_cellpose`, `2p_cellpose` | Cellpose model and parameters for each side |
| `twop_to_hcr_registration` | Cross-modal cascade: tile sizes, search ranges, thresholds |
| `intensity_extraction` | Background settings for probe intensity measurement |
| `rotation_2p_to_HCR` | `fliplr` / `flipud` to un-mirror the functional image, plus an optional coarse `rotation`. The flip is the part that has to be right; see [step 1](#what-it-does) |

Every `params` section has working defaults in the templates.
[`param_example.hjson`](examples/param_example.hjson) goes deeper on the registration and
matching knobs: what each one does, and when it is worth changing.

### Functional input formats

Use `input_format: "tiff"`. It reads `2P/plane_{N}.tiff` mean images, works with any
microscope and any preprocessing, and is the only path the templates and the demo use.

`input_format` is required whenever there is a `two_photon_imaging` section. There is no
default, an unrecognised value is an error, and no command-line switch overrides it.

Two other readers exist for the acquisition setup this was built on, `suite2p` (pulls the mean
image from an existing Suite2p `ops.npy`) and `sbx` (ScanBox). Both still work, but neither is
the supported route: whatever produced your recording, export a mean image per plane as TIFF
and the rest of the pipeline is identical.

`input_format` and `masks` are separate choices and do not have to agree. `input_format` says
where the image comes from; `masks` says where the cells come from. `input_format: "tiff"`
with `masks: "suite2p"` is a normal combination: your own TIFF mean image, your own Suite2p
ROIs, and no segmentation run at all. The one thing to get right is that the two describe the
same pixel grid: export the TIFF from the same Suite2p `ops['meanImg']` the ROIs were drawn
on, uncropped and unresampled.

### Hi-res structural images

If you acquired a higher-resolution structural image of the same field, supply it as
`2P/plane_{N}_hires.tiff`. The low-res mean image is placed into it and the alignment to the
FISH volume is computed at the higher resolution. The image must already be stitched.

> `easipass/tiling.py` and `easipass/auto_stitching.py` do assemble tiles by phase
> correlation with a median-shift consensus layout, but they assume our ScanBox tile geometry
> and naming, so this is not a supported general feature. Supply an already-stitched image.
> Generalizing it mainly needs an agreed tile-input format (per-tile files plus a nominal
> grid position), which is an open contribution we would welcome.

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
`MERGED/aligned_extracted_features/` for the result and
`2P/registered/QualityCheck/` for the overlays that show whether alignment worked.

## Re-running

The pipeline skips a step when its output already exists, so an interrupted run resumes where
it stopped. Delete a step's output to redo just that step, or the whole `OUTPUT/` folder for a
clean run.

Three steps behave differently, and it is worth knowing which:

| Step | Behaviour |
|---|---|
| Low-res to hi-res placement, and the cross-modal cascade | **Ask**, do not skip. You get `Overwrite? [y/n]` naming the file, and your answer is reused for every remaining plane. Answer `n` to keep what is there |
| Segmentation | Looks for your own masks before its own output, so deleting `_seg.npy` alone finds the `_masks.tiff` beside it and reuses that. Delete both to segment again |
| Merged feature tables | Rebuild when any intensity file is newer than the table, so they refresh on their own |

Re-orienting the functional image is the one thing you cannot redo from the manifest alone:
the flip is applied once, on the first run. Delete
`OUTPUT/2P/registered/lowres_meanImg_C0_plane{N}_rotated.tiff` to be asked again, and delete
the landmarks with it, since they were placed on the old orientation.

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
