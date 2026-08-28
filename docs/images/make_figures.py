"""Regenerate the figures used in README.md and docs/.

    python docs/images/make_figures.py

`overview.png` is a schematic and needs nothing. The other three are rendered from a
completed demo run, so run the demo first (see demo/README.md); point --qc elsewhere to
build them from a different run.

The colour scheme follows the paper's Figure 1: green for the functional side, purple for
the molecular side, orange for the cross-modal step.

No IoU numbers are burned into these captions. The value the console reports as
`Final: IoU` is computed on a different basis than whole-overlay mask IoU, and showing
them together would imply they are the same quantity.
"""
import argparse
import os

import numpy as np
import tifffile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_QC = os.path.join(REPO, "demo", "demo_pre_run", "JS078_demo", "OUTPUT",
                          "2P", "registered", "QualityCheck")
DEFAULT_EXPLORE = os.path.join(REPO, "demo", "demo_pre_run", "JS078_demo",
                               "OUTPUT", "explore_results.png")

GREEN_FILL, GREEN_LINE = "#7ced97", "#1f7d26"
PURPLE_FILL, PURPLE_LINE = "#cbabef", "#5b2785"
ORANGE_FILL, ORANGE_LINE = "#fbc191", "#c25c07"
BLUE_FILL, BLUE_LINE = "#b6dcf3", "#1a6394"
INK = "#1f1f1f"

MASK_GREEN = (0.15, 0.90, 0.25)
MASK_MAGENTA = (0.90, 0.20, 0.85)

CROP_Y, CROP_X, CROP_SZ = 700, 700, 380


def overlay_rgb(stack):
    """Channel 0 is HCR FISH masks, channel 1 functional masks. Both binary."""
    fish = stack[0].astype(bool)
    func = stack[1].astype(bool)
    im = np.zeros(fish.shape + (3,), np.float32)
    for c in range(3):
        im[..., c] += fish * MASK_MAGENTA[c]
        im[..., c] += func * MASK_GREEN[c]
    return np.clip(im, 0, 1)


def crop(stack):
    return overlay_rgb(stack)[CROP_Y:CROP_Y + CROP_SZ, CROP_X:CROP_X + CROP_SZ]


def make_overview(dest):
    """The conceptual overview, a simplified form of the paper's Figure 1A."""
    fig, ax = plt.subplots(figsize=(10, 2.7))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 34)
    ax.axis("off")

    def box(x, y, w, h, fill, line, title, sub, tsize=11.5):
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                                    boxstyle="round,pad=0.3,rounding_size=1.3",
                                    facecolor=fill, edgecolor=line, linewidth=2.0))
        ax.text(x + w / 2, y + h * 0.74, title, ha="center", va="center",
                fontsize=tsize, fontweight="bold", color=line)
        ax.text(x + w / 2, y + h * 0.46, sub, ha="center", va="center",
                fontsize=8.6, color=INK, linespacing=1.45)

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                     mutation_scale=17, linewidth=1.9,
                                     color="#4d4d4d", shrinkA=0, shrinkB=0))

    box(3, 18, 28, 14, GREEN_FILL, GREEN_LINE,
        "Two-photon functional imaging", "one mean image per plane")
    box(3, 2, 28, 14, PURPLE_FILL, PURPLE_LINE,
        "Multi-round EASI-FISH", "or your preferred FISH method\none volume per round")

    for dy in [0.0, 0.85, 1.7]:
        ax.add_patch(Polygon([[15.4, 19.7 + dy], [19.6, 19.7 + dy],
                              [18.4, 20.6 + dy], [14.2, 20.6 + dy]],
                             closed=True, facecolor="#ffffff",
                             edgecolor=GREEN_LINE, linewidth=1.1))

    cx, cy, s, d = 16.2, 2.9, 2.2, 0.85
    ax.add_patch(Polygon([[cx, cy], [cx + s, cy], [cx + s, cy + s], [cx, cy + s]],
                         closed=True, facecolor="#ffffff",
                         edgecolor=PURPLE_LINE, linewidth=1.1))
    for a, b in [((cx, cy + s), (cx + d, cy + s + d)),
                 ((cx + s, cy + s), (cx + s + d, cy + s + d)),
                 ((cx + s, cy), (cx + s + d, cy + d))]:
        ax.plot([a[0], b[0]], [a[1], b[1]], color=PURPLE_LINE, linewidth=1.1)
    ax.plot([cx + d, cx + s + d, cx + s + d], [cy + s + d, cy + s + d, cy + d],
            color=PURPLE_LINE, linewidth=1.1)

    box(42, 8, 25, 18, ORANGE_FILL, ORANGE_LINE, "EASI-PASS",
        "segment  ·  register  ·  match", tsize=13)
    for dx, fc, ec in [(-1.6, GREEN_FILL, GREEN_LINE),
                       (1.6, PURPLE_FILL, PURPLE_LINE)]:
        ax.add_patch(Circle((54.5 + dx, 12.2), 2.3, facecolor=fc, edgecolor=ec,
                            linewidth=1.4, alpha=0.72))

    box(76, 10, 22, 14, BLUE_FILL, BLUE_LINE,
        "One row per cell", "activity paired with genes")
    gx, gy, cw, rh = 81.5, 12.2, 3.5, 0.75
    for i in range(3):
        ax.plot([gx, gx + cw * 3], [gy + i * rh] * 2, color=BLUE_LINE, linewidth=0.9)
    for j in range(4):
        ax.plot([gx + j * cw] * 2, [gy, gy + rh * 2], color=BLUE_LINE, linewidth=0.9)

    arrow(32.0, 24.0, 37.0, 19.6)
    arrow(32.0, 8.5, 37.0, 12.9)
    ax.plot([37.0, 37.0], [12.9, 19.6], color="#4d4d4d", linewidth=1.9,
            solid_capstyle="round")
    arrow(37.0, 16.3, 41.4, 16.3)
    arrow(67.7, 16.3, 75.4, 16.3)

    fig.tight_layout(pad=0.2)
    fig.savefig(dest, dpi=100, facecolor="white")
    plt.close(fig)


def make_cascade(qc, dest):
    stages = [("plane0_stage_baseline.tiff", "landmarks only"),
              ("plane0_stage_global.tiff", "+ rigid search"),
              ("plane0_stage_affine.tiff", "+ global affine"),
              ("plane0_stage_tile_300.tiff", "+ 300 px tiles"),
              ("plane0_stage_tile_100.tiff", "+ 100 px tiles"),
              ("plane0_stage_tile_50.tiff", "+ 50 px tiles")]
    fig, axes = plt.subplots(1, len(stages), figsize=(9.2, 1.75))
    for ax, (fn, label) in zip(axes, stages):
        ax.imshow(crop(tifffile.imread(os.path.join(qc, fn))), interpolation="nearest")
        ax.set_title(label, fontsize=7.5)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout(pad=0.35)
    fig.savefig(dest, dpi=100, facecolor="white")
    plt.close(fig)


def make_explore(src, dest):
    """Top-left two panels of the figure demo/explore_results.py writes."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w, h = im.size
    im = im.crop((int(0.005 * w), int(0.075 * h), int(0.684 * w), int(0.535 * h)))
    target = 900
    im = im.resize((target, int(im.size[1] * target / im.size[0])), Image.LANCZOS)
    im = im.quantize(colors=128, method=Image.MEDIANCUT,
                     dither=Image.FLOYDSTEINBERG)
    im.save(dest, optimize=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qc", default=DEFAULT_QC,
                   help="QualityCheck folder of a completed run")
    p.add_argument("--explore", default=DEFAULT_EXPLORE,
                   help="explore_results.png of a completed run")
    args = p.parse_args()

    make_overview(os.path.join(HERE, "overview.png"))
    print("overview.png")

    if os.path.isdir(args.qc):
        make_cascade(args.qc, os.path.join(HERE, "cascade_stages.png"))
        print("cascade_stages.png")
    else:
        print("skipped cascade: no QualityCheck folder at %s" % args.qc)

    if os.path.isfile(args.explore):
        make_explore(args.explore, os.path.join(HERE, "explore_results.png"))
        print("explore_results.png")
    else:
        print("skipped explore_results: not found at %s" % args.explore)


if __name__ == "__main__":
    main()
