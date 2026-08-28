# BigWarp tips

How to place the landmarks: what the panels are, what order to work in, and the keys that
matter. For what the pipeline needs from you (filename, CSV columns, the calibration gate,
what to do when the alignment comes out wrong) see [landmarks.md](landmarks.md).

BigWarp is not ours. The [imagej.net page](https://imagej.net/plugins/bigwarp) has the full
command list and is the authority if anything here disagrees with it;
[Bogovic's walkthrough video](https://www.youtube.com/watch?v=EApotxnnQD8) is worth watching
once. **F1** inside BigWarp prints the bindings for your installed version. The demo ships both
images and a finished 18-point set to practise on ([demo/README.md](../demo/README.md)).

## What you are doing

You are not moving an image. You are telling BigWarp that this point here is that point there,
one pair at a time, and it fits a thin-plate spline through the pairs. The warp on screen is a
live preview, recomputed on every new point, and nothing reaches disk until you export.

| Panel | Image | Which file |
|---|---|---|
| **Moving** | your 2P reference plane, 2D | `.../OUTPUT/2P/registered/hires_stitched_plane0_rotated.tiff` |
| **Target** (fixed) | the reference FISH round, 3D | `.../HCR/{sample}_HCR01.tiff` |

The pipeline prints both paths when it pauses. Open them in Fiji, launch
**Plugins > BigDataViewer > Big Warp**, and assign them in that order.

<!-- SCREENSHOT 01: Fiji with both demo TIFFs open and the Big Warp selection dialog filled in: moving = plane_0_hires.tiff, target = JS078_demo_HCR01.tiff. -->

## Flips must be fixed before you get here

**BigWarp has no mirror or flip.** It rotates, pans, zooms and warps, and that is all. If your
2P plane is mirrored relative to the FISH volume, no amount of landmarking will fix it and the
run is wasted.

That is why the pipeline stops on an `ORIENTATION` banner beforehand: look at the two images and
put any `"fliplr": true` or `"flipud": true` into the manifest. Rotation is not asked for,
because the landmarks carry it. On a plane already oriented the prompt does not return until you
delete its `*_rotated.tiff` under `OUTPUT/2P/registered/`.

## Square up the tissue first

Rotation is the part you *can* fix here, and it pays to do it before hunting for anything.
Matching two modalities is hard enough; matching two that also sit 20 degrees apart is much
harder, because your eye stops reading the same group of cells as the same group.

**X**, **Y** or **Z** picks the rotation axis, the **arrow keys** rotate, **Shift+X/Y/Z** snaps
to a plane. This is a viewing aid only: landmarks are stored in image coordinates, so rotating
the view changes nothing you export. Rotate freely.

<!-- SCREENSHOT 02: before/after pair of the two panels, first badly rotated relative to each other, then squared up. -->

## One channel pair at a time

Showing every channel at once makes the field unreadable. Put one on each side, matched to a
channel that stains the same thing (**F3** and **F4** open the visibility dialogs):

| Moving (2P) | Target (FISH) | What you are matching |
|---|---|---|
| GCaMP | cytoDAPI | cell bodies, overall cytoarchitecture |
| sparse marker | tdTomato | the few bright labelled cells, unambiguous where present |
| GCaMP | anti-GCaMP HCR probe | GCaMP-expressing cells directly, if a round carries the probe |

Switch between pairings as you go: the sparse marker gives a few certain correspondences,
cytoDAPI gives coverage everywhere else, and neither alone gets you a well-spread set.

**Re-do the contrast on every switch.** Skipping this is what makes people conclude the images
do not match. The two modalities share nothing in their intensity distributions, so a channel
that looks empty at the previous display range usually comes back once you stretch it. Adjust
both sides until they are comparable to your eye, not until either is objectively correct.

<!-- SCREENSHOT 03: same target channel at a bad display range (near-black) and after adjustment (structure visible), side by side. -->

## Get your bearings

Find the large structures first: white matter tracts, ventricle boundaries, an abrupt
cytoarchitectural change, the tissue edge. These are too coarse to landmark, but they tell you
where in the FISH volume you are. Scroll the target through z (**mouse wheel**, or **,** and
**.**) until the slice looks like the same piece of tissue as your plane.

## The first four points

**space** toggles landmark mode, in which a left click places a point instead of navigating.
Click a feature in the moving panel, then the same feature in the target panel, and the pair
becomes a row in the landmark table. **Shift+left-drag** does both ends at once, **Ctrl+Z**
undoes.

Four is the minimum worth pressing **T** on. Spread them to bracket the field, and take them
from wherever you are most certain, usually the sparse-marker cells. What survives the jump
between modalities is the arrangement, not the brightness: a distinctive triangle of three
neighbouring somata, or a soma in a notch of a vessel. The single brightest object rarely does,
since what is brightest in 2P has no reason to be brightest in FISH.

Set the target z per point, at the slice where that cell is in focus. Those z values are
supposed to differ across the field ([landmarks.md](landmarks.md#placing-the-points)).

<!-- SCREENSHOT 04: landmark mode on, one pair being placed, the new row visible in the landmark table. -->
<!-- SCREENSHOT 05: zoomed crop of one good landmark in both modalities, with the neighbouring-soma arrangement circled. -->

## Press T, then work outward

**T** toggles the moving panel between warped and raw. With four points in, the warp pulls the
images into approximate agreement and the job changes character: instead of searching two
dissimilar images for something in common, you are looking at two that resemble each other, and
the next landmark is often a cell sitting a few pixels off its partner. Each point you add
tightens the warp locally and makes the region just past it readable, so work outward from what
you have rather than jumping across the field.

<!-- SCREENSHOT 06: T pressed with only ~4 points: centre approximately aligned, edges clearly wrong. -->

## Coverage beats count

What matters is not the total but whether any sizeable region has none. A spline is constrained
only where you constrained it; across an empty region it interpolates through whatever the
surrounding points imply, which can be far off. Empty corners and an unconstrained rim are where
cross-modal alignment fails first. Fifteen to twenty-five well-spread points is the usual
landing place (the demo ships 18). Before exporting, show the points (**V**, and **N** for
names), find the barest quarter of the image, and put two there.

<!-- SCREENSHOT 07: the finished 18-point set with points visible, showing spread to the edges, and T on: the two panels in agreement. -->

## When you get lost

The panels navigate independently, so it is easy to end up somewhere unrecognisable. These are
the way back:

| Key | Does |
|---|---|
| **Q** | point the *other* viewer at what the active one is showing |
| **W** | point the *active* viewer at what the other one is showing |
| **E** | centre the active viewer on the nearest landmark |
| **R** | reset the active viewer |

**Ctrl+D** and **Ctrl+Shift+D** step through the landmarks you have placed, which is the fast
way to audit a finished set.

## Transform type

**F2** selects what BigWarp fits. Leave it on **thin-plate spline**, which is what the pipeline
assumes. Affine or similarity is occasionally useful as a check while placing the first few
points, since neither will contort around a badly placed pair the way the spline does; switch
back before exporting.

## Export

**File > Export landmarks**, or **Ctrl+S**, to the exact path the pipeline printed
([landmarks.md](landmarks.md#what-the-pipeline-asks-for) has the pattern and the columns).
**Ctrl+O** loads a set back in to extend later, or to disable a bad point instead of deleting
it. Then re-run, and check the overlays in `OUTPUT/2P/registered/QualityCheck/` before
committing to a full run;
[`--check_alignment`](landmarks.md#settling-the-alignment-before-committing-to-a-full-run)
exists for that.

<!-- SCREENSHOT 08: the export dialog with the pipeline's prompted filename pasted in. -->

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
