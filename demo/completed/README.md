# Reference output ("the complete")

This is the expected result of running the demo, so you can confirm your own run
produced something sensible. It is intentionally lightweight — a single small CSV,
not the multi-GB OUTPUT tree the pipeline generates (HCR masks alone are ~600 MB).
Ship inputs (`../demo_pre_run/`) + this golden output; regenerate the heavy intermediates
by running the pipeline.

## `twop_plane0_to_HCR01.csv`

The per-cell 2P→HCR matching table produced at
`demo_pre_run/JS078_demo/OUTPUT/MERGED/aligned_masks/twop_plane0_to_HCR01.csv`.
Each row is a candidate 2P↔HCR mask pair; `is_best_match == True` marks the accepted
1:1 match, and the `somaprint_*` columns are the parallel geometric matcher's call.
(The full per-cell feature table joined to the 5 HCR gene channels is also produced,
as `OUTPUT/MERGED/aligned_extracted_features/full_table_*.pkl`.)

## Expected numbers (GPU + cellpose-SAM; yours will be close, not identical)

| quantity | value |
|---|---|
| HCR cells segmented | ~21,000 |
| 2P cells matched 1:1 | ~1,180 |
| best-match median IoU (at 2P z) | ~0.29 |
| 2P→HCR cascade final overlay IoU | ~0.48 |
| global coarse shift found | dx ≈ −18 px, accepted (no `[WARN] Global rejected`) |

If your `Final: IoU` is ~0.48 and the global shift is a small (~tens of px) accepted
value, the 2P→HCR overlay is correct. A railed shift (e.g. `dy=+100`) that gets
rejected means the low-res→hi-res placement was regenerated instead of kept — re-run
and answer **n** to the low-res→hi-res overwrite prompt (see `../README.md`).
