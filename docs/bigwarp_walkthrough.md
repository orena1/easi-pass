# A working session in BigWarp

How to actually place the landmarks: what the two panels are, what order to do things in, and
the keys that matter. For what the pipeline needs from you (the filename to save to, the CSV
columns, the micron calibration gate, what to do when the alignment comes out wrong) see
[landmarks.md](landmarks.md).

BigWarp is not ours. Two references worth keeping open:

- **[The BigWarp page on imagej.net](https://imagej.net/plugins/bigwarp)**, which has the full
  command list and is the authority if anything here disagrees with it.
- **[Manually Register Images with BigWarp](https://www.youtube.com/watch?v=EApotxnnQD8)**, John
  Bogovic (who wrote it) driving it for an hour. Worth watching once.

**F1** inside BigWarp prints every binding for the version you have installed. The table at the
end of this page is only the subset this workflow uses.

To practise first, the shipped demo has both images plus a finished 18-point set you can load
and inspect. See [demo/README.md](../demo/README.md).

## What you are doing

You are not moving an image. You are telling BigWarp that this point here is that point there,
one pair at a time, and it fits a thin-plate spline through the pairs you give it. The warp on
screen is a live preview of that fit, recomputed each time you add a point. Nothing is written
to disk until you export, so there is no cost to placing a point, looking at it, and moving it.

Two panels, two roles:

| Panel | Image | Which file |
|---|---|---|
| **Moving** | your 2P reference plane, 2D | `.../OUTPUT/2P/registered/hires_stitched_plane0_rotated.tiff` |
| **Target** (fixed) | the reference FISH round, 3D | `.../HCR/{sample}_HCR01.tiff` |

The pipeline prints both paths when it pauses. Open both TIFFs in Fiji, then launch
**Plugins > BigDataViewer > Big Warp** and assign them in that order.

<!-- SCREENSHOT 01: Fiji with both demo TIFFs open and the Big Warp selection dialog filled in: moving = plane_0_hires.tiff, target = JS078_demo_HCR01.tiff. -->

## Flips must be fixed before you get here

**BigWarp has no mirror or flip.** It rotates, pans, zooms and warps, and that is all. The
rigid and similarity fits cannot produce a reflection at all, and a spline handed mirrored
correspondences folds the image rather than flipping it. So if your 2P plane is mirrored
relative to the FISH volume, no amount of landmarking will fix it, and the run is wasted.

This is why the pipeline stops on an `ORIENTATION` banner before landmarking, prints the 2P and
HCR paths, and asks you to put any `"fliplr": true` or `"flipud": true` into the manifest. Look
at the two images at that point and answer it. Rotation is not asked for, because the landmarks
carry it.

If a plane has already been oriented the prompt does not appear again. Delete the plane's
`*_rotated.tiff` under `OUTPUT/2P/registered/` to get it back.

## Square up the tissue first

Rotation is the part you *can* fix here, and it is worth doing before you look for anything.
Matching two modalities is hard enough; matching two that are also 20 degrees apart is much
harder, because your eye stops reading the same group of cells as the same group.

Rotate the view until the panels sit in roughly the same orientation. **X**, **Y** or **Z**
picks the axis, the **arrow keys** rotate, and **Shift+X/Y/Z** snaps to a plane. Use your
record of how the tissue was mounted and cut.

This is a viewing aid. Rotating the view changes nothing that gets exported, since landmarks are
stored in image coordinates, and the real 2P-to-FISH orientation is handled by
`params.rotation_2p_to_HCR` and the orientation prompt. Rotate freely, you cannot break
anything.

<!-- SCREENSHOT 02: before/after pair of the two panels, first badly rotated relative to each other, then squared up. -->

## One channel pair at a time

Both volumes are multi-channel, and showing everything at once makes the field unreadable. Put
one channel on each side, matched to a channel that stains the same thing:

| Moving (2P) | Target (FISH) | What you are matching |
|---|---|---|
| GCaMP | cytoDAPI | cell bodies, overall cytoarchitecture |
| sparse marker | tdTomato | the few bright labelled cells, unambiguous where present |
| GCaMP | anti-GCaMP HCR probe | GCaMP-expressing cells directly, if a round carries the probe |

**F3** and **F4** open the visibility and grouping dialogs for the moving and target images.

Switch between these pairings as you go. The sparse marker gives you a small number of certain
correspondences, cytoDAPI gives you dense coverage everywhere else, and neither alone gets you a
well-spread set.

**Re-do the contrast on every switch.** People skip this and conclude the two images do not
match. The modalities have nothing in common in their intensity distributions, and a channel
that looks empty at the previous channel's display range usually comes back as soon as you
stretch it. Adjust brightness and contrast on both sides (the BigDataViewer brightness dialog,
from the Settings menu of either viewer) until the panels are comparable to your eye. Not until
either one is objectively correct.

<!-- SCREENSHOT 03: same target channel at a bad display range (near-black) and after adjustment (structure visible), side by side. -->

## Get your bearings before placing anything

Find the large structures first: white matter tracts, ventricle boundaries, an abrupt
cytoarchitectural change, the tissue edge. You are not landmarking these, they are too coarse
to click a point on. They tell you which part of the FISH volume you are in and roughly where
your 2P plane sits inside it. Scroll the target through z (**mouse wheel**, or **,** and **.**)
until the slice looks like the same piece of tissue as your plane.

## The first four points

**space** toggles landmark mode. While it is on, a left click places a point instead of
navigating. Click a feature in the moving panel, then the same feature in the target panel, and
the pair becomes a row in the landmark table. **Shift+left-drag** does both ends in one gesture.
**Ctrl+Z** undoes.

Four is the minimum worth pressing **T** on. Spread them so they bracket the field rather than
sitting in one corner, and take them from wherever you are most certain, which is usually the
sparse-marker cells.

What makes a landmark survive the jump between modalities is the arrangement, not the
brightness. A distinctive triangle of three neighbouring somata, or a soma sitting in a notch of
a vessel, is findable in the other image. The single brightest object usually is not, because
what is brightest in 2P has no reason to be brightest in FISH.

Set the target z per point, at the slice where that cell is actually in focus. Those z values
are supposed to differ across the field, see
[landmarks.md](landmarks.md#placing-the-points).

<!-- SCREENSHOT 04: landmark mode on, one pair being placed, the new row visible in the landmark table. -->
<!-- SCREENSHOT 05: zoomed crop of one good landmark in both modalities, with the neighbouring-soma arrangement circled. -->

## Press T, then work outward

**T** toggles the moving panel between raw and warped. With four points in, the warp pulls the
two images into approximate agreement, and the job changes character. Before T you are searching
two dissimilar images for something in common. After T the panels look alike and the next
landmark is often obvious, a cell sitting a few pixels off its partner.

So place four, press T, then find the rest by scanning outward from what you have. Each point
tightens the warp locally, which makes the region just past it readable, which gives you the
next point. Placing a point far from everything else is much harder and there is no reason to do
it.

<!-- SCREENSHOT 06: T pressed with only ~4 points: centre approximately aligned, edges clearly wrong. -->

## Coverage beats count

What matters is not how many points you have but whether any sizeable region has none. A
thin-plate spline is only constrained where you constrained it; across an empty region it
interpolates smoothly through whatever the surrounding points imply, which can be far off. Empty
corners and an unconstrained rim are where cross-modal alignment fails first.

Fifteen to twenty-five well-spread points is the usual landing place, and the demo ships 18.
Before exporting, look at the whole field with points visible (**V** toggles points, **N** their
names), find the barest quarter of the image, and put two points there.

<!-- SCREENSHOT 07: the finished 18-point set with points visible, showing spread to the edges, and T on: the two panels in agreement. -->

## When you get lost

The panels navigate independently, so it is easy to end up somewhere with nothing recognisable
in view. These four keys are the way back:

| Key | Does |
|---|---|
| **Q** | point the *other* viewer at what the active one is showing |
| **W** | point the *active* viewer at what the other one is showing |
| **E** | centre the active viewer on the nearest landmark |
| **R** | reset the active viewer |

**Ctrl+D** and **Ctrl+Shift+D** step forward and backward through the landmarks you have placed.
That is the fast way to audit a finished set: walk the list and check each pair still looks
right.

## Transform type

**F2** selects what BigWarp fits: thin-plate spline, affine, similarity, rotation or
translation. Leave it on **thin-plate spline**, which is what the pipeline assumes, and the
local deformation is the reason for doing this by hand. Affine or similarity is occasionally
useful as a check while placing the first few points, since it will not contort around a badly
placed pair the way the spline does. Switch back before exporting.

## Export

**File > Export landmarks**, or **Ctrl+S**. Save to the exact path the pipeline printed;
[landmarks.md](landmarks.md#what-the-pipeline-asks-for) has the filename pattern and the CSV
columns. **Ctrl+O** loads an existing file back in, so a set can be reopened and extended later,
and a bad point can be disabled instead of deleted.

<!-- SCREENSHOT 08: the export dialog with the pipeline's prompted filename pasted in. -->

Then re-run and check the overlays in `OUTPUT/2P/registered/QualityCheck/` before committing to
a full run. `--check_alignment` exists for this. Both are covered in
[landmarks.md](landmarks.md#settling-the-alignment-before-committing-to-a-full-run).

## Keys, condensed

| | |
|---|---|
| **space** | landmark mode on/off |
| **left click** x2 | place a pair (moving, then target) |
| **shift+left-drag** | place a pair in one gesture |
| **Ctrl+Z** / **Ctrl+Y** | undo / redo a landmark change |
| **T** | toggle warped / raw moving image |
| **X/Y/Z** + arrows | rotate the view; **shift+X/Y/Z** snaps to a plane |
| **mouse wheel**, **,** / **.** | move through z |
| **Q** / **W** / **E** / **R** | sync other / sync active / centre on nearest landmark / reset |
| **Ctrl+D** / **Ctrl+Shift+D** | next / previous landmark |
| **V** / **N** | point visibility / point names |
| **F2** | transform type |
| **F3** / **F4** | moving / target visibility and grouping |
| **Ctrl+S** / **Ctrl+O** | save / load landmarks |
| **F1** | every binding, for your installed version |
