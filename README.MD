# EASI-PASS

Align two-photon functional imaging to multi-round in-situ molecular imaging, cell by cell.

EASI-PASS takes a **mean image** from a functional recording and one or more **EASI-FISH
confocal volumes**, segments cells in both, registers them onto each other, matches cells
across modalities, and writes a single per-cell table joining functional identity to
molecular readout. It also runs without any functional data, to register and match cells
across successive FISH rounds alone.

It is a registration-and-matching pipeline. It does not process raw functional recordings,
compute ΔF/F, or stitch image tiles — those happen upstream, and EASI-PASS takes their
output as input.

## What it needs

| Input | Format |
|---|---|
| Functional field of view | One 2D **mean image** per plane, TIFF |
| Molecular rounds | One multi-channel **3D volume** per FISH round, TIFF |
| *(optional)* Hi-res structural image | A single stitched 2D TIFF per plane, used as an alignment bridge |
| A few seed landmarks | Placed once in [BigWarp](https://imagej.net/plugins/bigwarp), between one functional plane and the reference FISH volume. Only needed for cross-modal runs — FISH-only runs need none, and **the demo ships its landmarks, so you never open BigWarp to run it** |

Everything else is set in a manifest file.

## Installation

Requires **Linux** and [conda](https://docs.conda.io/). An **NVIDIA GPU (CUDA)** is strongly
recommended — the demo runs on CPU, but full datasets are impractically slow without one.
Segmentation uses **Cellpose 4 (cellpose-SAM)**.

```bash
conda env create -f environment.yml   # Python 3.12, PyTorch + CUDA
conda activate easipass
pip install -e .                      # the pipeline and its Python dependencies
```

`environment.yml` carries only what must come from conda channels — Python and CUDA-enabled
PyTorch. Everything else is a pip dependency in `pyproject.toml`, and `pip install -e .`
covers every stage and mode. Optional extras: `.[notebooks]` for Jupyter, `.[analysis]` for
the analysis notebooks, `.[all]` for both.

Cross-modal runs also need [Fiji](https://fiji.sc/)'s BigWarp for placing seed landmarks
(Plugins > BigDataViewer > Big Warp). See [docs/landmarks.md](docs/landmarks.md).

> If `conda env create` is slow, [mamba](https://mamba.readthedocs.io/) does the same job in
> seconds. Multi-round registration pulls a pinned BigStream fork from git; to use a local
> checkout instead, `pip install -e /path/to/bigstream` afterwards.

## Start with the demo

[`demo/`](demo/README.md) is a small, real, end-to-end example: one two-photon plane from
mouse JS078 aligned to a 5-channel FISH volume, with a reference result to check yourself
against. It is the fastest way to confirm your install works and to see what goes in and
what comes out.

```bash
python demo/fetch_demo_data.py     # downloads the imaging data
python master_pipeline.py --manifest demo/JS078_demo.hjson
```

Nothing to edit — the demo manifest points at its own data. The run pauses three times to
let you check intermediate output; `demo/README.md` gives the answers.

## Running your own data

1. Copy the template that matches what you have:

   | Template | For |
   |---|---|
   | [`demo_tiff.hjson`](examples/demo_tiff.hjson) | **Start here.** You supply a 2P mean image per plane as `plane_{N}.tiff` |
   | [`demo_suite2p.hjson`](examples/demo_suite2p.hjson) | Same, but point at your Suite2p folder and the mean image is pulled from `ops.npy` |
   | [`demo_hcr_only.hjson`](examples/demo_hcr_only.hjson) | FISH rounds alone, no functional data |

   A hi-res structural image and the single-round case both work without any manifest
   change — see the notes at the top of `demo_tiff.hjson`.

   [`param_example.hjson`](examples/param_example.hjson) documents every tunable option in
   `params`. It is a reference to copy settings out of, not a starting point — it has no
   `data` section.
2. Set `base_path` and `mouse_name` at the top of your manifest, then put your files here.
   These are the only inputs; everything under `OUTPUT/` is created for you.

   ```
   {base_path}/{mouse_name}/
   ├── 2P/
   │   ├── plane_0.tiff               your functional mean image, one per plane
   │   └── plane_0_hires.tiff         optional, and must already be stitched
   └── HCR/
       ├── {mouse_name}_HCR01.tiff    reference round
       └── {mouse_name}_HCR02.tiff    any further rounds
   ```

   The numbers have to line up: `{N}` in `plane_{N}.tiff` matches an entry in
   `functional_planes`, and `{R}` in `_HCR{R}.tiff` matches a `round` value. `.tif` and
   `.tiff` both work, and case is ignored.

3. Run:

```bash
python master_pipeline.py --manifest examples/your_manifest.hjson
```

A manifest with no `two_photon_imaging` section runs FISH rounds only; nothing extra to
pass. Use `--only_hcr` when you want to skip the functional half of a manifest that has one.

Cross-modal alignment is the step most likely to need another attempt — it depends on your
seed landmarks, the functional segmentation, and whether the recovered tissue actually
contains the imaged field. Add `--check_alignment` to settle that first:

```bash
python master_pipeline.py --manifest examples/your_manifest.hjson --check_alignment
```

This segments the reference FISH round only, registers and matches the functional planes to
it, reports the match rate, and stops — so the later rounds need not even be imaged yet.
Review the overlays in `OUTPUT/2P/registered/QualityCheck/`, then re-run the same command
without the flag to segment the remaining rounds and build the output tables. Everything the
check produced is reused.

## What it does

```
Molecular side (once, for all rounds)
  1. Round-to-round registration     Each FISH round -> reference round.
                                     Cell centroids seed a global affine (RANSAC),
                                     then block-wise deformable refinement (BigStream).
  2. 3D segmentation                 Cellpose per plane, linked across planes into 3D cells
  3. Probe intensity extraction      Per-cell fluorescence per channel, with local background

Functional side (per plane)
  4. 2D segmentation                 Cellpose on the mean image
  5. Low-res -> hi-res placement     Only if a hi-res structural image is supplied

Cross-modal (per plane)
  6. Registration                    Seed landmarks -> thin-plate spline surface through the
                                     FISH volume -> rigid search -> global affine ->
                                     coarse-to-fine local tile cascade
  7. Matching                        Mask overlap (IoU) and soma-print, reported per cell

Output
  8. Merged table                    One row per cell: matched identities, per-gene
                                     intensities across rounds, match-quality scores
```

With `--only_hcr`, steps 4–7 are skipped and cells are matched across FISH rounds only.

> **Round-to-round registration** uses cell centroids from the segmentation, not detected
> fluorescent spots. If rounds register poorly, tune `HCR_to_HCR_registration.global` and
> `.local`: lower `match_threshold` (0.3 → 0.2) to accept weaker centroid correspondences,
> lower `count_floor` / `match_floor` to let sparse blocks contribute, and widen
> `context_radius_um` for tissue with less distinctive local geometry. Check the reference
> round's Cellpose segmentation first — every centroid comes from it.

## What you get

The primary product is a per-cell matching table,
`OUTPUT/MERGED/aligned_masks/twop_plane{N}_to_HCR01.csv`. Each row is a candidate
functional↔FISH cell pair; `is_best_match` marks the accepted 1:1 call.

| Column | Meaning |
|---|---|
| `mask1`, `mask2` | Functional cell id, FISH cell id |
| `iou`, `iou_at_mask1_z` | Mask overlap, in 3D and in the functional plane |
| `containment_2p`, `containment_hcr_at_z` | Directional overlap, each way |
| `mask1_size`, `mask2_size`, `mask2_size_at_mask1_z` | Mask sizes, in voxels |
| `is_best_match` | The accepted overlap-based 1:1 match |
| `somaprint_hcr_label` | The independent geometric matcher's call for this cell |
| `somaprint_best_score`, `somaprint_second_score` | Its best and runner-up scores |
| `somaprint_confident` | Whether best separates significantly from runner-up |

```
mask1,mask2,intersection,...,iou_at_mask1_z,...,is_best_match,somaprint_hcr_label,...,somaprint_confident
1,20646,117,...,0.2875,...,True,20646,...,True
1,20482,7,...,0.0109,...,False,20646,...,True
2,18531,0,...,0.0000,...,False,18531,...,False
```

Both matchers are reported for every cell rather than reconciled for you, so you can set
your own thresholds. Alongside it, `OUTPUT/MERGED/aligned_extracted_features/full_table_*.pkl`
joins these matches to the per-gene intensities across all FISH rounds.

In the demo, 1,199 of the 1,387 functional cells in the plane are matched — **86%** — with
a median overlap of 0.29 in the functional plane, and soma-print confidently calls 83%. A
tracked copy of the table is in [`demo/completed/`](demo/completed/README.md) to diff your
run against.

## Manifest

The manifest is an [HJSON](https://hjson.github.io/) file — JSON with comments and relaxed
syntax. It has two top-level sections: `data` (what you're processing) and `params` (how).

### `data`

| Field | Description |
|---|---|
| `base_path` | Root directory holding your experiment folders |
| `mouse_name` | Folder name for this experiment. **Outputs are written under this name** |
| `HCR_confocal_imaging.rounds` | One entry per FISH round: round id, channel names, voxel resolution |
| `HCR_confocal_imaging.reference_round` | The round all others register to. Pick the one with the best signal |
| `two_photon_imaging.sessions` | Functional session config. Omit entirely for FISH-only runs |

Per FISH round:

| Field | Description |
|---|---|
| `round` | Round identifier, e.g. `"01"` |
| `channels` | Channel names. The nuclear/cytoplasmic stain used for registration comes first |
| `resolution` | Voxel size `[x, y, z]` in microns, from your confocal metadata |

Per functional session:

| Field | Description |
|---|---|
| `functional_planes` | Planes to process. **The first is the reference plane** for landmark alignment |
| `input_format` | How the functional side is read — see below |

### `params`

| Section | Description |
|---|---|
| `HCR_to_HCR_registration` | Round-to-round global and local registration settings |
| `HCR_cellpose` | Cellpose model and parameters for 3D FISH segmentation |
| `2p_cellpose` | Cellpose model and parameters for 2D functional segmentation |
| `twop_to_hcr_registration` | Cross-modal cascade: tile sizes, search ranges, thresholds |
| `intensity_extraction` | Background settings for probe intensity measurement |
| `rotation_2p_to_HCR` | Coarse rotation/flip bringing the functional image into FISH orientation |

[`examples/param_example.hjson`](examples/param_example.hjson) documents every knob with its
default and when to change it.

### Functional input formats

Set per session by `input_format`:

| Value | Reads | Use when |
|---|---|---|
| `tiff` | `2P/plane_{N}.tiff` mean images | **The standard path.** Any microscope, any preprocessing |
| `suite2p` | An existing Suite2p output folder | You already ran Suite2p and want the mean image pulled from it |
| `sbx` | ScanBox `.sbx` via Suite2p | Andermann-lab internal acquisition format |

`tiff` is the path this pipeline is built around and the one the demo uses. `sbx` exists for
in-house acquisition and is not expected to be useful outside the lab.

`input_format` is **required** whenever there is a `two_photon_imaging` section. There is no
default, an unrecognised value is an error, and there is no command-line switch that
overrides it.

### Hi-res structural images

If you acquired a higher-resolution structural image of the same field, supply it as
`2P/plane_{N}_hires.tiff` and EASI-PASS will use it as a bridge: the low-res mean image is
placed into it, and the alignment to the FISH volume is computed at the higher resolution.
The image must already be stitched.

> **On tile stitching.** `easipass/tiling.py` and `easipass/auto_stitching.py` do assemble
> tiles into a stitched field, by phase correlation between adjacent tiles with a
> median-shift consensus layout. This works, but it assumes our ScanBox acquisition's tile
> geometry and naming, so it is **not a supported general feature** — supply an
> already-stitched image instead. Generalizing it mainly needs an agreed tile-input format
> (per-tile files plus a nominal grid position); that is an open contribution we'd welcome.

## What the pipeline writes

Everything lands under `{base_path}/{mouse_name}/OUTPUT/`, alongside your inputs:

```
OUTPUT/
├── HCR/
│   ├── full_registered_stacks/   rounds warped into the reference frame
│   ├── cellpose/                 3D FISH masks
│   └── extract_intensities/      per-cell fluorescence per channel
├── 2P/
│   ├── cellpose/                 2D functional masks
│   └── registered/               landmarks, transforms, QC overlays
└── MERGED/
    ├── aligned_masks/            per-cell match tables
    └── aligned_extracted_features/   final tables, matches joined to genes
```

The two you will actually open are `MERGED/aligned_masks/` for the matches and
`2P/registered/QualityCheck/` for the overlays that tell you whether alignment worked.

## Re-running

The pipeline skips a step when its output already exists, so an interrupted run resumes
where it stopped. Delete a step's output files to redo just that step, or the whole
`OUTPUT/` folder for a clean run.

## Troubleshooting

**`pynwb not installed ...`** — printed by Suite2p on every import. NWB is a file format
EASI-PASS never touches. Nothing is missing.

**`could not start: No module named 'registrations'`** — an internal module name, so this is
never the real cause. The startup message names what is actually wrong; the usual answer is
that the environment is not active (`conda activate easipass`).

**Alignment looks wrong** — see [docs/landmarks.md](docs/landmarks.md), which covers the
common failure modes and what each one points to.

## Source layout

Where to look first, by what you are trying to change:

| File | Purpose |
|---|---|
| `master_pipeline.py` | Orchestrator and CLI — the order every step runs in |
| `easipass/meta.py` | Manifest parsing and validation |
| `easipass/importers.py` | Dispatch on `input_format` (tiff / suite2p / sbx) |
| `easipass/functional.py` | Reads the functional side and applies the coarse rotation |
| `easipass/segmentation.py` | Cellpose segmentation, mask matching, merged tables |
| `easipass/registrations.py` | Registration orchestration |
| `easipass/registrations_utils.py` | Cross-modal registration algorithms |
| `easipass/hcr_centroid_registration.py` | Centroid-seeded round-to-round registration |
| `easipass/somaprint.py` | Geometric cross-modal cell matcher |
| `easipass/somaprint_hcr.py` | Geometric round-to-round cell matcher |

The rest of `easipass/` is supporting code: tile stitching, the automation checkpoints, the
BigStream wrappers, and analysis helpers.

## Citation

If you use EASI-PASS, please cite the accompanying paper. Citation details will be added
here on publication; see [CITATION.cff](CITATION.cff).

## License

BSD 3-Clause. See [LICENSE](LICENSE).
