# Outputs

Everything lands under `{base_path}/{sample_name}/OUTPUT/`:

```
OUTPUT/
├── HCR/
│   ├── cellpose/                 3D HCR FISH masks
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

Mask naming, in `cellpose/` and `cellpose_aligned/`: the reference round is plain
`HCR01_masks.tiff`, and non-reference rounds are `HCR{R}_to_HCR{ref}_masks.tiff`, so round 02
against reference 01 is `HCR02_to_HCR01_masks.tiff`.

## The per-cell matching table

At `OUTPUT/MERGED/aligned_masks/twop_plane{N}_to_HCR01.csv`. One row per candidate
functional/HCR FISH pair. The demo's first row, as it appears in the file:

| mask1 | mask2 | iou | iou_at_mask1_z | is_best_match | somaprint_hcr_label | somaprint_confident |
|---|---|---|---|---|---|---|
| 1 | 20646 | 0.064 | 0.287 | True | 20646 | True |

Functional cell 1 pairs with HCR FISH cell 20646, both matchers agree, and overlap is weak in 3D
but better within the plane, which is normal for one plane cutting a volume.

| Column | Meaning |
|---|---|
| `mask1`, `mask2` | Functional cell id, HCR FISH cell id |
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

## The feature table

At `OUTPUT/MERGED/aligned_extracted_features/full_table_{feature}_twop_plane{N}.csv` (and
`.pkl`). Joins those matches to per-gene intensities. One row per HCR FISH cell in the reference
round, one file per feature, single header row.

These are the first three matched rows of the demo's `full_table_mean_twop_plane0.csv`, complete
except that the decimals are shortened. The demo is a single round with five channels, so this
is every column it has:

| mask_id_main | mean_round_01_DAPI | mean_round_01_GCAMP | mean_round_01_PV | mean_round_01_SST | mean_round_01_TDTOMATO | twoP_iou_match | twoP_iou | twoP_somaprint_match | twoP_somaprint_confident | plane |
|---|---|---|---|---|---|---|---|---|---|---|
| 6078 | 6.866 | 1.221 | 0.0607 | 0.0017 | 0.752 | 916 | 0.536 | 916 | True | 0 |
| 7372 | 5.861 | 1.044 | 0.0045 | 0.0002 | 0.493 | 629 | 0.390 | 629 | True | 0 |
| 8399 | 7.441 | 1.267 | 0.0070 | 0.0003 | 0.831 | 1194 | 0.028 | 1224 | True | 0 |

Read a row as: this HCR FISH cell, its intensity in every channel, and which functional cell it
is. The third row is the one to understand before trusting either matcher, since overlap and
soma-print name different functional cells (1194 against 1224) on a weak overlap of 0.028.

| Column | Meaning |
|---|---|
| `mask_id_main` | The HCR FISH cell, in the reference round. The row is about this cell |
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

## Commonly misread columns

- **A blank means no match, not zero.** Reference-round gene columns are never blank, since
  measuring a cell does not depend on matching it.
- **A soma-print pick is not always a confident pick.** In the demo 1,387 cells get a pick and
  1,149 clear the gate, so `twoP_somaprint_match.notna()` and `twoP_somaprint_confident` ask
  different questions.
- **Sizes, containments and intersections are not repeated here.** They are columns of the
  matching table above.

See [`demo/completed/`](../demo/completed/README.md) for the numbers a healthy demo run lands
near, and a tracked table to diff your own run against.
