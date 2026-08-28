"""A first look at what a run produced.

Reads the tables a finished run wrote, prints how they are put together, and
saves one figure showing the things worth checking first: which cells matched,
where the functional plane landed in the volume, and what the genes look like
in space.

    python demo/explore_results.py                        # the demo run
    python demo/explore_results.py --output PATH/OUTPUT   # your own run
    python demo/explore_results.py --plane 2              # a specific plane

Needs a run that matched a functional plane to the FISH volume. A FISH-only run
produces no cross-modal table, so there is nothing here to show for one.

Everything here uses the two small tables plus the functional mean image. The
mask volumes are hundreds of megabytes and nothing below needs them.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tifffile import imread


def find_tables(output_dir: Path, want_plane: str = None):
    """Locate one plane's tables. Returns (merged, intensities, plane, feature)."""
    feat_dir = output_dir / "MERGED" / "aligned_extracted_features"
    tables = sorted(feat_dir.glob("full_table_*_twop_plane*.csv"))
    if not tables:
        raise SystemExit(
            f"No merged table under {feat_dir}.\n"
            "Run the pipeline first, or point --output at a finished OUTPUT folder.")

    planes = sorted({t.stem.split("_twop_plane")[-1] for t in tables})
    if want_plane is None:
        plane = planes[0]
        if len(planes) > 1:
            print(f"Planes in this run: {', '.join(planes)}. Showing plane {plane}; "
                  "pass --plane to pick another.\n")
    elif want_plane in planes:
        plane = want_plane
    else:
        raise SystemExit(f"No table for plane {want_plane}. "
                         f"This run has: {', '.join(planes)}")

    tables = [t for t in tables if t.stem.endswith(f"_twop_plane{plane}")]

    # Several features can be written (plain mean, neuropil-corrected, ...). They
    # share every column except the intensities, so the plain one is the simplest
    # thing to open first.
    table = next((t for t in tables if "_neuropil" not in t.name), tables[0])
    stem = table.stem                       # full_table_{feature}_twop_plane{N}
    feature = stem[len("full_table_"):stem.rindex("_twop_plane")]

    intensities = sorted((output_dir / "HCR" / "extract_intensities")
                         .glob("*_probs_intensities.csv"))
    if not intensities:
        raise SystemExit(f"No intensity table under {output_dir / 'HCR' / 'extract_intensities'}")

    return table, intensities[0], plane, feature


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path,
                    default=Path(__file__).parent / "demo_pre_run" / "JS078_demo" / "OUTPUT",
                    help="a finished OUTPUT folder (default: the demo run)")
    ap.add_argument("--plane", default=None,
                    help="which functional plane to show (default: the first one found)")
    ap.add_argument("--save", type=Path, default=None,
                    help="where to write the figure (default: <output>/explore_results.png)")
    args = ap.parse_args()

    out = args.output
    if not out.exists():
        raise SystemExit(f"{out} does not exist. Run the demo first:\n"
                         "  python demo/fetch_demo_data.py\n"
                         "  python master_pipeline.py --manifest demo/JS078_demo.hjson")

    table_path, inten_path, plane, feature = find_tables(out, args.plane)

    # ---------------------------------------------------------------- the table
    print("=" * 72)
    print("THE MAIN RESULT")
    print("=" * 72)
    print(f"  {table_path}")
    merged = pd.read_csv(table_path)
    print(f"\n  {len(merged)} rows, one per cell in the reference FISH round.")

    genes = [c for c in merged.columns if c.startswith(f"{feature}_round_")]
    print(f"\n  Gene columns ({len(genes)}), named {{feature}}_round_{{R}}_{{gene}}:")
    for g in genes:
        print(f"    {g}")

    n_iou = int(merged["twoP_iou_match"].notna().sum())
    confident = merged["twoP_somaprint_confident"].fillna(False).astype(bool)
    n_soma = int(confident.sum())
    # A FISH-only run writes this table too, with the twoP_ columns present but
    # empty, so their emptiness is what distinguishes the two cases.
    has_functional = n_iou > 0
    if has_functional:
        print(f"\n  Matched to the functional plane, by two independent matchers:")
        print(f"    twoP_iou_match       {n_iou:>6}  cells matched by mask overlap")
        print(f"    twoP_somaprint_match {n_soma:>6}  cells matched confidently by soma-print")
        print(f"    the rest ({len(merged) - n_iou} cells) are elsewhere in the volume,")
        print(f"    outside the field the functional recording covered.")
    else:
        print("\n  The twoP_ columns are empty, so no functional plane was matched.")
        print("  That is what a FISH-only run looks like (--only_hcr, or a manifest")
        print("  with no two_photon_imaging). The gene columns below are unaffected;")
        print("  only the cross-modal panels are skipped.")

    # ------------------------------------------------------------- coordinates
    print("\n" + "=" * 72)
    print("WHERE THE CELLS ARE")
    print("=" * 72)
    print(f"  {inten_path}")
    inten = pd.read_csv(inten_path)
    print(f"\n  {len(inten)} rows: one per cell per channel, so this is the long-format")
    print("  table behind the gene columns above. It also carries the centroids,")
    print("  which the merged table does not, so join on mask_id to place cells.")

    pos = inten.groupby("mask_id")[["X", "Y", "Z"]].first()
    df = merged.merge(pos, left_on="mask_id_main", right_index=True, how="left")
    print(f"\n  df = merged.merge(pos, left_on='mask_id_main', right_index=True)")
    print(f"  -> {int(df.X.notna().sum())}/{len(df)} cells placed")

    # -------------------------------------------------------------- functional
    mean_path = out / "2P" / "cellpose" / f"lowres_meanImg_C0_plane{plane}.tiff"
    mask_path = out / "2P" / "cellpose" / f"lowres_meanImg_C0_plane{plane}_masks.tiff"
    have_2p = has_functional and mean_path.exists() and mask_path.exists()
    if have_2p:
        mean_img = imread(mean_path).astype(float)
        masks_2p = imread(mask_path)
        matched_ids = set(merged["twoP_iou_match"].dropna().astype(int))
        n_cells_2p = int(masks_2p.max())
        print(f"\n  Functional plane {plane}: {n_cells_2p} cells segmented, "
              f"{len(matched_ids)} of them matched.")

    # ------------------------------------------------------------------ figure
    matched = merged["twoP_iou_match"].notna().to_numpy()
    # DAPI is a nuclear stain in every round, so it says nothing about cell type.
    # Of the rest, prefer the channels with signal: a probe that labels almost
    # nothing makes a plot that looks broken rather than sparse.
    candidates = [g for g in genes if "DAPI" not in g.upper()] or genes
    show = sorted(candidates, key=lambda g: merged[g].median(), reverse=True)[:2]

    # The top row is entirely about the functional match, so a FISH-only run drops
    # it rather than printing three empty axes.
    if has_functional:
        fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
        fig.suptitle(f"EASI-PASS results, functional plane {plane}", fontsize=14, y=0.98)
        top, gene_axes, hist_ax = axes[0], axes[1, :2], axes[1, 2]
    else:
        fig, row = plt.subplots(1, 3, figsize=(16, 5))
        fig.suptitle("EASI-PASS results, FISH only", fontsize=14, y=0.98)
        top, gene_axes, hist_ax = None, row[:2], row[2]

    if top is not None:
        # 1. the functional field, coloured by whether each cell matched
        ax = top[0]
        if have_2p:
            lo, hi = np.percentile(mean_img, [1, 99.5])
            ax.imshow(np.clip((mean_img - lo) / max(hi - lo, 1e-9), 0, 1), cmap="gray")
            ids = np.arange(n_cells_2p + 1)
            is_matched = np.isin(ids, list(matched_ids))
            lut = np.zeros((n_cells_2p + 1, 4))
            lut[is_matched] = [0.15, 0.75, 0.35, 0.65]     # green: found a partner
            lut[~is_matched] = [0.90, 0.25, 0.25, 0.65]    # red: did not
            lut[0] = [0, 0, 0, 0]                          # background stays clear
            ax.imshow(lut[masks_2p])
            ax.set_title(f"Functional cells: {len(matched_ids)} matched (green),\n"
                         f"{n_cells_2p - len(matched_ids)} not (red)")
        else:
            ax.text(0.5, 0.5, "functional mean image not found",
                    ha="center", va="center")
        ax.set_xticks([]); ax.set_yticks([])

        # 2. where that plane sits in the FISH volume
        ax = top[1]
        ax.scatter(df.X, df.Y, s=1, c="0.85", linewidths=0,
                   label=f"all FISH cells ({len(df)})")
        ax.scatter(df.X[matched], df.Y[matched], s=3, c="#268c46", linewidths=0,
                   label=f"matched ({int(matched.sum())})")
        ax.set_aspect("equal"); ax.invert_yaxis()
        ax.set_xlabel("X (px)"); ax.set_ylabel("Y (px)")
        ax.set_title("Where the functional plane landed\nin the FISH volume")
        ax.legend(loc="upper right", frameon=False, fontsize=8, markerscale=3)

        # 3. how good the overlaps were
        ax = top[2]
        iou = merged.loc[matched, "twoP_iou"].dropna()
        ax.hist(iou, bins=40, color="#4878a8")
        ax.axvline(iou.median(), color="k", ls="--", lw=1,
                   label=f"median {iou.median():.2f}")
        ax.set_xlabel("twoP_iou"); ax.set_ylabel("cells")
        ax.set_title("Overlap of the matched pairs")
        ax.legend(frameon=False, fontsize=8)

    # genes in space. Every cell is drawn faint and the expressing ones are drawn
    # on top. Colouring all 21,000 by raw intensity does not work: the distribution
    # is so skewed that almost every cell sits at the bottom of the colour map and
    # the plot reads as uniformly dark.
    for ax, gene in zip(gene_axes, show):
        v = df[gene].to_numpy()
        cut = np.nanpercentile(v, 90)
        hi = np.nanpercentile(v, 99.5)
        pos = v >= cut
        ax.scatter(df.X, df.Y, s=1.5, c="0.88", linewidths=0)
        order = np.argsort(np.nan_to_num(v[pos]))
        sc = ax.scatter(df.X.to_numpy()[pos][order], df.Y.to_numpy()[pos][order],
                        c=np.clip(v[pos][order], cut, hi), s=7, cmap="magma_r",
                        linewidths=0, vmin=cut, vmax=hi)
        ax.set_aspect("equal"); ax.invert_yaxis()
        ax.set_xlabel("X (px)"); ax.set_ylabel("Y (px)")
        ax.set_title(f"{gene.replace(f'{feature}_', '')}\ntop 10% of cells, "
                     f"the rest in grey")
        plt.colorbar(sc, ax=ax, fraction=0.046, label="intensity")

    # what one gene looks like across the cells. Most sit near zero with a long
    # tail, which is the shape that decides where a "positive" threshold goes, so
    # plot it rather than a summary statistic. With no functional match there is
    # no matched subset to take, so this is every cell in the reference round.
    ax = hist_ax
    gene = show[0]
    subset = merged.loc[matched, gene] if has_functional else merged[gene]
    vals = subset.dropna()
    ax.hist(vals, bins=45, color="#4878a8")
    ax.axvline(np.percentile(vals, 90), color="crimson", ls="--", lw=1,
               label=f"90th pct = {np.percentile(vals, 90):.2f}")
    ax.set_yscale("log")
    ax.set_xlabel(gene.replace(f"{feature}_", ""))
    if has_functional:
        ax.set_ylabel("matched cells (log)")
        ax.set_title(f"One gene across the {int(matched.sum())} matched cells")
    else:
        ax.set_ylabel("cells (log)")
        ax.set_title(f"One gene across all {len(vals)} cells")
    ax.legend(frameon=False, fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    save_to = args.save or (out / "explore_results.png")
    fig.savefig(save_to, dpi=130)
    print("\n" + "=" * 72)
    print(f"Figure written to {save_to}")
    print("=" * 72)
    print("\nTo carry on from here:")
    print("  import pandas as pd")
    print(f"  df = pd.read_csv(r'{table_path}')")
    if has_functional:
        print("  df[df.twoP_iou_match.notna()]        # cells with a functional partner")
    print(f"  df.nlargest(20, '{show[0]}')" if show else "")


if __name__ == "__main__":
    main()
