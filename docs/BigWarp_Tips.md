# BigWarp tips

How to place the landmarks: what the two panels are, what order to work in, and the keys that
matter. For what the pipeline needs from you, see [landmarks.md](landmarks.md): the filename,
the CSV columns, the calibration gate, and what to do when the alignment comes out wrong.

BigWarp is not ours. The [imagej.net page](https://imagej.net/plugins/bigwarp) lists every
command and is the authority if anything here disagrees with it, and
[Bogovic's video](https://www.youtube.com/watch?v=EApotxnnQD8) is worth watching once. Inside
BigWarp, **F1** prints the bindings for your installed version. To practise before doing this
for real, the demo ships both images and a finished 18-point set
([demo/README.md](../demo/README.md)).

## What you are doing

You are not moving an image. You are telling BigWarp that this point here is that point there,
one pair at a time, and it fits a thin-plate spline through the pairs. What you see on screen is
a preview of that fit. It is recomputed every time you add a point, and nothing reaches disk
until you export, so a point costs nothing: place it, look, move it.

| Panel | Image | Which file |
|---|---|---|
| **Moving** | your 2P reference plane, 2D | `.../OUTPUT/2P/registered/hires_stitched_plane0_rotated.tiff` |
| **Target** (fixed) | the reference FISH round, 3D | `.../HCR/{sample}_HCR01.tiff` |

The pipeline prints both paths when it pauses. Open them in Fiji, launch
**Plugins > BigDataViewer > Big Warp**, and assign them in that order.

<!-- SCREENSHOT 01: Fiji with both demo TIFFs open and the Big Warp selection dialog filled in: moving = plane_0_hires.tiff, target = JS078_demo_HCR01.tiff. -->

## Flips must be fixed before you get here

**BigWarp has no mirror or flip.** It rotates, pans, zooms and warps, and that is all. If your
2P plane is mirrored relative to the FISH volume, landmarking cannot fix it and the run is
wasted.

That is why the pipeline stops on an `ORIENTATION` banner first. Look at the two images it
names, and if one is mirrored, put `"fliplr": true` or `"flipud": true` in the manifest. It does
not ask about rotation, because each landmark pair you place records that already. Once a plane
has been oriented the prompt stops appearing; delete that plane's `*_rotated.tiff` under
`OUTPUT/2P/registered/` to get it back.

## Rotate the tissue into rough alignment

Rotation is the part you can fix here, and fixing it first saves time. Two modalities are hard
enough to match. Two that also sit 20 degrees apart are much harder, because your eye stops
reading the same group of cells as the same group.

Press **X**, **Y** or **Z** to pick the axis, then rotate with the **arrow keys**;
**Shift+X/Y/Z** rotates straight to that plane. Only the view changes. Landmarks are stored in
image coordinates, so you export the same file however you were looking at it. Rotate freely.

<!-- SCREENSHOT 02: before/after pair of the two panels, first badly rotated relative to each other, then squared up. -->

## Show one channel pair at a time

Every channel at once is unreadable. Put one on each side, matched to a channel that stains the
same thing. **F3** and **F4** open the visibility dialogs for the moving and target images.

| Moving (2P) | Target (FISH) | What you are matching |
|---|---|---|
| GCaMP | cytoDAPI | cell bodies, overall cytoarchitecture |
| sparse marker | tdTomato | the few bright labelled cells, unambiguous where present |
| GCaMP | anti-GCaMP HCR probe | GCaMP-expressing cells directly, if a round carries the probe |

Switch between these pairings as you work. The sparse marker gives you a handful of certain
correspondences. cytoDAPI gives you coverage everywhere else. You need both.

**Re-do the contrast every time you switch.** Skip it and you will conclude the images do not
match. The two modalities share nothing in their intensity distributions, so a channel that
looks empty at the previous display range usually appears as soon as you stretch it. Adjust both
sides until they look comparable to your eye, which is not the same as either one being correct.

<!-- SCREENSHOT 03: same target channel at a bad display range (near-black) and after adjustment (structure visible), side by side. -->

## Get your bearings

Start with the big structures: white matter tracts, ventricle boundaries, an abrupt change in
cytoarchitecture, the tissue edge. They are too coarse to landmark, but they tell you where in
the volume you are. Scroll the target through z with the **mouse wheel**, or **,** and **.**,
until the slice looks like the same piece of tissue as your plane.

## Place the first four points

Press **space** for landmark mode, where a left click places a point instead of navigating.
Click a feature in the moving panel, then the same feature in the target panel. The pair becomes
a row in the landmark table. **Shift+left-drag** does both ends in one gesture, and **Ctrl+Z**
undoes.

Four is the minimum worth pressing **T** on. Put them near the four edges of the field rather
than together in the middle, and start with the cells you are surest of, usually the
sparse-marker ones.

Choose landmarks by their arrangement, not their brightness. A triangle of three neighbouring
somata is recognisable in the other modality, and so is a soma tucked into a bend of a vessel.
The brightest cell in the 2P image usually is not, because nothing makes it the brightest one in
FISH.

Set the target z for each point individually, at the slice where that cell is in focus. Those z
values are meant to differ across the field ([landmarks.md](landmarks.md#placing-the-points)).

<!-- SCREENSHOT 04: landmark mode on, one pair being placed, the new row visible in the landmark table. -->
<!-- SCREENSHOT 05: zoomed crop of one good landmark in both modalities, with the neighbouring-soma arrangement circled. -->

## Press T, then work outward

**T** switches the moving panel between warped and raw. With four points in, the two panels line
up roughly, and the job gets much easier: instead of hunting two dissimilar images for something
in common, you are looking for a cell that sits a few pixels off its partner.

Every point you add improves the warp around it, which makes the region just beyond it readable,
which gives you the next point. So work outward from what you have. Jumping to the far side of
the field means starting from scratch again.

<!-- SCREENSHOT 06: T pressed with only ~4 points: centre approximately aligned, edges clearly wrong. -->

## Cover the field

What matters is not the total but whether some large region has nothing in it. The spline only
fits where you gave it points. Elsewhere it interpolates from the points around it, and that
guess can be far off, which is why alignment fails at empty corners and edges first.

Fifteen to twenty-five well-spread points is usually enough, and the demo ships 18. Before you
export, press **V** to show the points (**N** for their names), find the emptiest quarter of the
image, and put two there.

<!-- SCREENSHOT 07: the finished 18-point set with points visible, showing spread to the edges, and T on: the two panels in agreement. -->

## When you get lost

The panels navigate independently, so you will end up looking at tissue you cannot place. These
four get you back:

| Key | Does |
|---|---|
| **Q** | point the *other* viewer at what the active one is showing |
| **W** | point the *active* viewer at what the other one is showing |
| **E** | centre the active viewer on the nearest landmark |
| **R** | reset the active viewer |

**Ctrl+D** and **Ctrl+Shift+D** step through the points you have placed, which is the quick way
to audit a finished set.

## Transform type

**F2** chooses what BigWarp fits. Leave it on **thin-plate spline**, which is what the pipeline
assumes. Affine and similarity are useful as a check while you have only a few points, because
neither bends to accommodate a badly placed pair the way the spline does. Switch back before you
export.

## Export

**File > Export landmarks**, or **Ctrl+S**, to the exact path the pipeline printed.
[landmarks.md](landmarks.md#what-the-pipeline-asks-for) has the filename pattern and the
columns. **Ctrl+O** loads a set back in, so you can extend it later or disable a bad point
instead of deleting it.

Then re-run and look at the overlays in `OUTPUT/2P/registered/QualityCheck/` before you commit
to a full run.
[`--check_alignment`](landmarks.md#settling-the-alignment-before-committing-to-a-full-run) stops
the pipeline right after this step so you can.

<!-- SCREENSHOT 08: the export dialog with the pipeline's prompted filename pasted in. -->

## Keys, condensed

| | |
|---|---|
| **space** | landmark mode on/off |
| **left click** x2 | place a pair (moving, then target) |
| **shift+left-drag** | place a pair in one gesture |
| **Ctrl+Z** / **Ctrl+Y** | undo / redo a landmark change |
| **T** | toggle warped / raw moving image |
| **X/Y/Z** + arrows | rotate the view; **shift+X/Y/Z** rotates to that plane |
| **mouse wheel**, **,** / **.** | move through z |
| **Q** / **W** / **E** / **R** | sync other / sync active / centre on nearest landmark / reset |
| **Ctrl+D** / **Ctrl+Shift+D** | next / previous landmark |
| **V** / **N** | point visibility / point names |
| **F2** | transform type |
| **F3** / **F4** | moving / target visibility and grouping |
| **Ctrl+S** / **Ctrl+O** | save / load landmarks |
| **F1** | every binding, for your installed version |
