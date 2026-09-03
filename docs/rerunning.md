# Re-running

A step is skipped when its output exists, so an interrupted run resumes where it stopped. Delete
a step's output to redo it, or all of `OUTPUT/` for a clean run.

> If you supplied your own masks, they live under `OUTPUT/` too, so deleting the whole folder
> deletes them along with everything else. Keep a copy outside `OUTPUT/`, or delete step by
> step — see [masks.md](masks.md).

Three steps differ:

| Step | Behaviour |
|---|---|
| Low-res to hi-res placement, and the cross-modal cascade | **Ask**, do not skip. You get `Overwrite? [y/n]` naming the file, and your answer is reused for every remaining plane. Answer `n` to keep what is there |
| Segmentation | Skips on its own output first, and only then looks for masks you supplied — so on the functional side `_seg.npy` wins over the `_masks.tiff` beside it. Delete `_seg.npy` to have your `_masks.tiff` read; delete both to segment again. Either way the run names the file it used |
| Merged feature tables | Rebuild when any intensity file is newer than the table, so they refresh on their own |

## Re-orienting the functional image

This is the one thing the manifest alone cannot redo, since the flip is applied once, on the
first run. Delete

```
OUTPUT/2P/registered/lowres_meanImg_C0_plane{N}_rotated.tiff
```

to be asked again, and delete the landmarks with it, since they were placed on the old
orientation.

## Re-doing only the alignment

`--check_alignment` stops after registering and matching the functional planes to the reference
round, so you can settle the cross-modal step without processing later rounds. See
[landmarks.md](landmarks.md#checking-the-alignment-first).
