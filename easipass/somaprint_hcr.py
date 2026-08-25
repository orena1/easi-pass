"""HCR round-to-round cell matching: best-plane IoU overlap + pinned soma-print repair.

Two-stage hybrid matcher that re-pairs cells across HCR rounds in the shared
HCR{reference} frame:

  Stage 1 -- best-plane IoU overlap (the z-robust workhorse): mutual best partners
    whose best SINGLE-PLANE IoU >= overlap_tau. Best-plane (not 3D volume IoU,
    which is deflated by z-thickness mismatch and loses z-offset partners). Matches
    the well-registered bulk for free.
  Stage 2 -- pinned 2d_plane soma-print (the repair layer): the stage-1 anchors are
    PINNED (vote in every identity round, never gate-evicted) and paper-faithful
    `2d_plane` soma adds matches in the slightly-misregistered patches that overlap
    alone can't reach.

This is a faithful port of the validated dev library plus the best-plane overlap
stage-1 validated on JS082. The core matcher (SPParams/match/iterate_rounds/...)
is byte-for-byte the dev code so the
production path reproduces the notebook numbers; only the pipeline entry point
(`run_for_round`) and the manifest plumbing (`get_params`) are new here.

Validated on JS082 HCR02->HCR01 (centroid-registration warp): stage-1 overlap
50,227 (81.4%) -> pinned 54,437 (88.2%); soma repairs 4,210 cells, median local
shift 10.6um, 0% beyond 60um. See agent memory somaprint_hcr_module /
hcr_centroid_registration_pipeline for lineage.

TRU-FACT faithful (Wang et al. 2026): per-cell soma-print = vectors to m nearest
in-plane neighbours; greedy n-pair match -> 100/(1+dbar); distance penalty
exp(-(x/lam)^2), lam = FOV_span/10; within-plane 2nd-best null; LR gate.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import stats
from scipy.spatial import cKDTree
from sklearn.mixture import GaussianMixture

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(x, **k):
        return x

try:
    from .meta import output_root, rprint            # package import
except ImportError:
    from meta import output_root, rprint             # notebook import

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


# =========================================================================== #
#  manifest config
# =========================================================================== #
# Mirrors the validated notebook cells 3-4 (phase0 OVERLAP_TAU/W_OV/ZR_OV +
# SEARCH_XY_UM/SEARCH_Z_UM/PLANE_BAND). Microns are converted to px per mouse
# from the HCR resolution; lambda is derived from the grid (FOV_span/10).
DEFAULTS = dict(
    enabled=True,
    # ---- anchors: ONE IoU layer, taken from the align_masks pre-pass -------------------
    # A cell anchors when its OWN overlap is good AND the tissue around it also registers.
    # The second test is what makes an anchor trustworthy: a cell can overlap its partner
    # well by luck in a locally mis-registered patch, and pinning that seeds a wrong
    # fingerprint for every neighbour. Both numbers come from the same IoU the pre-pass
    # already computed (iou_at_mask1_z), so there is exactly one IoU definition in play.
    anchor_iou=0.6,          # min iou_at_mask1_z of the cell itself
    anchor_nbhd_iou=0.5,     # min binarized IoU of the surrounding tissue (cell+partner removed)
    anchor_nbhd_radius_um=25.0,   # physical radius of that neighbourhood
    # legacy stage-1 rescan (superseded by the two knobs above; kept for the dev notebooks)
    overlap_tau=0.5,         # min best-single-plane IoU to seed a mutual anchor
    overlap_win_xy=40,       # half-window (px) for the per-cell overlap search
    overlap_win_z=4,         # half-window (planes) for the per-cell overlap search
    # stage 2 -- pinned soma-print
    # TRU-FACT defines TWO fingerprints. '2d_plane' is the one built for a flat focal plane
    # imaged in vivo against an ex vivo stack -- z is discarded because one side has no z.
    # HCR->HCR has z on BOTH sides, which is the paper's own condition for using '3d'
    # (isotropic vectors, continuous z centroid, no plane binning). '2d_plane' with
    # plane_band=2 projects a 5-plane / ~50um slab of dense tissue onto (y,x), which both
    # depresses the true partner's score and raises the null it is measured against.
    fingerprint='2d_plane',
    null_strategy='within_plane',   # '3d' fingerprints want 'dedup': "same rounded plane" is
                                    # not a meaningful near-duplicate test once z is kept
    round2_max_conf_um=None,        # cap on confirmed-neighbour distance in rounds 2+ (see
                                    # score_round_identity). None = paper behaviour, no cap.
    gate='lr',                      # 'local_lr' refits the LR gate per XY block, so a cell is
                                    # judged against tissue sharing its registration quality
                                    # rather than against the whole mosaic (see curate)
    gate_block_um=500.0,            # block size for gate='local_lr'
    search_xy_um=126.0,      # candidate-box half-width (XY), microns
    search_z_um=37.0,        # candidate-box half-height (Z), microns
    plane_band=2,            # 2d_plane fingerprint: neighbours within +/-band planes
    m_a=15,                  # neighbours fingerprinting a moving (A) cell
    m_b=30,                  # neighbours fingerprinting a reference (B) cell
    n_pairs=10,
    n_pairs_r2=10,
    lr_threshold=0.05,
    null_fallback=True,      # a missing within-plane rival must not silently delete the cell
    max_rounds=4,
    terminate_pct=5.0,
    min_confirmed_for_round2=5,
    min_cells_for_gmm=30,
    # mask-outlier filter (port of segmentation._filter_implausible_hcr_masks)
    filter_outliers=True,
)


def get_params(full_manifest: dict) -> dict:
    """Merge DEFAULTS with any params.somaprint_hcr overrides from the manifest."""
    p = dict(DEFAULTS)
    p.update(full_manifest.get('params', {}).get('somaprint_hcr', {}) or {})
    return p


# =========================================================================== #
#  parameters (dev-lib core -- DO NOT diverge from somaprint_tests/somaprint_hcr.py)
# =========================================================================== #
@dataclass
class SPParams:
    fingerprint: str = "3d"       # "3d" isotropic-px; "2d_plane" TRU-FACT per-plane
    plane_band: int = 0           # "2d_plane": neighbours from |round(z)-z| <= band
    m_a: int = 15
    m_b: int = 30
    n_pairs: int = 10
    n_pairs_r2: int = 10
    search_xy_half_px: float = 100.0
    search_z_half: int = 5
    lambda_px: float | None = None
    gate: str = "lr"                  # "lr" population GMM/tail; "margin" per-cell;
                                      # "local_lr" the LR gate refitted per XY block
    gate_block_px: float = 400.0      # block size for gate="local_lr", raw XY px
    lr_threshold: float = 0.05
    null_strategy: str = "baseline"
    r_dedup_px: float = 30.0
    margin_min: float = 5.0
    max_rounds: int = 4
    terminate_pct: float = 5.0
    min_confirmed_for_round2: int = 5
    min_cells_for_gmm: int = 30
    pin_seeds: bool = False
    null_fallback: bool = True    # never let a missing null silently delete a cell (see
                                  # _null_within_plane); set False for the old NaN behaviour
    round2_max_conf_px: float | None = None   # isotropic-px cap on how far away a confirmed
                                  # neighbour may be in rounds 2+. None = no cap (paper
                                  # behaviour, safe on a single FOV). See
                                  # score_round_identity for why a cap matters on a mosaic.


def lambda_from_fov(fov_span_px: float) -> float:
    """TRU-FACT default penalty scale: lam = FOV_span / 10 (px)."""
    return float(fov_span_px) / 10.0


# =========================================================================== #
#  geometry: fingerprints + candidate boxes
# =========================================================================== #
def build_neighbor_vectors(cents, m):
    cents = np.asarray(cents, float)
    n = len(cents)
    D = cents.shape[1] if n else 3
    if n == 0:
        return np.zeros((0, m, D))
    m_eff = max(1, min(m, n - 1))
    tree = cKDTree(cents)
    _, idx = tree.query(cents, k=m_eff + 1)
    if idx.ndim == 1:
        idx = idx[:, None]
    idx = idx[:, 1:]
    vecs = cents[idx] - cents[:, None, :]
    if m_eff < m:
        vecs = np.concatenate([vecs, np.full((n, m - m_eff, D), np.nan)], axis=1)
    return vecs


def build_neighbor_vectors_plane(cents_px, m, band=0):
    """2D PER-PLANE fingerprint (TRU-FACT-faithful): (y,x) vectors to the m nearest
    same-plane (rounded z +/-band) neighbours, nan-padded (n, m, 2)."""
    cents_px = np.asarray(cents_px, float)
    n = len(cents_px)
    if n == 0:
        return np.zeros((0, m, 2))
    pz = cents_px[:, 0].round().astype(int)
    xy = cents_px[:, 1:]
    vecs = np.full((n, m, 2), np.nan)
    for pl in np.unique(pz):
        sel = np.where(np.abs(pz - pl) <= band)[0]
        in_pl = sel[pz[sel] == pl]
        if len(in_pl) == 0 or len(sel) < 2:
            continue
        sub = xy[sel]
        m_eff = max(1, min(m, len(sel) - 1))
        tree = cKDTree(sub)
        _, idx = tree.query(xy[in_pl], k=m_eff + 1)
        if idx.ndim == 1:
            idx = idx[:, None]
        idx = idx[:, 1:]
        vv = sub[idx] - xy[in_pl][:, None, :]
        vecs[in_pl, :m_eff] = vv
    return vecs


def candidates_box(a_px, b_px, xy_half_px, z_half_planes):
    a_px = np.asarray(a_px, float); b_px = np.asarray(b_px, float)
    z_scale = xy_half_px / max(z_half_planes, 1e-9)
    a_s = a_px.copy(); a_s[:, 0] *= z_scale
    b_s = b_px.copy(); b_s[:, 0] *= z_scale
    tree = cKDTree(b_s)
    return tree.query_ball_point(a_s, r=float(xy_half_px), p=np.inf)


def band_candidates(src_px, dst_px, xy_half, band):
    src_px = np.asarray(src_px, float); dst_px = np.asarray(dst_px, float)
    tree = cKDTree(dst_px[:, 1:])
    sz = src_px[:, 0].round().astype(int); dz = dst_px[:, 0].round().astype(int)
    raw = tree.query_ball_point(src_px[:, 1:], r=float(xy_half), p=np.inf)
    out = []
    for i, cl in enumerate(raw):
        cl = np.asarray(cl, dtype=np.int64)
        out.append(cl[np.abs(dz[cl] - sz[i]) <= band] if len(cl) else cl)
    return out


# =========================================================================== #
#  scoring
# =========================================================================== #
def _greedy_match(cost, n):
    """Mean cost of the n cheapest disjoint vector pairs.

    The mean is over the pairs ACTUALLY taken, not over n. The fingerprint arrays are
    nan-padded whenever a cell has fewer than m neighbours in its slab (see
    build_neighbor_vectors_plane: m_eff = min(m, len(sel) - 1)), and those rows arrive here
    as inf. Dividing the truncated sum by n instead would shrink dbar and INFLATE
    100/(1+dbar) by exactly the fraction of pairs that were missing -- a cell with 4 usable
    neighbours would score as if its 4 pairs were 10. That inflation lands precisely where
    cells are sparse (z extremes, tissue edges, thin slabs), manufacturing confident matches
    there and, worse, dragging up the pooled null that every other cell is gated against.
    """
    c = cost.copy()
    n_actual = min(n, c.shape[0], c.shape[1])
    if n_actual == 0:
        return np.inf
    s = 0.0
    taken = 0
    for _ in range(n_actual):
        ia, ib = np.unravel_index(np.argmin(c), c.shape)
        v = c[ia, ib]
        if not np.isfinite(v):
            break
        s += v
        taken += 1
        c[ia, :] = np.inf
        c[:, ib] = np.inf
    if taken == 0:
        return np.inf
    return s / taken


def score_round1_full(a_iso, b_iso, a_vecs, b_vecs, cand_lists, lam, n_pairs):
    a_iso = np.asarray(a_iso, float); b_iso = np.asarray(b_iso, float)
    n = len(a_iso)
    best = np.full(n, np.nan); partner = np.full(n, -1, dtype=np.int64)
    all_scores = [None] * n; all_cands = [None] * n
    for i in tqdm(range(n), desc="score-full", leave=False):
        cand = cand_lists[i]
        if len(cand) < 2:
            continue
        cand = np.asarray(cand)
        va = a_vecs[i]; vb = b_vecs[cand]
        cost = np.linalg.norm(va[None, :, None, :] - vb[:, None, :, :], axis=-1)
        cost = np.where(np.isnan(cost), np.inf, cost)
        dx = np.linalg.norm(b_iso[cand] - a_iso[i], axis=1)
        pen = np.ones(len(cand)) if not lam or lam <= 0 else np.exp(-(dx / lam) ** 2)
        sc = np.array([(100.0 / (1.0 + _greedy_match(c, n_pairs))) * p
                       for c, p in zip(cost, pen)])
        o = np.argsort(sc)[::-1]
        all_scores[i] = sc[o]; all_cands[i] = cand[o]
        best[i] = sc[o[0]]; partner[i] = cand[o[0]]
    return best, partner, all_scores, all_cands


# =========================================================================== #
#  NULL models
# =========================================================================== #
def _null_baseline(all_scores, all_cands, b_iso, p, b_planes=None):
    n = len(all_scores); out = np.full(n, np.nan)
    for i, sc in enumerate(all_scores):
        if sc is not None and len(sc) >= 2:
            out[i] = sc[1]
    return out


def _null_dedup(all_scores, all_cands, b_iso, p, b_planes=None):
    n = len(all_scores); out = np.full(n, np.nan)
    for i in range(n):
        sc, cd = all_scores[i], all_cands[i]
        if sc is None or len(sc) < 2:
            continue
        d_win = np.linalg.norm(b_iso[cd[1:]] - b_iso[cd[0]], axis=1)
        far = sc[1:][d_win > p.r_dedup_px]
        out[i] = float(far[0]) if len(far) else sc[1]
    return out


def _null_median(all_scores, all_cands, b_iso, p, b_planes=None):
    n = len(all_scores); out = np.full(n, np.nan)
    for i, sc in enumerate(all_scores):
        if sc is not None and len(sc) >= 2:
            out[i] = float(np.median(sc[1:]))
    return out


def _null_within_plane(all_scores, all_cands, b_iso, p, b_planes=None):
    """Paper-faithful pairing for fingerprint='2d_plane': best NON-winner candidate in the
    WINNER's own plane (else the runner-up is a cross-plane near-duplicate and the null
    re-inflates). Requires b_planes.

    FALLBACK (p.null_fallback, default on) -- returning NaN here is not "no opinion", it is a
    SILENT DELETION: match() builds `valid = ~isnan(best) & ~isnan(null)`, so a NaN null drops
    the cell before the gate ever sees it. It is never judged and never matched, and nothing in
    the output records that it happened.

    That fires far more often than it looks like it should. Cellpose labels a 3D cell ONCE, at
    its rounded centroid plane, so a plane holds far fewer centroids than it holds visible
    cells; "another candidate in the winner's exact plane" is routinely absent in sparse
    regions, near the z extremes, and wherever the two rounds stitch cells over different z
    spans. Worse, it is blind to match quality -- a textbook-easy pair under a pure rigid shift
    is discarded just as readily as a hard one, because the test is only whether some rival
    happens to share a rounded plane.

    So keep the paper's intent (a rival that is not a near-duplicate of the winner) but never
    throw the cell away: prefer a same-plane rival, else the best rival farther than
    r_dedup_px from the winner, else the runner-up.
    """
    n = len(all_scores); out = np.full(n, np.nan)
    if b_planes is None:
        return out
    b_planes = np.asarray(b_planes)
    b_iso = np.asarray(b_iso, float)
    fallback = bool(getattr(p, "null_fallback", True))
    r_dedup = float(getattr(p, "r_dedup_px", 0.0) or 0.0)
    for i in range(n):
        sc, cd = all_scores[i], all_cands[i]
        if sc is None or len(sc) < 2:
            continue
        same = sc[1:][b_planes[cd[1:]] == b_planes[cd[0]]]
        if len(same):
            out[i] = float(same[0])
        elif fallback:
            if r_dedup > 0:                       # a rival far enough not to be the winner again
                d = np.linalg.norm(b_iso[cd[1:]] - b_iso[cd[0]], axis=1)
                far = sc[1:][d > r_dedup]
                if len(far):
                    out[i] = float(far[0]); continue
            out[i] = float(sc[1])                 # last resort: the runner-up
    return out


NULL_STRATEGIES = {
    "baseline": _null_baseline,
    "dedup": _null_dedup,
    "median": _null_median,
    "within_plane": _null_within_plane,
}


# =========================================================================== #
#  statistical gate
# =========================================================================== #
def _gmm_density(x, gmm):
    means = gmm.means_.ravel(); stds = np.sqrt(gmm.covariances_.ravel()); w = gmm.weights_
    return w[0] * stats.norm.pdf(x, means[0], stds[0]) + w[1] * stats.norm.pdf(x, means[1], stds[1])


def curate(best, null, partner, valid_mask, lr_threshold, min_cells):
    """TRU-FACT's empirical-Bayes gate, fitted over whatever population it is handed.

    Read what the mixture is being ASKED here. The paper's two Gaussians mean "correctly
    matched" and "incorrectly matched", and that reading holds on one field of view where
    every cell was registered equally well. Hand this the same statistic over a stitched
    mosaic whose registration quality varies across the field and the two components stop
    tracking correctness and start tracking GEOGRAPHY: one component is the well-registered
    tissue, the other is the poorly-registered tissue, and the likelihood-ratio cut lands
    between the two REGIONS. Every cell in the weaker region is then written off wholesale,
    however decisive its own margin over its own null happens to be.

    Seeding with IoU anchors sharpens exactly the wrong edge of that. The anchors are, by
    construction, the best-registered cells in the volume; they enter the fit and pull the
    "correct" component to higher scores, which raises the bar that the un-anchored region
    has to clear. The anchors were meant to help the hard cells and instead they raise the
    threshold against them.

    Use curate_local (gate='local_lr') to fit this per spatial block instead.
    """
    keep = np.where(valid_mask)[0]
    if len(keep) < min_cells:
        return {}
    best_v = best[valid_mask]; null_v = null[valid_mask]
    mu, sd = float(np.mean(null_v)), float(np.std(null_v))
    if not np.isfinite(sd) or sd <= 0:
        return {}
    x = best_v.reshape(-1, 1)
    try:
        g2 = GaussianMixture(n_components=2, random_state=0).fit(x)
        g1 = GaussianMixture(n_components=1, random_state=0).fit(x)
        bimodal = bool(g2.bic(x) < g1.bic(x))
    except Exception:
        g2, bimodal = None, False
    if bimodal:
        p_inc = stats.norm.pdf(best, mu, sd)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = p_inc / _gmm_density(best, g2)
            score = np.where(np.isfinite(ratio), ratio, np.inf)
    else:
        score = stats.norm.sf(best, mu, sd)
    return {int(i): int(partner[i]) for i in keep
            if score[i] < lr_threshold and partner[i] >= 0}


def curate_margin(best, null, partner, valid_mask, margin_min):
    out = {}
    for i in np.where(valid_mask)[0]:
        if partner[i] >= 0 and np.isfinite(best[i]) and np.isfinite(null[i]) \
                and (best[i] - null[i]) >= margin_min:
            out[int(i)] = int(partner[i])
    return out


def curate_local(best, null, partner, valid_mask, yx, lr_threshold, min_cells, block_px):
    """The same gate, fitted independently inside square XY blocks of `block_px`.

    A cell should be judged against cells whose registration it shares, not against the whole
    mosaic. Blocking does that with no new parameters to tune beyond the block size: within a
    block the null and the best-score mixture describe one registration regime, so the
    likelihood ratio again means what the paper says it means -- correct versus incorrect --
    rather than "is this cell in the good part of the slide".

    Blocks too small to fit a mixture fall back to being pooled and gated together, so no cell
    is silently dropped for living somewhere sparse.
    """
    yx = np.asarray(yx, float)
    valid_mask = np.asarray(valid_mask, bool)
    if block_px is None or block_px <= 0:
        return curate(best, null, partner, valid_mask, lr_threshold, min_cells)
    by = np.floor(yx[:, 0] / float(block_px)).astype(np.int64)
    bx = np.floor(yx[:, 1] / float(block_px)).astype(np.int64)
    key = (by - by.min()) * (int(bx.max() - bx.min()) + 1) + (bx - bx.min())
    out = {}
    leftover = np.zeros(len(key), bool)
    for k in np.unique(key[valid_mask]):
        m = valid_mask & (key == k)
        if int(m.sum()) < min_cells:
            leftover |= m
            continue
        out.update(curate(best, null, partner, m, lr_threshold, min_cells))
    if leftover.any():
        out.update(curate(best, null, partner, leftover, lr_threshold, min_cells))
    return out


def apply_gate(best, null, partner, valid, p: SPParams, yx=None):
    if p.gate == "margin":
        return curate_margin(best, null, partner, valid, p.margin_min)
    if p.gate == "local_lr" and yx is not None:
        return curate_local(best, null, partner, valid, yx, p.lr_threshold,
                            p.min_cells_for_gmm, p.gate_block_px)
    return curate(best, null, partner, valid, p.lr_threshold, p.min_cells_for_gmm)


# =========================================================================== #
#  iterative neighbour-restriction rounds
# =========================================================================== #
def score_round_identity(a_iso, b_iso, cand_lists, current_matches, lam, n_pairs_r2, min_conf,
                         max_conf_dist=None):
    """Rounds 2+: score each candidate against the IDENTITY-paired vectors to the cell's
    nearest already-confirmed neighbours.

    Read what this actually computes. With u_k = a_iso[a_nb_k] - b_iso[b_nb_k] (confirmed
    neighbour k's residual displacement) and v = a_iso[i] - b_iso[cand] (the displacement the
    candidate implies),

        va - vb = (a_nb - b_nb) - (a_i - b_cand) = u_k - v
        dbar    = mean_k || u_k - v ||

    The neighbour GEOMETRY cancels identically for every candidate. So rounds 2+ are not a
    geometric fingerprint at all -- they are a local displacement-consensus vote, and they are
    only meaningful while the confirmed neighbours are genuinely LOCAL.

    `max_conf_dist` (isotropic px) is what enforces that. Without a cap, a cell in a region
    with no confirmed neighbours still gets k of them: the KD-tree simply reaches across the
    whole field. On a single FOV that is harmless -- the paper's setting. On a stitched mosaic
    it is not: a locally shifted block with no anchors of its own imports the displacement
    consensus of tissue millimetres away, which endorses the wrong candidate, and endorses the
    same wrong candidate coherently for every cell in the block. Cells left with fewer than 5
    confirmed neighbours inside the cap are scored as invalid rather than answered with an
    imported prior; with pin_seeds they keep their anchor, otherwise they go unmatched -- which
    is the honest outcome when there is no local evidence.
    """
    a_iso = np.asarray(a_iso, float); b_iso = np.asarray(b_iso, float)
    n = len(a_iso)
    blank = (np.full(n, np.nan), np.full(n, np.nan),
             np.full(n, -1, dtype=np.int64), np.zeros(n, dtype=bool))
    conf_a = np.array(list(current_matches.keys()), dtype=np.int64)
    conf_b = np.array([current_matches[i] for i in conf_a], dtype=np.int64)
    if len(conf_a) < min_conf:
        return blank
    conf_tree = cKDTree(a_iso[conf_a])
    best = np.full(n, np.nan); second = np.full(n, np.nan)
    partner = np.full(n, -1, dtype=np.int64); valid = np.zeros(n, dtype=bool)
    kq = min(n_pairs_r2 + 2, len(conf_a))
    cap = float(max_conf_dist) if max_conf_dist else np.inf
    for i in range(n):
        d, j = conf_tree.query(a_iso[i], k=kq)
        d = np.atleast_1d(d); j = np.atleast_1d(j)
        j = j[(d > 1e-6) & (d <= cap)][:n_pairs_r2]
        if len(j) < 5:
            continue
        a_nb, b_nb = conf_a[j], conf_b[j]
        cand = cand_lists[i]
        if len(cand) < 2:
            continue
        cand = np.asarray(cand)
        va = a_iso[a_nb] - a_iso[i]
        vb = b_iso[b_nb][None, :, :] - b_iso[cand][:, None, :]
        dbar = np.linalg.norm(va[None, :, :] - vb, axis=2).mean(axis=1)
        dx = np.linalg.norm(b_iso[cand] - a_iso[i], axis=1)
        pen = np.ones(len(cand)) if not lam or lam <= 0 else np.exp(-(dx / lam) ** 2)
        scores = (100.0 / (1.0 + dbar)) * pen
        order = np.argsort(scores)[::-1]
        best[i] = scores[order[0]]
        second[i] = scores[order[1]] if len(order) > 1 else np.nan
        partner[i] = cand[order[0]]; valid[i] = True
    return best, second, partner, valid


def iterate_rounds(a_iso, b_iso, cand_lists, round1_conf, p: SPParams, pinned=None, yx=None):
    pinned = pinned or {}
    current = dict(round1_conf)
    history = [len(current)]
    for _ in range(p.max_rounds):
        if len(current) < p.min_confirmed_for_round2:
            break
        best, second, partner, valid = score_round_identity(
            a_iso, b_iso, cand_lists, current, p.lambda_px, p.n_pairs_r2,
            p.min_confirmed_for_round2, max_conf_dist=p.round2_max_conf_px)
        if int(valid.sum()) < p.min_cells_for_gmm:
            break
        new = apply_gate(best, second, partner, valid, p, yx=yx)
        if pinned:
            new = {**new, **pinned}
        prev = len(current)
        delta = 100.0 * abs(len(new) - prev) / max(prev, 1)
        current = new
        history.append(len(current))
        if delta < p.terminate_pct:
            break
    return current, history


# =========================================================================== #
#  top-level matcher (one full run; pluggable null + optional IoU-anchor seed)
# =========================================================================== #
def match(a_iso, a_px, b_iso, b_px, p: SPParams, cand_lists=None, seed_matches=None):
    """Run the full pipeline once. a_*/b_* are (z,y,x): *_iso isotropic px, *_px raw px.
    seed_matches {a_idx->b_idx}: confident anchors. With p.pin_seeds they are HARD
    anchors (never evicted); soma only ADDS to them. Returns a result dict."""
    if p.fingerprint == "2d_plane":
        a_vecs = build_neighbor_vectors_plane(a_px, p.m_a, p.plane_band)
        b_vecs = build_neighbor_vectors_plane(b_px, p.m_b, p.plane_band)
    else:
        a_vecs = build_neighbor_vectors(a_iso, p.m_a)
        b_vecs = build_neighbor_vectors(b_iso, p.m_b)
    if cand_lists is None:
        cand_lists = candidates_box(a_px, b_px, p.search_xy_half_px, p.search_z_half)

    best, partner, all_scores, all_cands = score_round1_full(
        a_iso, b_iso, a_vecs, b_vecs, cand_lists, p.lambda_px, p.n_pairs)
    b_planes = np.asarray(b_px, float)[:, 0].round().astype(int)
    null = NULL_STRATEGIES[p.null_strategy](all_scores, all_cands, np.asarray(b_iso, float), p, b_planes)
    valid = ~np.isnan(best) & ~np.isnan(null)
    yx = np.asarray(a_px, float)[:, 1:]
    conf1 = apply_gate(best, null, partner, valid, p, yx=yx)

    start = dict(seed_matches) if seed_matches else {}
    start.update(conf1)
    pinned = dict(seed_matches) if (seed_matches and p.pin_seeds) else None
    final, history = iterate_rounds(a_iso, b_iso, cand_lists, start, p, pinned=pinned, yx=yx)
    return dict(best=best, partner=partner, all_scores=all_scores, all_cands=all_cands,
                null=null, valid=valid, conf1=conf1, seed=start, final=final,
                history=history, cand_lists=cand_lists)


# =========================================================================== #
#  mask -> centroids helpers
# =========================================================================== #
def filter_outlier_masks(masks, vmin=0.1, vmax=10.0, bbox=3.0, min_n=10, relabel=False):
    """Port of segmentation._filter_implausible_hcr_masks: drop labels with vol
    <vmin*median or >vmax*median, or xy-bbox >bbox*median. relabel=False (DEFAULT)
    keeps ORIGINAL labels (REQUIRED for CSV alignment). Returns (filtered, info)."""
    from scipy.ndimage import find_objects
    from skimage.segmentation import relabel_sequential
    masks = np.asarray(masks)
    vols = np.bincount(masks.ravel())
    present = np.where(vols[1:] > 0)[0] + 1
    if masks.max() == 0 or len(present) < min_n:
        return masks, dict(total=int(len(present)), dropped=0)
    slices = find_objects(masks)
    lv = vols[present].astype(float)
    bext = np.array([max(slices[l - 1][1].stop - slices[l - 1][1].start,
                         slices[l - 1][2].stop - slices[l - 1][2].start)
                     if slices[l - 1] is not None else 0 for l in present])
    mv, mb = float(np.median(lv)), float(np.median(bext))
    tiny = lv < vmin * mv; huge = lv > vmax * mv; wide = bext > bbox * mb
    drop = tiny | huge | wide
    lut = np.arange(len(vols), dtype=masks.dtype)
    lut[present[drop]] = 0
    out = lut[masks]
    if relabel:
        out, _, _ = relabel_sequential(out)
    return out.astype(masks.dtype), dict(
        total=int(len(present)), tiny=int(tiny.sum()), huge=int(huge.sum()),
        wide=int(wide.sum()), dropped=int(drop.sum()), med_vol=mv, med_bbox=mb)


def centroids_px(masks):
    """Per-label (z,y,x) centroid via bincount. Returns (ids, cents_zyx)."""
    masks = np.asarray(masks)
    idx = np.flatnonzero(masks)
    if idx.size == 0:
        return np.empty(0, int), np.empty((0, 3))
    lab = masks.reshape(-1)[idx]
    zz, yy, xx = np.unravel_index(idx, masks.shape)
    nlab = int(lab.max()) + 1
    cnt = np.bincount(lab, minlength=nlab).astype(float)
    cz = np.bincount(lab, zz, minlength=nlab)
    cy = np.bincount(lab, yy, minlength=nlab)
    cx = np.bincount(lab, xx, minlength=nlab)
    keep = cnt > 0; keep[0] = False
    ids = np.flatnonzero(keep)
    return ids, np.column_stack([cz[ids] / cnt[ids], cy[ids] / cnt[ids], cx[ids] / cnt[ids]])


def to_isotropic(cents_zyx, z_scale):
    """(z,y,x) px -> (z*z_scale, y, x) isotropic px for the 3D fingerprint."""
    c = np.asarray(cents_zyx, float).copy()
    c[:, 0] *= z_scale
    return c


# =========================================================================== #
#  stage 1: best-plane IoU overlap  (port of phase0 _bp_* / stage1_overlap)
# =========================================================================== #
def _bp_iou_planes(A, B):
    """Best single-plane IoU between two boolean sub-volumes (max over z)."""
    return max(((A[k] & B[k]).sum() / u
                for k in range(A.shape[0]) for u in [(A[k] | B[k]).sum()] if u),
               default=0.0)


def _bp_best_partner(a_masks, b_masks, lab, z, y, x, W, zr):
    """Best-plane-IoU partner of A-cell `lab` among B labels in its local window."""
    zs = slice(max(0, z - zr), z + zr + 1)
    ys = slice(max(0, y - W), y + W)
    xs = slice(max(0, x - W), x + W)
    A = (a_masks[zs, ys, xs] == lab); Bw = b_masks[zs, ys, xs]
    cand = np.unique(Bw[A]); cand = cand[cand > 0]
    best_bl, best_io = 0, 0.0
    for bl in cand.tolist():
        io = _bp_iou_planes(A, Bw == bl)
        if io > best_io:
            best_io, best_bl = io, int(bl)
    return best_bl, best_io


def sphere_kernel(radius_um, res_xyz, box=True):
    """Per-axis half-extents for a `radius_um` neighbourhood, and an optional stencil.

    The half-extent on each axis is still derived in PHYSICAL units (so 25um means 25um in
    z as well as xy, despite z voxels being ~8x taller), but with box=True the region is the
    voxel box those extents define rather than an inscribed sphere. The box is the default
    because it lets neighborhood_iou skip a boolean AND over every voxel of every cell; the
    only cells it treats differently are the box corners (up to ~1.7x the radius away), which
    is not a meaningful distinction for "does the tissue around this cell register".

    Returns (kernel_or_None, (rz, ry, rx)). res_xyz is (x,y,z) um/px.
    """
    rx = max(1, int(np.floor(radius_um / float(res_xyz[0]))))
    ry = max(1, int(np.floor(radius_um / float(res_xyz[1]))))
    rz = max(0, int(np.floor(radius_um / float(res_xyz[2]))))
    if box:
        return None, (rz, ry, rx)
    zz, yy, xx = np.ogrid[-rz:rz + 1, -ry:ry + 1, -rx:rx + 1]
    d2 = ((zz * float(res_xyz[2])) ** 2 + (yy * float(res_xyz[1])) ** 2
          + (xx * float(res_xyz[0])) ** 2)
    return (d2 <= radius_um ** 2), (rz, ry, rx)


def neighborhood_iou(a_masks, b_masks, a_lab, b_lab, zc, yc, xc, kern, r):
    """Binarized IoU of the tissue AROUND one cell, with that cell AND its partner deleted.

    Both volumes are reduced to 'is there any nucleus here', the pair's own voxels are
    dropped from BOTH sides (so they enter neither the intersection nor the union), and the
    IoU of what is left inside the sphere is returned. This asks a question the per-cell IoU
    cannot: does the surrounding tissue line up? A well-overlapping cell stranded in a
    mis-registered patch scores low here and is refused as an anchor.

    Dropping the partner as well as the cell is what makes it unbiased -- removing the cell
    from the moving side only would leave its partner's voxels on the reference side, adding
    pure union with no intersection and depressing every score.
    """
    rz, ry, rx = r
    Z, Y, X = a_masks.shape
    z0, z1 = max(0, zc - rz), min(Z, zc + rz + 1)
    y0, y1 = max(0, yc - ry), min(Y, yc + ry + 1)
    x0, x1 = max(0, xc - rx), min(X, xc + rx + 1)
    if z1 <= z0 or y1 <= y0 or x1 <= x0:
        return 0.0
    A = a_masks[z0:z1, y0:y1, x0:x1]
    B = b_masks[z0:z1, y0:y1, x0:x1]
    keep = (A != a_lab) & (B != b_lab)          # the pair contributes nothing, either side
    if kern is not None:                        # sphere mode; box mode (default) skips this
        keep &= kern[z0 - (zc - rz): kern.shape[0] - ((zc + rz + 1) - z1),
                     y0 - (yc - ry): kern.shape[1] - ((yc + ry + 1) - y1),
                     x0 - (xc - rx): kern.shape[2] - ((xc + rx + 1) - x1)]
    fa = (A > 0) & keep
    fb = (B > 0) & keep
    union = int(np.count_nonzero(fa | fb))
    if not union:
        return 0.0
    return float(np.count_nonzero(fa & fb)) / union


def anchors_from_iou(a_masks, b_masks, a_ids, a_zyx, b_lab2idx, iou_picks, res_xyz,
                     tau_cell, tau_nbhd, radius_um):
    """THE anchor set: one IoU layer, filtered twice.

    `iou_picks` is the align_masks pre-pass result, {mov_label: (ref_label, iou_at_mask1_z)},
    already 1:1 (is_best_match). A cell anchors when its own IoU >= tau_cell AND the
    binarized neighbourhood IoU (cell + partner removed) >= tau_nbhd.

    Returns ({a_index -> b_index}, nbhd_iou array aligned to a_ids, n_failed_cell,
    n_failed_nbhd) so the caller can report why cells were refused.
    """
    kern, r = sphere_kernel(radius_um, res_xyz)
    n = len(a_ids)
    nbhd = np.full(n, np.nan)
    anchors = {}
    n_fail_cell = n_fail_nbhd = 0
    for i in tqdm(range(n), desc="anchors", leave=False):
        pick = iou_picks.get(int(a_ids[i]))
        if pick is None:
            continue                                  # no 1:1 IoU partner -> soma-print's job
        ref_lbl, cell_iou = int(pick[0]), float(pick[1])
        if not (cell_iou >= tau_cell):
            n_fail_cell += 1
            continue
        z, y, x = (int(v) for v in a_zyx[i])
        nbhd[i] = neighborhood_iou(a_masks, b_masks, int(a_ids[i]), ref_lbl, z, y, x, kern, r)
        if nbhd[i] < tau_nbhd:
            n_fail_nbhd += 1
            continue
        bj = b_lab2idx.get(ref_lbl)
        if bj is not None:
            anchors[i] = bj
    return anchors, nbhd, n_fail_cell, n_fail_nbhd


def stage1_overlap(a_masks, b_masks, a_ids, a_zyx, b_lab2idx, tau, W, zr):
    """Mutual best-plane-IoU anchors: {a_index -> b_index} where A and B are each
    other's best overlap partner and that IoU >= tau. Index space matches centroids_px."""
    n = len(a_ids)
    a_bl = np.zeros(n, np.int64); a_io = np.zeros(n)
    for i in tqdm(range(n), desc="stage1-overlap", leave=False):
        z, y, x = a_zyx[i].astype(int)
        a_bl[i], a_io[i] = _bp_best_partner(a_masks, b_masks, int(a_ids[i]), z, y, x, W, zr)
    best_a_for_b = {}
    for i in range(n):
        bl = int(a_bl[i])
        if bl > 0 and a_io[i] > best_a_for_b.get(bl, (-1.0, -1))[0]:
            best_a_for_b[bl] = (a_io[i], i)
    s1 = {}
    for i in range(n):
        bl = int(a_bl[i])
        if bl > 0 and a_io[i] >= tau and best_a_for_b[bl][1] == i:
            bj = b_lab2idx.get(bl)
            if bj is not None:
                s1[i] = bj
    return s1, a_io


# =========================================================================== #
#  pipeline entry point
# =========================================================================== #
def run_for_round(mov_masks_path, ref_masks_path, res_xyz, params: dict,
                  round_label: str = "", stats: dict = None, iou_picks: dict = None) -> dict:
    """Two-stage match of one moving HCR round's masks (already warped into the
    reference frame) against the reference round's masks.

    Both volumes must share the reference grid (cellpose_aligned/*). `res_xyz` is
    the HCR (x,y,z) resolution in microns (resolve_hcr_resolution order). `params`
    comes from get_params().

    Returns a per-moving-label dict
        {mov_label: (ref_label, best_score, second_score, confident, source)}
    where source is 'overlap' (stage-1 IoU anchor) or 'somaprint' (stage-2 repair).
    best/second are the soma scores (NaN for overlap anchors that never went through
    soma scoring). Returns {} when inputs are missing/empty.

    If a `stats` dict is passed it is populated with totals for the caller's summary:
    {n_mov, n_ref, n_overlap, n_repair, n_matched} (left empty on an early skip).
    """
    import tifffile
    mov_masks_path = Path(mov_masks_path); ref_masks_path = Path(ref_masks_path)
    if not mov_masks_path.exists() or not ref_masks_path.exists():
        missing = mov_masks_path if not mov_masks_path.exists() else ref_masks_path
        rprint(f"  [yellow][somaprint_hcr] {round_label}: missing masks {missing}; skipping[/yellow]")
        return {}

    t0 = time.time()
    a_masks = tifffile.imread(str(mov_masks_path)).astype(np.int32)
    b_masks = tifffile.imread(str(ref_masks_path)).astype(np.int32)
    if a_masks.shape != b_masks.shape:
        rprint(f"  [yellow][somaprint_hcr] {round_label}: shape mismatch "
               f"{a_masks.shape} vs {b_masks.shape}; skipping[/yellow]")
        return {}

    if params.get('filter_outliers', True):
        a_masks, _ai = filter_outlier_masks(a_masks)
        b_masks, _bi = filter_outlier_masks(b_masks)

    a_ids, a_zyx = centroids_px(a_masks)
    b_ids, b_zyx = centroids_px(b_masks)
    if len(a_ids) == 0 or len(b_ids) == 0:
        rprint(f"  [yellow][somaprint_hcr] {round_label}: empty masks "
               f"({len(a_ids)} mov / {len(b_ids)} ref); skipping[/yellow]")
        return {}

    res_xyz = np.asarray(res_xyz, float)
    z_scale = float(res_xyz[2] / res_xyz[0])
    a_iso = to_isotropic(a_zyx, z_scale); b_iso = to_isotropic(b_zyx, z_scale)
    b_lab2idx = {int(l): j for j, l in enumerate(b_ids)}

    grid = np.array(b_masks.shape)
    lam = lambda_from_fov(float(max(grid[1:])))
    search_xy_px = float(params['search_xy_um']) / float(res_xyz[0])
    search_z_pl = max(1, int(round(float(params['search_z_um']) / float(res_xyz[2]))))

    n = len(a_ids)
    rprint(f"  [somaprint_hcr] {round_label}: {n} mov / {len(b_ids)} ref cells "
           f"(z_scale {z_scale:.2f}, lam {lam:.0f}), stage 1 ...")

    # ---- anchors: the single IoU layer (pre-pass IoU + neighbourhood agreement) ----
    if iou_picks is None:
        # No pre-pass handed in (dev notebooks): fall back to the legacy self-contained rescan.
        s1, _a_io = stage1_overlap(
            a_masks, b_masks, a_ids, a_zyx, b_lab2idx,
            tau=float(params['overlap_tau']),
            W=int(params['overlap_win_xy']), zr=int(params['overlap_win_z']))
        rprint(f"  [somaprint_hcr] {round_label}: legacy stage-1 overlap "
               f"{len(s1)} ({100 * len(s1) / n:.1f}%); soma-print ...")
    else:
        tau_c = float(params['anchor_iou']); tau_n = float(params['anchor_nbhd_iou'])
        rad = float(params['anchor_nbhd_radius_um'])
        s1, nbhd, n_fc, n_fn = anchors_from_iou(
            a_masks, b_masks, a_ids, a_zyx, b_lab2idx, iou_picks, res_xyz,
            tau_cell=tau_c, tau_nbhd=tau_n, radius_um=rad)
        n_no_pick = sum(1 for lab in a_ids if int(lab) not in iou_picks)
        rprint(f"  [somaprint_hcr] {round_label}: anchors {len(s1)} ({100 * len(s1) / n:.1f}%) "
               f"= IoU>={tau_c} & nbhd>={tau_n} @{rad:.0f}um "
               f"[dim](refused: {n_fc} low IoU, {n_fn} low neighbourhood, "
               f"{n_no_pick} no 1:1 partner)[/dim]; soma-print ...")

    # ---- stage 2: pinned 2d_plane soma-print ----
    r2_cap_um = params.get('round2_max_conf_um')
    P = SPParams(
        fingerprint=str(params.get('fingerprint', '2d_plane')),
        plane_band=int(params['plane_band']),
        null_strategy=str(params.get('null_strategy', 'within_plane')),
        gate=str(params.get('gate', 'lr')),
        gate_block_px=float(params.get('gate_block_um', 500.0)) / float(res_xyz[0]),
        round2_max_conf_px=(float(r2_cap_um) / float(res_xyz[0])) if r2_cap_um else None,
        lr_threshold=float(params['lr_threshold']),
        m_a=int(params['m_a']), m_b=int(params['m_b']),
        n_pairs=int(params['n_pairs']), n_pairs_r2=int(params['n_pairs_r2']),
        search_xy_half_px=search_xy_px, search_z_half=search_z_pl, lambda_px=lam,
        max_rounds=int(params['max_rounds']), terminate_pct=float(params['terminate_pct']),
        min_confirmed_for_round2=int(params['min_confirmed_for_round2']),
        min_cells_for_gmm=int(params['min_cells_for_gmm']),
        null_fallback=bool(params['null_fallback']), pin_seeds=True)
    R = match(a_iso, a_zyx, b_iso, b_zyx, P, seed_matches=s1)
    final = R['final']; best = R['best']; null = R['null']

    out = {}
    n_repair = 0
    for ia, ib in final.items():
        mov_lbl = int(a_ids[ia]); ref_lbl = int(b_ids[ib])
        is_overlap = ia in s1
        if is_overlap:
            source = 'overlap'; bs = np.nan; ss = np.nan
        else:
            source = 'somaprint'; n_repair += 1
            bs = float(best[ia]) if np.isfinite(best[ia]) else np.nan
            ss = float(null[ia]) if np.isfinite(null[ia]) else np.nan
        out[mov_lbl] = (ref_lbl, bs, ss, True, source)

    rprint(f"  [somaprint_hcr] {round_label}: matched {len(out)}/{n} "
           f"({100 * len(out) / n:.1f}%) = {len(s1)} overlap + {n_repair} soma-repair "
           f"({time.time() - t0:.1f}s)")
    if stats is not None:
        stats.update(n_mov=int(n), n_ref=int(len(b_ids)), n_overlap=int(len(s1)),
                     n_repair=int(n_repair), n_matched=int(len(out)))
    return out
