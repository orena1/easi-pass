# Reference output ("the complete")

This is the expected result of running the demo, so you can confirm your own run
produced something sensible. It is deliberately lightweight: a single small CSV,
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
| HCR cells segmented (whole 3D volume, all 39 z-slices) | ~21,000 |
| 2P cells segmented in the plane | 1,439 |
| 2P cells matched 1:1 (IoU) | 1,199, or **83% of the 1,439 segmented** |
| 2P cells soma-print called confidently | 1,149, or 80% |
| best-match median IoU (at 2P z) | 0.29 |
| 2P→HCR cascade final overlay IoU | ~0.48 |
| global coarse shift found | dx ≈ −18 px, accepted (no `[WARN] Global rejected`) |

Note the two cell counts are not comparable directly: the ~21,000 FISH cells span the whole
3D volume, while one 2P plane intersects only a thin slab of it. The match rate to judge your
run by is matched over cells segmented, so ~83%. The console prints the stricter
matched over cells that overlap anything, which is ~91%.

If your `Final: IoU` is ~0.48 and the global shift is a small (~tens of px) accepted
value, the 2P→HCR overlay is correct. A railed shift (e.g. `dy=+100`) that gets
rejected means the low-res to hi-res placement was regenerated rather than kept. Re-run
and answer **n** to that overwrite prompt (see `../README.md`).
