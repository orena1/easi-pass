# Re-running

A step is skipped when its output exists, so an interrupted run resumes where it stopped. Delete
a step's output to redo it, or all of `OUTPUT/` for a clean run.

Three steps differ:

| Step | Behaviour |
|---|---|
| Low-res to hi-res placement, and the cross-modal cascade | **Ask**, do not skip. You get `Overwrite? [y/n]` naming the file, and your answer is reused for every remaining plane. Answer `n` to keep what is there |
| Segmentation | Looks for your own masks before its own output, so deleting `_seg.npy` alone finds the `_masks.tiff` beside it and reuses that. Delete both to segment again |
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
