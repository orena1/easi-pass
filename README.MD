# EASI-PASS

Automated image processing pipeline for **2-photon (2P) microscopy** and **HCR confocal imaging** of mouse brain experiments. Takes raw imaging data and a manifest file, and produces merged cell-identity tables matching 2P functional recordings to HCR molecular markers.

## Installation

Requires **Linux** and [conda](https://docs.conda.io/). An **NVIDIA GPU (CUDA)** is strongly recommended — the demo runs on CPU, but full datasets are impractically slow without one. The segmentation backend is **Cellpose 4 (cellpose-SAM)**.

```bash
conda env create -f environment.yml   # conda-only packages (Python 3.12, PyTorch + CUDA)
conda activate easipass
pip install -e ".[all]"               # the pipeline + all Python dependencies
```

> **Tip — much faster install.** The conda *classic* solver can spend 10+ minutes on the
> `environment.yml` step. Use [mamba](https://mamba.readthedocs.io/) instead
> (`mamba env create -f environment.yml`) or enable the libmamba solver once
> (`conda install -n base conda-libmamba-solver`, then pass `--solver=libmamba`) to cut the
> solve from minutes to seconds. Recent conda versions use libmamba by default.

`environment.yml` installs only what must come from conda channels; everything else is declared in `pyproject.toml` and installed by the `pip` step. Install a subset instead of `[all]` if you don't need every stage:

| Command | Adds |
|---------|------|
| `pip install -e "."` | Core pipeline only |
| `pip install -e ".[twop]"` | 2-photon ingest (Suite2p, ScanBox reader) |
| `pip install -e ".[bigstream]"` | BigStream registration deps |
| `pip install -e ".[notebooks]"` | Jupyter + interactive plotting |
| `pip install -e ".[analysis]"` | ML/stats for the analysis notebooks |

> **BigStream fork:** HCR round-to-round registration uses a fork installed from git by `[bigstream]`/`[all]`. To use a local checkout instead: `pip install -e /path/to/bigstream`.

## Quickstart

**New here? Run the demo first.** [`demo/`](demo/README.md) is a small, real, end-to-end example — one 2P image aligned to an HCR volume — with downloadable data and a reference result to check against. It's the fastest way to confirm your install works and to see the pipeline's inputs and outputs. Then come back here for your own data.

1. Copy the appropriate template from `examples/` and fill in your values
2. Organize your data following the [expected folder structure](#folder-structure)
3. Run the pipeline on the cluster:

```bash
# Full pipeline (2P + HCR)
python master_pipeline.py --manifest examples/your_manifest.hjson

# HCR-only mode (no 2P data needed)
python master_pipeline.py --manifest examples/your_manifest.hjson --only_hcr
```

## Execution Modes

| Mode | Flag | Template | When to use |
|------|------|----------|-------------|
| **HCR-only** | `--only_hcr` | `demo_hcr_only.hjson` | You only have HCR confocal data, no 2P |
| **Full + hi-res** | (none) | `demo_hires.hjson` | 2P + HCR, with high-res anatomical tile runs |
| **Full + standard** | (none) | `demo_standard.hjson` | 2P + HCR, no high-res tiles (uses Suite2p mean image directly) |
| **Stills / image-align** | `--tiff_only` | `demo/JS078_demo.hjson` | Align a static 2P image (not a movie) to HCR — no activity traces |
| **General template** | (none) | `demo.hjson` | All options documented with comments |

### 2P input formats

How the 2P side is read is set per session by `input_format` (in the manifest's `two_photon_imaging.sessions`):

| `input_format` | Reads | Activity traces? | Use when |
|---|---|---|---|
| `sbx` *(default)* | ScanBox `.sbx` + Suite2p | Yes | In-lab functional recordings |
| `suite2p` | An existing Suite2p output folder | Yes | You already ran Suite2p |
| `tiff` | `2P/plane_{N}.tiff` mean image(s) | No | A static 2P image, no movie (pair with `--tiff_only`) |

`tiff` and `suite2p` still do full cross-modal alignment and the molecular join; only the `sbx`/`suite2p` paths yield per-cell activity traces.

## Pipeline Steps

### Full pipeline (2P + HCR)

```
Phase 1 — HCR processing (runs once for all rounds)
  1. HCR round-to-round registration    All rounds → reference round (BigStream)
  2. HCR cellpose segmentation          3D cell segmentation on registered stacks
  3. HCR probe intensity extraction      Per-cell fluorescence for each probe

Phase 2 — 2P processing (per imaging plane)
  4. Tile processing & stitching         (hi-res mode only) Unwarp + stitch tiles
  5. Suite2p extraction                  Mean images from functional recordings
  6. 2P cellpose segmentation            2D cell segmentation on mean images

Phase 3 — Cross-modal registration (per plane)
  7. Low-res → high-res registration     (hi-res mode only) SIFT or landmark-based
  8. 2P → HCR registration              Landmark-based, with cascade refinement

Phase 4 — Output (per plane)
  9. Mask alignment                      Match cells across HCR rounds + 2P
 10. Mask merging                        Final merged feature tables
```

### HCR-only mode (`--only_hcr`)

```
  1. HCR round-to-round registration
  2. HCR cellpose segmentation
  3. HCR probe intensity extraction
  4. Mask alignment across HCR rounds
  5. Merged HCR feature tables
```

## Manifest File (.hjson)

The manifest is an [HJSON](https://hjson.github.io/) file (JSON with comments and relaxed syntax) that configures everything about your experiment. It has two top-level sections:

### `data` — What you're processing

| Field | Description |
|-------|-------------|
| `base_path` | Root path on the cluster (e.g. `/mnt/nasquatch/data/2p/lab/pipeline`) |
| `mouse_name` | Folder name under base_path for this experiment |
| `two_photon_imaging.sessions` | 2P session config (date, runs, planes). Only 1 session supported. Omit for `--only_hcr` |
| `HCR_confocal_imaging.rounds` | List of HCR rounds, each with round number, channel names, and voxel resolution |
| `HCR_confocal_imaging.reference_round` | Which round all others register to. Pick the one with best signal |

#### 2P session fields

| Field | Description |
|-------|-------------|
| `date` | Date string used in folder names: `{mouse}_{date}_{run}` |
| `functional_run` | Run number containing the `suite2p/` folder |
| `functional_planes` | Planes to process. **First = reference plane** for HCR landmark alignment |
| `anatomical_hires_green_runs` | Hi-res tile run numbers (green channel). Paired 1:1 with red |
| `anatomical_hires_red_runs` | Hi-res tile run numbers (red channel) |
| `anatomical_lowres_green_runs` | Low-res anatomical run numbers (alternative to hi-res) |
| `anatomical_lowres_red_runs` | Low-res anatomical run numbers |
| `unwarp_config` | Distortion correction file (in `{base_path}/Calibration_files_for_unwarping/`) |
| `unwarp_steps` | Number of unwarp interpolation steps |

> **Note:** Set either hi-res or low-res anatomical runs, not both. Leave both empty to use only the Suite2p mean image.

#### HCR round fields

| Field | Description |
|-------|-------------|
| `round` | Round identifier string (e.g. `"01"`, `"02"`) |
| `channels` | List of channel names. DAPI should always be first (used for registration) |
| `resolution` | Voxel size `[x, y, z]` in microns — get from your confocal acquisition metadata |

### `params` — How to process it

| Section | Required | Description |
|---------|----------|-------------|
| `HCR_to_HCR_registration` | Yes | BigStream downsampling factors `[x, y, z]`. Default: `[3, 3, 2]` |
| `rotation_2p_to_HCR` | For 2P | Coarse rotation/flip to align 2P orientation with HCR |
| `HCR_cellpose` | Yes | Cellpose model + parameters for HCR 3D segmentation. **Must include `cellpose_channel`** |
| `2p_cellpose` | For 2P | Cellpose model + parameters for 2P 2D segmentation |
| `intensity_extraction` | Yes | Neuropil settings for probe intensity measurement |
| `automation` | No | Override manual steps with automated alternatives (see below) |
| `HCR_selected_registrations` | Later | Populated during the interactive HCR registration step |

#### Automation options

All default to `"manual"`. Set to `"auto"` to use automated alternatives:

| Option | Manual | Auto |
|--------|--------|------|
| `twop_to_hcr` | User-provided BigWarp landmarks only | Automated refinement (still needs initial landmarks) |
| `lowres_to_hires` | BigWarp landmarks + TPS | SIFT feature matching + RANSAC affine |
| `stitching` | BigStitcher coordinates | SIFT + phase correlation |

## Folder Structure

The pipeline expects this input layout and creates `OUTPUT/` alongside it:

```
{base_path}/
└── {mouse_name}/
    ├── 2P/
    │   ├── {mouse}_{date}_{run}/
    │   │   ├── {mouse}_{date}_{run}.sbx
    │   │   └── suite2p/          (for functional run)
    │   └── ...
    ├── HCR/
    │   ├── {mouse}_HCR01.tif     (reference round)
    │   ├── {mouse}_HCR02.tif     (additional rounds)
    │   └── ...
    └── OUTPUT/                   (created by pipeline)
        ├── HCR/
        │   ├── full_registered_stacks/
        │   ├── cellpose/
        │   ├── registrations/
        │   └── extract_intensities/
        ├── 2P/
        │   ├── cellpose/
        │   ├── suite2p/
        │   ├── tile/             (hi-res mode only)
        │   └── registered/
        └── MERGED/
            ├── aligned_masks/
            └── aligned_extracted_features/
                └── merged_table_plane{N}.csv   ← final output
```

In **`tiff` mode** the 2P side is a mean-image TIFF per plane instead of the `.sbx` / `suite2p/` layout:

```
2P/
├── plane_0.tiff          (2P mean image, low-res)
├── plane_0_hires.tiff    (optional hi-res stitched image)
└── ...
```

## Re-Entry / Resume

The pipeline skips steps when output files already exist. To re-run a specific step, delete its output files. To re-run everything, delete the entire `OUTPUT/` folder.

## Key Source Files

| File | Purpose |
|------|---------|
| `master_pipeline.py` | Main orchestrator |
| `easipass/meta.py` | Manifest parsing and validation |
| `easipass/registrations.py` | Registration orchestration (HCR-to-HCR, 2P-to-HCR) |
| `easipass/registrations_utils.py` | Registration algorithms |
| `easipass/segmentation.py` | Cellpose segmentation, mask alignment, merging |
| `easipass/tiling.py` | Tile processing and stitching |
| `easipass/auto_stitching.py` | Automated stitching |
| `easipass/functional.py` | Suite2p data extraction |

