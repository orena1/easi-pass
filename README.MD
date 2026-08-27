# EASI-PASS

Align two-photon functional imaging to multi-round in-situ molecular imaging, cell by cell.

EASI-PASS takes a mean image from a functional recording and one or more EASI-FISH confocal
volumes, segments cells in both, registers them onto each other, matches cells across
modalities, and writes a per-cell table joining functional identity to molecular readout. It
also runs without any functional data, registering and matching cells across successive FISH
rounds alone.

It does not process raw recordings, compute ΔF/F, or stitch image tiles. Those happen
upstream, and EASI-PASS takes their output as input.

## What it needs

| Input | Format |
|---|---|
| Functional field of view | One 2D mean image per plane, TIFF |
| Molecular rounds | One multi-channel 3D volume per FISH round, TIFF |
| Hi-res structural image *(optional)* | One stitched 2D TIFF per plane, used as an alignment bridge |
| A few landmarks | Placed once in [BigWarp](https://imagej.net/plugins/bigwarp), between one functional plane and the reference FISH volume. Not needed for FISH-only runs, and the demo ships its own |

Everything else is set in a manifest.

## Installation

Needs Linux. A GPU is optional — see below. Segmentation uses Cellpose 4 (cellpose-SAM).

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass

uv venv --python 3.12
source .venv/bin/activate

uv pip install -r requirements.txt
uv pip install -e . --no-deps
```

About four minutes, and uv fetches its own Python, so nothing else has to be installed
first. One file, whether or not you have a GPU. `requirements.txt` pins every version
exactly, so nothing is resolved on your machine and you get the environment the pipeline was
validated in rather than whatever released this week.

For the notebooks, add the extras on top:

```bash
uv pip install -e ".[notebooks,analysis]" -c requirements.txt
```

Keep the `-c`. Without it, Jupyter's own dependencies pull newer numpy and pandas than the
pinned ones and quietly undo the versions above.

Clone to local disk, not a network share — the editable install writes alongside the package
and fails on some mounts.

<details>
<summary>If you have to use conda</summary>

conda works, but it is slower for reasons that have nothing to do with this project: it
downloads and indexes the whole of conda-forge's package metadata, several hundred megabytes,
before installing anything, and it does that however little you ask it for. On the classic
solver that step alone can take longer than the entire uv install. Use
[miniforge](https://github.com/conda-forge/miniforge) and check `conda config --show solver`
reports `libmamba`.

`environment.yml` supplies Python and nothing else; `requirements.txt` does the rest.

```bash
conda env create -f environment.yml
conda activate easipass
pip install -r requirements.txt
pip install -e . --no-deps
```
</details>

Cross-modal runs also need [Fiji](https://fiji.sc/)'s BigWarp for placing landmarks
(Plugins > BigDataViewer > Big Warp). See [docs/landmarks.md](docs/landmarks.md).

### Do you need a GPU?

No. Only Cellpose segmentation can use one. Registration, matching, intensity extraction and
the merged tables are CPU-only, so a GPU changes how long you wait for masks and nothing else
— same code, same numbers.

Without one, install exactly as above and run exactly as documented — there is no separate
CPU install. Cellpose falls back to the CPU on its own, and EASI-PASS prints one line at the
start of segmentation naming the device it got, so a fallback you did not intend is visible
rather than silent. The only cost of the single install is disk: the Linux PyTorch wheels
bundle CUDA whether or not you can use it, about 3 GB that then sits idle. As an order of
magnitude for time: a full FISH volume that segments in tens of minutes on a GPU takes several
hours on a CPU. The demo is one plane and one volume, and is comfortable either way.

If you meant to use a GPU, confirm it is actually there before a long run:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

It should print `True`. A machine that reports `False` keeps working, just far slower — which
is easy to mistake for the pipeline being slow.

`gpu` in each cellpose block is optional and defaults to true, meaning *use an accelerator if
there is one*. Set `gpu: false` to pin it to the CPU.

If you already have masks, you can skip segmentation altogether — see
[Bringing your own masks](#bringing-your-own-masks).

RAM is the tighter constraint, and it scales with FISH volume size rather than with the GPU.
Budget roughly 25 GB while a 2048 × 2048 × 100 round is being registered; a 64 GB machine is
comfortable at that size.

## Start with the demo

[`demo/`](demo/README.md) is one two-photon plane from mouse JS078 aligned to a 5-channel
FISH volume, with a reference result to check yourself against. It is the quickest way to
confirm your install works and see what goes in and what comes out.

```bash
python demo/fetch_demo_data.py
python master_pipeline.py --manifest demo/JS078_demo.hjson
```

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
a template rather than starting from it.

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

Segmentation is a stage, not a prerequisite. If you have already segmented one side — your own
Cellpose run, hand-corrected masks, Suite2p ROIs, another tool entirely — hand those in and
EASI-PASS registers and matches them instead of segmenting again.

**Suite2p ROIs, on the functional side.** Set `masks: "suite2p"` on the session, and the
pipeline reads `2P/suite2p/plane{N}/` (`stat.npy`, `iscell.npy`, `ops.npy`) from your sample
folder and rasterizes every `iscell` ROI into the label image Cellpose would have produced.
Overlapping pixels go to the ROI with the higher `lam`, so each pixel has one owner. **Mask
label = Suite2p ROI index + 1**, which is how you join your own `F.npy` back on: `label - 1`.
Traces are yours to keep; EASI-PASS never reads them. This assumes the ROIs are in the
`ops['meanImg']` pixel grid, which is true of a plain Suite2p run.

**Anything else, by writing the file the stage would have written.** The pipeline skips a step
whose output already exists, so a mask file in the right place is simply used.

| Masks you have | Write them to | As |
|---|---|---|
| Functional plane `N` | `OUTPUT/2P/cellpose/lowres_meanImg_C0_plane{N}_seg.npy` | `np.save` of a dict with a `masks` key: a 2D label image on the mean image's pixel grid. (Cellpose also stores `img` for its GUI; the pipeline reads only `masks`) |
| FISH round `R`, as acquired | `OUTPUT/HCR/cellpose/HCR{R}_masks.tiff` for the reference round, `HCR{R}_to_HCR{ref}_masks.tiff` for every other | 3D `uint16` label volume, matching the round's DAPI channel in `(Z, Y, X)` |
| FISH round `R`, already warped into the reference frame | `OUTPUT/HCR/cellpose_aligned/` under the same names | as above, on the reference round's grid |

The two FISH rows are separate skips, and each stands alone. Masks in `cellpose/` skip
segmentation for that round; masks in `cellpose_aligned/` skip warping its labels into the
reference frame, which is the one to use when your rounds are already registered to each
other. Round-to-round registration is computed before that warp and still runs either way. For
a single-round run there is nothing to warp — the reference round's masks are copied straight
across — so `cellpose/` alone is enough.

Label 0 is background, and the ceiling is 65,535 cells per volume — the pipeline raises rather
than let `uint16` labels wrap. Number cells consecutively from 1, as Cellpose does. Write the
file before the run reaches that stage, and delete it to segment again.

## What it does

```
Before any segmentation
  1. Per-plane prep              Rotate the functional mean image (and, for ScanBox input,
                                 stitch it)
  2. Landmarks                   BigWarp, functional plane against the acquired reference
                                 EASI-FISH volume. These come first so a bad alignment shows
                                 up before you spend an hour on Cellpose.

Segmentation
  3. Functional                  Cellpose on each mean image
  4. Molecular                   Cellpose per FISH plane, linked across planes into 3D cells

Molecular side (once, for all rounds)
  5. Round-to-round registration Each round -> reference round. Cell centroids initialize a
                                 global affine (RANSAC), then block-wise deformable
                                 refinement (BigStream). Labels are warped into the
                                 reference frame.
  6. Probe intensity extraction  Per-cell fluorescence per channel, with local background

Cross-modal (per plane)
  7. Low-res -> hi-res placement Only if a hi-res structural image is supplied
  8. Registration                Landmarks -> thin-plate spline surface through the FISH
                                 volume -> rigid search -> global affine ->
                                 coarse-to-fine local tile cascade
  9. Matching                    Mask overlap (IoU) and Soma-print, reported per cell

Output
 10. Merged table                One row per cell: matched identities, per-gene intensities
                                 across rounds, match-quality scores
```

FISH-only runs skip 1, 2, 3 and 7, and match rounds to each other at 9.

Round-to-round registration uses cell centroids from the segmentation, not detected
fluorescent spots. If rounds register poorly, check the reference round's Cellpose
segmentation first, since every centroid comes from it. Then tune
`HCR_to_HCR_registration.global` and `.local`: lower `match_threshold` (0.3 to 0.2) to accept
weaker correspondences, lower `count_floor` / `match_floor` to let sparse blocks contribute,
and widen `context_radius_um` for tissue with less distinctive local geometry.

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

**One row, laid out.** Every row answers the same questions about one FISH cell: what are its
genes, which functional cell is it, and which cell is it in each later round.

```
mask_id_main                 1     this row is FISH cell 1
plane                        0

mean_round_01_DAPI         6.8     its genes in the reference round,
mean_round_01_SST          0.0     one column per channel

twoP_iou_match             412     which functional cell it is, by mask overlap
twoP_iou                  0.51     how good that overlap was

twoP_somaprint_match       412     and by Soma-print, which can pick a different cell
twoP_somaprint_confident  True     whether that pick cleared its gate

round_02_iou_match           310   which cell it is in round 02, by overlap alone
round_02_hybrid_match        310   and by the full matcher, which the genes follow
round_02_hybrid_matched_by overlap how the full matcher got there

mean_round_02_TAC1         2.1     its genes in round 02
```

A blank means no match was found, not zero. Gene columns are always filled for the reference
round, since measuring a cell does not depend on matching it. Round `02` columns only exist
when you have more than one round.

| Column | Meaning |
|---|---|
| `mask_id_main` | The FISH cell this row is about |
| `{feature}_round_{R}_{gene}` | Intensity of that gene in that round, e.g. `mean_round_01_PDYN` |
| `plane` | Which functional plane this file covers |

Which functional cell it is. Both columns hold a functional cell id, from two independent
matchers that can disagree:

| Column | Meaning |
|---|---|
| `twoP_iou_match` | The cell matched by mask overlap, blank if none |
| `twoP_iou` | Overlap of that pair, in the functional plane |
| `twoP_somaprint_match` | The cell Soma-print picked, confident or not |
| `twoP_somaprint_confident` | Whether that pick cleared its gate. `False`, never blank |

A Soma-print pick is not always a confident one: in the demo, 1,387 cells get a pick and 1,149
of those are confident. So `twoP_somaprint_match.notna()` and `twoP_somaprint_confident` are
different questions.

Cell in each further FISH round `R`, one set per round. Absent for single-round runs:

| Column | Meaning |
|---|---|
| `round_{R}_iou_match`, `round_{R}_iou` | Cell in round R by overlap alone, and that overlap |
| `round_{R}_hybrid_match` | Cell in round R by the full matcher |
| `round_{R}_hybrid_matched_by` | `overlap` if overlap alone was trusted (an anchor), `somaprint` if Soma-print recovered it |
| `round_{R}_somaprint_score`, `_second_score` | Scores behind a Soma-print recovery, blank for an anchor |

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
`input_format`, and optionally `masks` to reuse Suite2p ROIs instead of segmenting
(see [Bringing your own masks](#bringing-your-own-masks)).

**`params`**

| Section | Description |
|---|---|
| `HCR_to_HCR_registration` | Round-to-round global and local registration |
| `HCR_cellpose`, `2p_cellpose` | Cellpose model and parameters for each side |
| `twop_to_hcr_registration` | Cross-modal cascade: tile sizes, search ranges, thresholds |
| `intensity_extraction` | Background settings for probe intensity measurement |
| `rotation_2p_to_HCR` | Coarse rotation/flip bringing the functional image into FISH orientation |

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
with `masks: "suite2p"` is a normal combination — your own TIFF mean image, your own Suite2p
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

## Troubleshooting

**`pynwb not installed ...`** Printed by Suite2p on every import. NWB is a format EASI-PASS
never touches, so nothing is missing.

**`could not start: No module named 'registrations'`** An internal module name, so never the
real cause. The startup message names what is actually wrong; usually the environment is not
active (`source .venv/bin/activate`).

**Alignment looks wrong** See [docs/landmarks.md](docs/landmarks.md), which covers the common
failure modes and what each one points to.

## Source layout

| File | Purpose |
|---|---|
| `master_pipeline.py` | Orchestrator and CLI, and the order every step runs in |
| `easipass/meta.py` | Manifest parsing and validation |
| `easipass/importers.py` | Dispatch on `input_format` |
| `easipass/functional.py` | Reads the functional side, applies the coarse rotation |
| `easipass/segmentation.py` | Cellpose segmentation, mask matching, merged tables |
| `easipass/registrations.py` | Registration orchestration |
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
