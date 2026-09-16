"""
hcr_centroid_registration.py -- in-pipeline HCR round-to-round registration driven by
cellpose nucleus CENTROIDS (no notebook farming).

Two stages, both reusing existing engines (no new registration math):

  GLOBAL  -- a cap-free 2D-context centroid affine, ported verbatim from the validated
             diagnostic `centroid_global_batched` (HCR_global_centroid_diagnostic.ipynb /
             gen_hcr_global_centroid_diagnostic.py). The bigstream no-prior feature-point
             matcher is deliberately NOT used here: the diagnostic showed it falls into the
             identity/local-minimum trap at large inter-round offset. The 2D-um-context
             matcher + cv2 RANSAC is the robust winner across cortex + PBN.

  LOCAL   -- bigstream's distributed_piecewise_alignment_pipeline with the cellpose
             centroids INJECTED as fix_spots_global / mov_spots_global and the global affine
             supplied as the per-block prior (static_transform_list). Ported from
             _profile_local_reg.coverage_sweep, including the adaptive_cc_contexts edge
             monkeypatch and the loosened spot/match floors.

Outputs land in the EXISTING registrations/ layout so registration_apply(),
verify_rounds() and align_masks_to_reference() need no changes:

    OUTPUT/HCR/registrations/HCR{N}_to_HCR{ref}/<global_tag>/<local_tag>/
        _affine.mat     (4x4 fix->mov physical affine; np.savetxt)
        deform.zarr     (local deformation field)
        overlay_warped.tiff     (QC: 2-channel ImageJ composite, warped mov + fix, at lowres)

`<local_tag>` always contains 'bs{Y}x{X}x{Z}' so _load_round_transform's blocksize regex
parses it. The selected_registrations entry written into the manifest is
'<global_tag>/<local_tag>'.

EVERY candidate is persisted, not just the scored winner: each swept global radius gets its own
<global_tag>/_affine.mat plus a composite under registrations/composites/global/, and each local
blocksize gets its own <global_tag>/<local_tag>/ plus one under composites/local/. The metrics
SUGGEST a row; nothing is deleted for losing. This matters because the coarse metrics disagree in
practice -- MI, mutual-inlier count and residual can each favour a different radius -- so the
person looking at the overlays needs all of them on disk to compare.

Public entry: run_hcr_centroid_registration(...) -> per-round ranked results.
Selection + manifest write-back is handled by register_rounds() in registrations.py. The one
exception is the COARSE pick, which must be settled mid-run (the expensive deform is seeded by
that affine): the caller passes a `choose_global` callback that is invoked once the coarse
composites are written. Leave it None for unattended runs -> the suggestion is taken.

"""
import time
import shutil
import hashlib
import contextlib
import numpy as np
from pathlib import Path
from tifffile import imread as tif_imread, imwrite as tif_imwrite

try:
    from .meta import (rprint, output_root, get_hcr_to_hcr_registration_config,
                       get_round_folder_name, parse_json)
    from .registrations_utils import resolve_hcr_resolution
    from .bigstream_functions import get_registration_score
except ImportError:  # running in a notebook / as a flat module
    from meta import (rprint, output_root, get_hcr_to_hcr_registration_config,
                       get_round_folder_name, parse_json)
    from registrations_utils import resolve_hcr_resolution
    from bigstream_functions import get_registration_score


# --------------------------------------------------------------------------- #
#  CONFIG  (hjson params -> typed config, with defaults)
# --------------------------------------------------------------------------- #
# Defaults chosen from the diagnostic's consistency table (60um global is near-universal)
# and the local threshold-sweep findings (loosened floors 8/4, cc=(12,12,2), mt=0.3).
_GLOBAL_DEFAULTS = dict(
    method="centroid",
    context_radius_um=[40.0, 60.0, 80.0],  # searched (downsampled, cheap); best auto-picked by select_metric
    # Residual in-plane rotation search. 0 = OFF, which is the shipped behaviour and leaves every
    # existing sample bit-identical. _contexts has no rotation invariance, and the QC rotation
    # test only tries 0/90/180/270, so a hand-rotation left a few degrees off degrades silently
    # and dies somewhere past ~5-8 degrees (PS393_1L R3: 8 degrees out, 556 mutual inliers at 0,
    # 1498 once corrected). Scanned at one radius, scored by above_chance, winner goes on to the
    # radius sweep -- so it adds one pass, not len(angles) x len(radii) candidates on disk.
    # ON by default from 2026-09-15: 7 angles at ~5 s each is ~35 s against a ~45 min round, and
    # 5 deg steps are inside the matcher's own tolerance (PS393_1L R5 was 4 deg off and R7 2 deg
    # off; both registered fine at 0, while R3 at 8 deg was dead).
    angle_search_deg=15.0,           # half-span; 15 scans -15..+15. 0 disables the scan.
    angle_step_deg=5.0,
    angle_scan_radius_um=None,       # default: the largest context radius (most discriminative)
    # A non-zero angle must beat 0 deg by this FACTOR on above_chance before it is accepted, so
    # the scan is a RESCUE and not a re-optimisation: a healthy round keeps 0 and the radius
    # sweep that follows is bit-identical to a run with the scan disabled.
    #
    # 2.0 is measured, not guessed. Scanned 10 rounds across 5 samples (PS388_1L, PS389_1R,
    # PS527_04, PS528_01, JS082) on 2026-09-15: every HEALTHY round's best angle beat 0 deg by
    # at most 1.33x (PS389_1R R02, -5 deg, 5018 vs 3782), while PS393_1L R3 -- genuinely ~8-12
    # deg off -- beat it by ~2.6x (556 -> 1455). 2.0 sits in that gap with margin on both sides.
    # An earlier 1.15 would have rotated 2 of those 10, including PS389_1R R02, which is the best
    # round in the cohort at 3.70um / 63.4%. Do not lower this without re-running that sweep.
    angle_keep_zero_margin=2.0,
    match_threshold=0.3,
    select_metric="mi",              # "mi" (default) | "median_resid" | "above_chance"
    inlier_gate_um=12.0,             # reciprocal-NN gate for a "matched" cell (~ a cell spacing)
    ransac_threshold_um=15.0,        # cv2.estimateAffine3D inlier threshold
)
_LOCAL_DEFAULTS = dict(
    method="centroid",
    # Single fixed config: the full-field screen (cortex + PBN, all tiles) showed 200x200x10
    # wins every time and 400x400x15 loses every time, so the local blocksize search is dropped.
    # Labs can add more blocksizes in the manifest after a first run if their tissue differs.
    blocksize=[[200, 200, 10]],
    overlap=0.5,                     # A/B (overlap_ab_sweep.py) showed 0.25 costs quality on BOTH
                                     # samples: JS082 medResid 4.60->5.04um (frac<5 53->50%),
                                     # CIM131 11.62->16.49um (frac<5 34->26%). 0.25 is ~5x cheaper
                                     # (efficiency_sweep) but NOT free -- opt-in speed knob only.
    n_workers=1,                     # block-level parallelism; >1 fans blocks across processes
    threads_per_worker=8,
    context_radius=[12, 12, 2],      # voxels (current local style)
    context_radius_um=None,          # OPT-IN: global-style um window for blocks (experiment knob)
    match_threshold=0.3,
    # Hard cap on the distance between a paired fix/mov centroid. Below the true local
    # displacement it rejects EVERY candidate pair, the block fails match_floor, and it returns
    # identity -- silently, with no error. Raised 60 -> 200 on 2026-08-25: PS527_04 HCR03 carried a
    # ~90um (p95 113um) regional shift that the old 60 cost entirely, leaving 20/90 quadrant blocks
    # dead. At 175um that region went from 12.8% to 51.4% mutual-NN inliers and residual scatter
    # 10.4 -> 5.4um, with the already-good region UNCHANGED (5.47 -> 5.44um) and no runtime cost
    # (4 min either way). See figure_notebooks/figure_3_matching/regional_registration_failure_*.
    #
    # 200 is the useful ceiling for the default blocksize, not an arbitrary round number: with
    # overlap=0.5 blocks step by B/2, so a pair separated by d shares a block only when B >= 2d
    # (brute-force verified). blocksize 200px at 1.2626um/px caps recoverable d at ~126um, so a
    # cap much above ~200 buys reach the block cannot deliver while still adding rival candidates.
    # If you enlarge blocksize, this can go up with it; keep roughly cap <= blocksize_xy * xy_res.
    max_spot_match_distance_um=200.0,
    count_floor=8,                   # minimum centroids per block
    match_floor=4,                   # minimum point matches per block
    # bigstream blends neighbouring block transforms across the overlap. When a neighbour block
    # produced nothing (it failed count_floor/match_floor, so it stays identity), rebalancing
    # renormalises the surviving weights to sum to 1 -- which hands a lone block FULL authority
    # over territory where its neighbours found no evidence, instead of letting the blend fall
    # back toward identity. That is an amplifier exactly when coverage is low, and on
    # PS393_1L R4 (56% coverage, 44% of blocks identity) four blocks next to the dead zone
    # emitted 234-290um with a peak of 449um, against the ~90um a 180um block can even express.
    # Left True so no existing run changes; set False in the manifest to test.
    rebalance_for_missing_neighbors=True,
    adaptive_edges=True,
    nspots=5000,
    blob_sizes=[6, 30],              # REQUIRED by bigstream's signature; ignored when spots injected
)


def get_centroid_config(params):
    """Parse the centroid global/local config out of the manifest params, applying defaults.

    Returns (global_cfg, local_cfg, downsampling) or (None, None, ds) when the manifest has
    no global/local block (-> caller falls back to the legacy notebook flow).
    """
    ds = list(get_hcr_to_hcr_registration_config(params).get('downsampling', [3, 3, 2]))
    raw = params.get('HCR_to_HCR_registration', {}) or {}    # read global/local from the raw block
    g_raw, l_raw = raw.get('global'), raw.get('local')
    if g_raw is None and l_raw is None:
        return None, None, ds
    g = {**_GLOBAL_DEFAULTS, **(g_raw or {})}
    l = {**_LOCAL_DEFAULTS, **(l_raw or {})}
    # 'centroid' is the only implemented method. An unrecognised value used to
    # fall through to the legacy notebook path, whose error message says the
    # global/local block is missing -- confusing when it is right there.
    for name, cfg in (('global', g), ('local', l)):
        if cfg.get('method', 'centroid') != 'centroid':
            raise ValueError(
                f"HCR_to_HCR_registration.{name}.method = {cfg['method']!r} is not implemented. "
                "Remove the field; 'centroid' is the only option.")
    # normalise list-ish fields
    g['context_radius_um'] = _aslist(g['context_radius_um'])
    if l['blocksize'] and np.ndim(l['blocksize'][0]) == 0:   # single [Y,X,Z] -> wrap
        l['blocksize'] = [list(l['blocksize'])]
    else:
        l['blocksize'] = [list(b) for b in l['blocksize']]
    return g, l, ds


def _aslist(x):
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple, np.ndarray)) else [x]


# --------------------------------------------------------------------------- #
#  PORTED HELPERS -- geometry + honest metric
#  (verbatim from gen_hcr_global_centroid_diagnostic.py unless noted)
# --------------------------------------------------------------------------- #
def _apply(A, pts):                                        # pts Nx3 physical -> Nx3
    return (A[:3, :3] @ pts.T).T + A[:3, 3]


def _rot_z(theta):                                         # in-plane (y,x) rotation; coords (y,x,z)
    c, s = np.cos(theta), np.sin(theta)
    R = np.eye(4); R[0, 0] = c; R[0, 1] = -s; R[1, 0] = s; R[1, 1] = c
    return R


def mutual_inliers(A, fix_phys, mov_phys, gate_um):
    """Reciprocal NN within gate. A wrong/local-min transform gives few mutual pairs even if
    the one-way NN looks small (dense tissue). Returns (n_mutual, median_resid_um_of_mutual)."""
    from scipy.spatial import cKDTree
    fp = _apply(A, fix_phys)
    mtree = cKDTree(mov_phys); ftree = cKDTree(fp)
    d_fm, j = mtree.query(fp, k=1)
    _, i = ftree.query(mov_phys, k=1)
    mutual = (i[j] == np.arange(len(fp))) & (d_fm < gate_um)
    n = int(mutual.sum())
    return n, (float(np.median(d_fm[mutual])) if n else np.nan)


def null_mutual(A, fix_phys, mov_phys, gate_um, angle=45.0):
    """Chance floor: spin the A-aligned fix cloud by `angle` about its centre, recount mutuals.
    n_mut >> n_null = real signal."""
    from scipy.spatial import cKDTree
    fp = _apply(A, fix_phys); c = fp.mean(0)
    fp = (_rot_z(np.deg2rad(angle))[:3, :3] @ (fp - c).T).T + c
    mtree = cKDTree(mov_phys); ftree = cKDTree(fp)
    d_fm, j = mtree.query(fp, k=1); _, i = ftree.query(mov_phys, k=1)
    return int(((i[j] == np.arange(len(fp))) & (d_fm < gate_um)).sum())


def _contexts(img, spots_vox, cc):
    """Extract + L2-normalize (mean-subtracted) context vectors so a dot product == correlation.
    Returns (NxD unit vectors, keep_mask) for spots far enough from the edge. cc=(ry,rx,rz)."""
    ry, rx, rz = cc; Y, X, Z = img.shape; s = np.asarray(spots_vox, float)
    keep = ((s[:, 0] >= ry) & (s[:, 0] < Y - ry) & (s[:, 1] >= rx) & (s[:, 1] < X - rx) &
            (s[:, 2] >= rz) & (s[:, 2] < Z - rz))
    sp = s[keep].astype(int); D = (2 * ry + 1) * (2 * rx + 1) * (2 * rz + 1)
    out = np.empty((len(sp), D), np.float32)
    for k in range(len(sp)):
        y, x, z = sp[k]; out[k] = img[y - ry:y + ry + 1, x - rx:x + rx + 1, z - rz:z + rz + 1].ravel()
    if len(sp):
        out -= out.mean(1, keepdims=True)
        nrm = np.linalg.norm(out, axis=1, keepdims=True); nrm[nrm == 0] = 1; out /= nrm
    return out, keep


def _keep_sz(cent, area):
    """Drop segmentation artifacts: keep 0.3x-3x median nucleus volume."""
    if not len(area):
        return cent
    m = np.median(area); return cent[(area >= 0.3 * m) & (area <= 3.0 * m)]


def score_mi(A, fix, mov, fsp, msp):
    """Image MI on RAW (non-boosted) DAPI -- an INDEPENDENT sanity verdict (the centroid matcher
    optimises NN, not image MI). More negative = better. NEVER score boosted images.

    Returns (mi, aligned) -- the warped mov is handed back so the caller can write the QC
    composite from the SAME warp instead of recomputing it (the score you read and the overlay
    you inspect are then guaranteed to be the same image)."""
    from bigstream.transform import apply_transform
    al = np.asarray(apply_transform(fix, mov, fsp, msp, transform_list=[np.asarray(A)]))
    return float(get_registration_score(al, fix)), al


# --------------------------------------------------------------------------- #
#  PORTED HELPERS -- centroids + adaptive edges
#  (from _profile_local_reg.py)
# --------------------------------------------------------------------------- #
def _fast_centroids(mask):
    """Per-label centroid + area via bincount (~20x faster than regionprops on big masks).
    Returns (centroids Nx3 in (y,x,z) voxels, areas N)."""
    mask = np.asarray(mask)
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return np.empty((0, 3)), np.empty((0,))
    lab = mask.reshape(-1)[idx]
    ys, xs, zs = np.unravel_index(idx, mask.shape)
    n = int(lab.max()) + 1
    cnt = np.bincount(lab, minlength=n).astype(float)
    cy = np.bincount(lab, ys, minlength=n); cx = np.bincount(lab, xs, minlength=n)
    cz = np.bincount(lab, zs, minlength=n)
    keep = cnt > 0; keep[0] = False        # drop background label 0
    cents = np.column_stack([cy[keep] / cnt[keep], cx[keep] / cnt[keep], cz[keep] / cnt[keep]])
    return cents, cnt[keep]


def _score4(pts3, img):
    pts3 = np.asarray(pts3, float)
    if len(pts3) == 0:
        return np.empty((0, 4))
    yy = np.clip(pts3[:, 0].astype(int), 0, img.shape[0] - 1)
    xx = np.clip(pts3[:, 1].astype(int), 0, img.shape[1] - 1)
    zz = np.clip(pts3[:, 2].astype(int), 0, img.shape[2] - 1)
    return np.column_stack([pts3[:, 0], pts3[:, 1], pts3[:, 2], img[yy, xx, zz].astype(float)])


def _adaptive_get_contexts(image, coords, radius):
    """Bounds-safe replacement for bigstream.features.get_contexts: every context window is
    edge-padded to exactly (2r+1) per axis, so injected centroids near a volume edge / in a thin-z
    block degrade gracefully instead of crashing or falling back to identity. Module-level (not a
    closure) so it is picklable -> can be shipped to dask worker processes. Ported from
    _profile_local_reg.py."""
    if isinstance(radius, (int, np.integer)):
        radius = (radius,) * image.ndim
    radius = tuple(int(r) for r in radius)
    shp = image.shape
    out = []
    for coord in coords:
        lo, hi, plo, phi = [], [], [], []
        for x, r, n in zip(coord, radius, shp):
            x = int(round(float(x)))
            a, b = x - r, x + r + 1
            lo.append(max(a, 0)); hi.append(min(b, n))
            plo.append(max(-a, 0)); phi.append(max(b - n, 0))
        crop = image[tuple(slice(l, h) for l, h in zip(lo, hi))]
        if any(plo) or any(phi):
            crop = np.pad(crop, tuple((p, q) for p, q in zip(plo, phi)), mode="edge")
        out.append(crop)
    return out


def _install_adaptive_get_contexts():
    """Permanently install the adaptive get_contexts patch in the CURRENT process. Runs on dask
    worker processes (via client.run / a WorkerPlugin) where the main-process monkeypatch from
    adaptive_cc_contexts() is invisible -- the long-standing reason multiprocess block alignment
    'didn't work': workers silently used bigstream's edge-unsafe get_contexts and edge/thin-z
    blocks failed."""
    import bigstream.features as F
    F.get_contexts = _adaptive_get_contexts
    return True


@contextlib.contextmanager
def adaptive_cc_contexts():
    """Reversibly install the adaptive get_contexts patch in THIS process (main process; also the
    thread-pool workers, which share it). For a MULTIPROCESS cluster this is not enough -- use
    _patch_cluster_workers() to reinstall it inside each worker process too."""
    import bigstream.features as F
    orig = F.get_contexts
    F.get_contexts = _adaptive_get_contexts
    try:
        yield
    finally:
        F.get_contexts = orig


def _patch_cluster_workers(cl):
    """Reinstall the adaptive get_contexts patch on every worker process of a multiprocess cluster.
    Best-effort: warns and proceeds on failure. Covers both current workers (client.run) and any
    nanny-restarted workers (a WorkerPlugin)."""
    client = getattr(cl, 'client', None)
    if client is None:
        rprint("    [yellow]cluster exposes no .client; cannot patch workers for parallelism[/yellow]")
        return
    client.run(_install_adaptive_get_contexts)
    try:
        from distributed.diagnostics.plugin import WorkerPlugin

        class _AdaptiveGetContextsPlugin(WorkerPlugin):
            def setup(self, worker):
                _install_adaptive_get_contexts()

        # register_worker_plugin is deprecated in newer distributed in favour of register_plugin
        reg = getattr(client, 'register_plugin', None) or client.register_worker_plugin
        reg(_AdaptiveGetContextsPlugin())
    except Exception:
        pass    # client.run already covered the live workers; plugin is belt-and-suspenders


# --------------------------------------------------------------------------- #
#  LOAD one round's data (images + centroids, both global-lowres and local-fullres)
# --------------------------------------------------------------------------- #
def _norm_u8(arr, plo_hi=(0, 99.5)):
    from skimage import exposure
    return exposure.rescale_intensity(
        arr, in_range=(0, np.percentile(arr, plo_hi[1])), out_range=(0, 255)).astype(np.uint8)


def _load_round_data(reference_round, mov_round, fix_mask_path, mov_mask_path, ds):
    """Load fix/mov DAPI at full-res (local) + downsampled (global), and size-filtered
    centroids. Both masks must be in their own round's acquired frame, which is what
    cellpose/ holds; cellpose_aligned/ holds the reference-frame copies and is not this.

    Returns a dict with full-res images/centroids and downsampled (global) images/centroids,
    all in (Y,X,Z) order, plus physical spacings.
    """
    ds = np.array(ds)
    fix_sp = np.array(resolve_hcr_resolution(reference_round['image_path'], reference_round.get('resolution')))
    mov_sp = np.array(resolve_hcr_resolution(mov_round['image_path'], mov_round.get('resolution')))

    fix_full = _norm_u8(tif_imread(reference_round['image_path'])[:, 0].transpose(2, 1, 0))  # (Y,X,Z) DAPI
    mov_full = _norm_u8(tif_imread(mov_round['image_path'])[:, 0].transpose(2, 1, 0))

    fmask = tif_imread(str(fix_mask_path)).transpose(2, 1, 0)
    mmask = tif_imread(str(mov_mask_path)).transpose(2, 1, 0)
    # STALE-MASK GUARD: each mask must match its OWN raw image (same shape/orientation). A mismatch
    # means the image was rotated/replaced without re-segmenting -> the centroids are in the wrong
    # frame (garbage global) and intensity extraction crashes later. Fail fast with the fix.
    assert fmask.shape == fix_full.shape, (
        f"fix mask {fmask.shape} != fix image {fix_full.shape} -> stale/mismatched HCR"
        f"{reference_round['round']} mask. Delete its cellpose mask and re-run cellpose.")
    assert mmask.shape == mov_full.shape, (
        f"mov mask {mmask.shape} != mov image {mov_full.shape} -> stale/mismatched HCR"
        f"{mov_round['round']} mask (raw image changed without re-segmenting?). Delete "
        f"cellpose/{get_round_folder_name(mov_round['round'], reference_round['round'])}_masks.tiff "
        f"and re-run cellpose.")
    # Nothing further is asserted about the two shapes relative to each other. Rounds
    # acquired at the same dimensions give a mov mask the same shape as fix, which is
    # perfectly normal, and in that case shape cannot tell an acquired-frame mask from a
    # reference-warped one anyway. The guarantee comes from the folder, not the geometry:
    # cellpose/ is each round in its own frame, cellpose_aligned/ is the warped copies.

    fix_cent, fix_area = _fast_centroids(fmask)
    mov_cent, mov_area = _fast_centroids(mmask)
    fix_cent = _keep_sz(fix_cent, fix_area)
    mov_cent = _keep_sz(mov_cent, mov_area)

    sl = (slice(None, None, ds[0]), slice(None, None, ds[1]), slice(None, None, ds[2]))
    mov_lo = mov_full[sl]

    # global_centroid sizes its context window as a fixed VOXEL count off the FIX spacing and
    # applies that same window to both volumes, so the two patches cover the same physical area
    # only when the rounds share a pixel size. Often they do not: within PS393_1L the reference
    # is 0.902um/px and six of seven rounds are 1.136 or 1.263, so a 122um fix patch was being
    # correlated pixel-for-pixel against a 171um mov patch. Measured cost on that sample at
    # r=60um: HCR04 matched 11.4% of mov cells instead of 66.3%, and the affine stayed at
    # identity (0/880 blocks deformed). Put the moving lowres volume on the fix lowres grid so
    # one voxel radius is one physical radius in both.
    #
    # Linear, not nearest: the nuclear texture IS the signal being correlated and NN aliases it.
    # (Label volumes are the opposite case -- align_masks_to_reference warps those with
    # interpolator='0' because there an invented in-between value is a nonexistent cell.)
    fix_lo = fix_full[sl]
    lo_f, lo_m = fix_sp * ds, mov_sp * ds

    # Both volumes are compared on the REFERENCE grid, so one voxel radius is one physical
    # radius in both. Putting them on the COARSER grid instead was tried on 2026-09-15: it
    # improved PS393_1L R4's global frac<5 from 10.6% to 17.6% and made the FINAL result worse
    # (45.2 -> 41.9%). Global-stage gains do not predict final quality, so that option was
    # removed rather than shipped as a knob nobody should turn.
    lo_sp_match = lo_f

    def _to_match(vol, cent, sp_full, lo_sp):
        """Put a lowres volume and its FULL-RES centroids on the shared match grid."""
        z = lo_sp / lo_sp_match
        idx = cent * (sp_full / lo_sp_match)          # full-res voxels -> match-grid lowres idx
        if np.allclose(z, 1.0):
            return vol, idx
        from scipy.ndimage import zoom
        return zoom(vol, z, order=1), idx

    fix_lo_rs, fix_cent_rs = _to_match(fix_lo, fix_cent, fix_sp, lo_f)
    mov_lo_rs, mov_cent_rs = _to_match(mov_lo, mov_cent, mov_sp, lo_m)

    return dict(
        fix_full=fix_full, mov_full=mov_full, fix_sp=fix_sp, mov_sp=mov_sp,
        fix_lo=fix_lo, mov_lo=mov_lo, lo_sp_f=lo_f, lo_sp_m=lo_m, ds=ds,
        # Global context matching ONLY, on a shared grid, with centroids already in that grid's
        # lowres index units. Everything downstream -- RANSAC, mutual_inliers, MI, the composite,
        # the local stage -- keeps using fix_lo / mov_lo in each round's own acquired frame.
        fix_lo_rs=fix_lo_rs, fix_cent_rs=fix_cent_rs,
        mov_lo_rs=mov_lo_rs, mov_cent_rs=mov_cent_rs, lo_sp_match=lo_sp_match,
        fix_cent=fix_cent, mov_cent=mov_cent,                 # full-res voxel coords (y,x,z)
        fix_cent_phys=fix_cent * fix_sp, mov_cent_phys=mov_cent * mov_sp,
    )


def _angle_list(gcfg):
    """Angles to scan, always including 0. Empty/0 span -> [0.0], i.e. today's behaviour."""
    span = float(gcfg.get('angle_search_deg', 0) or 0)
    if span <= 0:
        return [0.0]
    step = float(gcfg.get('angle_step_deg', 4) or 4)
    n = int(np.floor(span / step))
    return sorted({0.0} | {float(s * step * k) for k in range(1, n + 1) for s in (-1, 1)}
                  | {-span, span})


def _rotate_for_match(vol, idx, ang_deg):
    """Rotate a lowres volume in the (Y,X) plane and carry its centroid indices with it.

    NEAREST-NEIGHBOUR (order=0) on purpose: the descriptor correlates nuclear texture, and a
    linear resample would soften the moving round relative to the un-rotated reference, adding
    exactly the sharpness mismatch we are trying not to introduce. Sub-voxel jitter from NN is
    +/-1.35um at the 2.7um lowres grid, small against a ~22um nucleus.

    Centroids are rotated ANALYTICALLY rather than re-derived from a rotated mask, so they carry
    no interpolation error at all. The convention below is scipy.ndimage.rotate's, verified
    against a synthetic dot pattern (the transposed form silently doubles the angle instead of
    cancelling it, which produced a wrong result on 2026-09-15 before it was caught).
    """
    if abs(ang_deg) < 1e-9:
        return vol, idx
    from scipy.ndimage import rotate as _nd_rotate
    h0, w0 = vol.shape[0], vol.shape[1]
    out = _nd_rotate(vol, ang_deg, axes=(0, 1), reshape=True, order=0,
                     mode='constant', cval=0)
    th = np.deg2rad(ang_deg); co, si = np.cos(th), np.sin(th)
    cy0, cx0 = (h0 - 1) / 2.0, (w0 - 1) / 2.0
    cy1, cx1 = (out.shape[0] - 1) / 2.0, (out.shape[1] - 1) / 2.0
    y = np.asarray(idx)[:, 0] - cy0; x = np.asarray(idx)[:, 1] - cx0
    return out, np.column_stack([co * y - si * x + cy1,
                                 si * y + co * x + cx1,
                                 np.asarray(idx)[:, 2]])


def _fit_global_A(fctx, mctx, fphys, mphys, mt, rth, batch):
    """Correlate every mov context against every fix context, keep the best match above `mt`,
    and fit an affine by RANSAC. Returns identity when nothing survives."""
    import cv2
    src, dst = [], []
    for b in range(0, len(mctx), batch):
        corr = mctx[b:b + batch] @ fctx.T                 # every mov vs ALL fix
        j = corr.argmax(1); cval = corr[np.arange(corr.shape[0]), j]; ok = cval > mt
        if ok.any():
            dst.append(mphys[b:b + batch][ok]); src.append(fphys[j[ok]])
    if not src:
        return np.eye(4)
    src = np.vstack(src).astype(np.float32); dst = np.vstack(dst).astype(np.float32)
    if len(src) < 12:
        return np.eye(4)
    try:
        _, M, _ = cv2.estimateAffine3D(src, dst, ransacThreshold=rth, confidence=0.999)
    except Exception as e:
        rprint(f"    [yellow]global ransac err {type(e).__name__}: {e}[/yellow]")
        return np.eye(4)
    if M is None:
        return np.eye(4)
    A = np.eye(4); A[:3, :] = M
    return A


# --------------------------------------------------------------------------- #
#  GLOBAL  -- cap-free 2D-context centroid affine (ported centroid_global_batched)
# --------------------------------------------------------------------------- #
def global_centroid(S, gcfg, emit=None, batch=2000):
    """Sweep gcfg['context_radius_um'] and return (table, suggested_idx), where table is a list of
    per-radius dicts {radius_um, above_chance, n_mut, med_resid, mi, A} and suggested_idx points at
    the row gcfg['select_metric'] favours. EVERY radius is kept -- the metrics routinely disagree
    (MI can prefer a radius with fewer mutual inliers and a worse residual), so the caller shows
    the whole table and the suggestion is advisory, not a filter.

    `emit(row, aligned)` is called once per radius, right after it is scored, with the warped
    lowres mov. The caller uses it to persist that radius' _affine.mat + QC composite before the
    next radius overwrites `aligned`, so all candidates are on disk to inspect BEFORE anything is
    chosen. Writing as we go (rather than returning N warped volumes) keeps peak memory at one
    lowres volume regardless of how many radii are swept.

    Ported from centroid_global_batched (the robust, no-prior, no-rotation global) + an MI column."""
    import cv2
    gate = float(gcfg['inlier_gate_um']); mt = float(gcfg['match_threshold'])
    rth = float(gcfg['ransac_threshold_um'])
    # Matching runs on a SHARED grid (the reference's, see _load_round_data), with both centroid
    # sets already expressed in that grid's lowres index units, so `cc` below is one physical
    # window in both images. MI, the composite and the physical point sets stay on each round's
    # own acquired frame.
    fwm, fcm = S['fix_lo_rs'], S['fix_cent_rs']
    mwm, mcm = S['mov_lo_rs'], S['mov_cent_rs']
    xy = float(S['lo_sp_match'][0]); ds = S['ds']
    fcF, mcF = S['fix_cent'], S['mov_cent']      # already size-filtered, full-res voxels
    fcp, mcp = S['fix_cent_phys'], S['mov_cent_phys']


    # ---- ANGLE SCAN -------------------------------------------------------------------
    # _contexts correlates AXIS-ALIGNED patches: there is no rotation invariance anywhere in
    # this matcher. A residual hand-rotation of theta displaces a feature at the patch edge by
    # r*sin(theta), which at r=80um is 11um at 8 degrees -- comparable to the 12um inlier gate,
    # and half a nucleus. Measured on PS393_1L R3 (filed at 0, actually ~8 out): correcting the
    # angle took mutual inliers 556 -> 1498 and the affine diagonal from garbage to
    # [+0.985 +0.922 +0.613], matching its healthy sibling R5. The QC rotation test only ever
    # tries 0/90/180/270, so it certified R3 as "0 wins" while it sat 8 degrees off.
    #
    # Scanned at ONE radius and scored by above_chance (not MI -- MI's tiebreak is unreliable
    # below a ~0.006 margin, see the PS388_1L note). Only the winning angle goes on to the radius
    # sweep, so the number of persisted candidates and composites is unchanged.
    angles = _angle_list(gcfg)
    ang_best = 0.0
    if len(angles) > 1:
        scan_r = float(gcfg.get('angle_scan_radius_um') or max(gcfg['context_radius_um']))
        r = max(1, int(round(scan_r / xy))); cc = (r, r, 0)          # 2D window: XY radius, single z-plane
        fctx_s, fk_s = _contexts(fwm, fcm, cc)
        fphys_s = fcF[fk_s] * S['fix_sp']
        rprint(f"    [cyan]angle scan[/cyan]  {len(angles)} angles "
               f"{min(angles):+.0f}..{max(angles):+.0f}° step {float(gcfg.get('angle_step_deg', 4)):g}° "
               f"· r{scan_r:.0f}µm · NN · scored by above-chance")
        t_scan = time.time()
        scan, best_sc, zero_sc = [], -np.inf, None
        for ang in angles:
            mw_a, mcR_a = _rotate_for_match(mwm, mcm, ang)
            mctx_a, mk_a = _contexts(mw_a, mcR_a, cc)
            if len(fctx_s) < 12 or len(mctx_a) < 12:
                scan.append((ang, -1, 0)); continue
            A_a = _fit_global_A(fctx_s, mctx_a, fphys_s, mcF[mk_a] * S['mov_sp'], mt, rth, batch)
            n_a, _ = mutual_inliers(A_a, fcp, mcp, gate)
            ab_a = n_a - null_mutual(A_a, fcp, mcp, gate)
            scan.append((ang, ab_a, n_a))
            if abs(ang) < 1e-9:
                zero_sc = ab_a
            if ab_a > best_sc:
                best_sc, ang_best = ab_a, ang
        # RESCUE, not re-optimisation: keep 0 unless another angle clears it by the margin.
        margin = float(gcfg.get('angle_keep_zero_margin', 1.15) or 1.0)
        if zero_sc is not None and abs(ang_best) >= 1e-9 and best_sc <= max(zero_sc, 0) * margin:
            rprint(f"      best {ang_best:+.0f} deg ({best_sc}) does not clear 0 deg "
                   f"({zero_sc}) by {margin:g}x -- [b]keeping 0[/b]")
            ang_best, best_sc = 0.0, zero_sc
        dt = time.time() - t_scan
        rprint("      " + "  ".join(f"[{'b' if a == ang_best else 'dim'}]{a:+.0f}°:{ab}[/]"
                                    for a, ab, _ in scan))
        if abs(ang_best) < 1e-9:
            rprint(f"      [green]0° kept[/green] (above-chance {best_sc}) · "
                   f"{dt:.0f}s, {dt/max(1,len(angles)):.1f}s/angle")
        else:
            gain = f"{best_sc}/{zero_sc}" if zero_sc else str(best_sc)
            rprint(f"      [yellow]ROTATED {ang_best:+.0f}°[/yellow] — above-chance {gain} "
                   f"vs 0°, clears the {margin:g}x margin · "
                   f"{dt:.0f}s, {dt/max(1,len(angles)):.1f}s/angle")
            rprint(f"      [dim]the round was filed ~{-ang_best:+.0f}° off the reference; "
                   f"this corrects it in-pipeline, the filed TIFF is untouched[/dim]")
    # Lowres indices from here on, so the rotation is applied once and never round-tripped.
    if len(angles) > 1 and abs(ang_best) >= 1e-9:
        mwm, mcm = _rotate_for_match(mwm, mcm, ang_best)

    table, best = [], (np.eye(4), -np.inf, None)
    for r_um in gcfg['context_radius_um']:
        r = max(1, int(round(r_um / xy))); cc = (r, r, 0)          # 2D window: XY radius, single z-plane
        fctx, fk = _contexts(fwm, fcm, cc); mctx, mk = _contexts(mwm, mcm, cc)
        A = np.eye(4)
        if len(fctx) >= 12 and len(mctx) >= 12:
            # mk is a keep-mask over the shared mov cell ordering, so it indexes mcF (acquired
            # frame) exactly as it indexes mcR (fix grid). Physical coords come from mcF -- the
            # UNROTATED acquired frame, so the fitted affine absorbs the scan angle and nothing
            # downstream needs to know about it.
            fphys = fcF[fk] * S['fix_sp']; mphys = mcF[mk] * S['mov_sp']
            A = _fit_global_A(fctx, mctx, fphys, mphys, mt, rth, batch)
        n_mut, med = mutual_inliers(A, fcp, mcp, gate)
        above = n_mut - null_mutual(A, fcp, mcp, gate)
        mi, aligned = score_mi(A, S['fix_lo'], S['mov_lo'], S['lo_sp_f'], S['lo_sp_m'])
        row = dict(radius_um=r_um, above_chance=above, n_mut=n_mut,
                   med_resid=med, mi=mi, A=A, angle_deg=ang_best)
        if emit is not None:
            emit(row, aligned)             # persist this candidate NOW (stamps tag/dir/composite on row)
        del aligned                        # one lowres volume alive at a time
        table.append(row)
    # gcfg['select_metric'], not a literal: it was hardcoded to 'mi' here until 2026-09-11, which
    # made the manifest key (and its default, and its docs) dead config -- setting it changed
    # nothing and gave no error. Default is still 'mi', so no existing manifest changes behaviour.
    pick = _pick_global(table, gcfg.get('select_metric', 'mi'))
    # identity, not equality: rows hold numpy arrays, so `table.index(pick)` would compare arrays
    sug = next(i for i, r in enumerate(table) if r is pick)
    return table, sug


def _pick_global(table, metric):
    """Choose the global radius strictly by `metric`:
      'mi'           -> best (most-negative) raw-DAPI image MI -- an independent verdict, used as-is.
      'above_chance' -> most reciprocal inliers above the 45deg-spin null.
      'median_resid' -> lowest mutual-inlier residual, tie-broken by MORE inliers; GUARDED to radii
                        with above_chance > 0 (a sparse-but-close fit can fake a low residual, so
                        the residual metric -- and only it -- ignores worse-than-chance radii)."""
    if metric == "mi":
        return min(table, key=lambda r: r['mi'])
    if metric == "above_chance":
        return max(table, key=lambda r: r['above_chance'])
    valid = [r for r in table if r['above_chance'] > 0] or table
    return min(valid, key=lambda r: (r['med_resid'] if r['med_resid'] == r['med_resid'] else 1e9, -r['n_mut']))


# --------------------------------------------------------------------------- #
#  LOCAL  -- bigstream piecewise deform with injected centroids (ported)
# --------------------------------------------------------------------------- #
def _local_cfg_dict(lcfg, fix_sp):
    """Build the per-block bigstream ransac config from the manifest local config."""
    if lcfg.get('context_radius_um'):                       # experiment knob: um-window -> voxels
        r = max(1, int(round(float(lcfg['context_radius_um']) / float(fix_sp[0]))))
        cc = (r, r, max(1, int(round(float(lcfg['context_radius_um']) / float(fix_sp[2])))))
    else:
        cc = tuple(int(v) for v in lcfg['context_radius'])
    mt = lcfg['match_threshold']
    return dict(
        blob_sizes=list(lcfg.get('blob_sizes', [6, 30])),   # required positionally; ignored when spots injected
        cc_radius=cc,
        match_threshold=list(mt) if isinstance(mt, (list, tuple)) else [float(mt)],
        max_spot_match_distance=float(lcfg['max_spot_match_distance_um']),
        fix_spots_count_threshold=int(lcfg['count_floor']),
        mov_spots_count_threshold=int(lcfg['count_floor']),
        point_matches_threshold=int(lcfg['match_floor']),
        nspots=int(lcfg['nspots']),
        safeguard_exceptions=False,
    )


def _moved_coverage(deform, blocksize):
    """Fraction of blocks that received a real local deform (95th-pct displacement > 0.5um)."""
    bs = np.array(blocksize); mag = np.linalg.norm(deform, axis=-1)
    grid = np.ceil(np.array(mag.shape) / bs).astype(int); moved = tot = 0
    for i in range(grid[0]):
        for j in range(grid[1]):
            for k in range(grid[2]):
                t = mag[i * bs[0]:(i + 1) * bs[0], j * bs[1]:(j + 1) * bs[1], k * bs[2]:(k + 1) * bs[2]]
                if t.size:
                    tot += 1; moved += int(np.percentile(t, 95) > 0.5)
    return moved, tot


def local_centroid_one(S, A_global, blocksize, lcfg, out_dir, cluster_kwargs=None, overlay_tiff=None,
                       fingerprint=None, resume=True):
    """Run ONE local block config at FULL resolution: write _affine.mat + deform.zarr into
    out_dir (these MUST stay per-candidate -- _load_round_transform reads them), and the QC
    composite to overlay_tiff (a single pooled folder; defaults to out_dir if not given).
    Returns metrics {medResid_um, frac_under5, moved, total, mi, reused}. Ported from
    _profile_local_reg.coverage_sweep._run, but writes PERSISTENT pipeline outputs (no /tmp,
    deform.zarr kept).

    RESUME: when `fingerprint` (mask identity + global affine) matches the one stamped beside an
    existing deform.zarr, the expensive align is SKIPPED and metrics are re-derived from the saved
    field. A changed mask / global / block config flips the fingerprint -> recompute (never reuses
    a stale field)."""
    import zarr
    from scipy.spatial import cKDTree
    from bigstream.piecewise_align import distributed_piecewise_alignment_pipeline
    from bigstream.transform import apply_transform_to_coordinates
    try:
        from ClusterWrap import cluster as cluster_constructor
    except ImportError:
        from ClusterWrap.clusters import cluster as cluster_constructor

    fix, mov = S['fix_full'], S['mov_full']
    fsp, msp = np.asarray(S['fix_sp'], float), np.asarray(S['mov_sp'], float)
    fix_pts = np.asarray(S['fix_cent'], float)                          # full-res voxels (y,x,z)
    fix_spots4 = _score4(fix_pts, fix)
    # mov centroids -> fix frame (inv global affine), injected as fix-frame spots
    mov_fix = apply_transform_to_coordinates(
        S['mov_cent_phys'].astype(float), [np.linalg.inv(A_global)], transform_spacing=fsp) / fsp
    mov_spots4 = _score4(mov_fix, fix)

    loc = _local_cfg_dict(lcfg, fsp)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    deform_path = out_dir / "deform.zarr"
    fp_path = out_dir / "_fingerprint.txt"

    reused = bool(resume and fingerprint and deform_path.exists()
                  and (out_dir / "_affine.mat").exists()
                  and fp_path.exists() and fp_path.read_text().strip() == fingerprint)

    if not reused:
        shutil.rmtree(deform_path, ignore_errors=True)
        nw = int(lcfg.get('n_workers', 1)); tpw = int(lcfg.get('threads_per_worker', 8))
        ck = cluster_kwargs or {"n_workers": nw, "threads_per_worker": tpw, "processes": nw > 1}
        adaptive = lcfg.get('adaptive_edges', True)

        def _run(cluster_kwargs):
            multiproc = bool(cluster_kwargs.get('processes'))
            ctx = adaptive_cc_contexts() if adaptive else contextlib.nullcontext()
            with ctx, cluster_constructor(cluster_kwargs) as cl:
                if adaptive and multiproc:        # propagate the patch into the worker PROCESSES
                    _patch_cluster_workers(cl)
                distributed_piecewise_alignment_pipeline(
                    fix, mov, fsp, msp, steps=[("ransac", loc)],
                    blocksize=list(blocksize), overlap=float(lcfg['overlap']),
                    static_transform_list=[np.asarray(A_global)], write_path=str(deform_path),
                    rebalance_for_missing_neighbors=bool(
                        lcfg.get('rebalance_for_missing_neighbors', True)),
                    cluster=cl, fix_spots_global=fix_spots4, mov_spots_global=mov_spots4)

        try:
            _run(ck)
        except Exception as e:
            if ck.get('processes'):               # multiprocess flaked -> fall back to a thread pool
                rprint(f"    [yellow]multiprocess cluster failed ({type(e).__name__}: {e}); "
                       f"retrying single-process thread pool[/yellow]")
                shutil.rmtree(deform_path, ignore_errors=True)
                _run({"n_workers": 1, "threads_per_worker": tpw, "processes": False})
            else:
                raise

        np.savetxt(str(out_dir / "_affine.mat"), np.asarray(A_global))  # required by _load_round_transform
        if fingerprint:
            fp_path.write_text(fingerprint)

    deform = zarr.open(str(deform_path), mode="r")[...]

    # residual: fix centroids warped by [affine, deform], scored with the MUTUAL reciprocal-inlier
    # metric (same as the global) -- robust to volume/coverage mismatch. When one round is much
    # bigger or deeper than the other, its extra cells have no true partner; a one-way all-cells NN
    # median is inflated by them (-> false RED FLAG, e.g. JS079 z-depth, SRC104 1.9x cell count).
    # Mutual inliers exclude the unmatchable cells. all-cells kept for reference only.
    mov_phys = S['mov_cent_phys']
    gate = float(lcfg.get('inlier_gate_um', 12.0))
    fp = apply_transform_to_coordinates(fix_pts * fsp, [np.asarray(A_global), deform], transform_spacing=fsp)
    mtree = cKDTree(mov_phys); ftree = cKDTree(fp)
    d_all, j = mtree.query(fp, k=1)
    _, i = ftree.query(mov_phys, k=1)
    mut = (i[j] == np.arange(len(fp))) & (d_all < gate)
    n_mut = int(mut.sum())
    med_mut = float(np.median(d_all[mut])) if n_mut else float('nan')
    frac5_mut = float(np.mean(d_all[mut] < 5.0)) if n_mut else 0.0
    moved, tot = _moved_coverage(deform, blocksize)

    # MI on RAW lowres DAPI with [affine, deform] -- the boost-proof independent verdict the candidates
    # are RANKED by (more negative = better). Computed from the same lowres warp as the QC composite,
    # so the candidate selection and the overlay you inspect agree.
    from bigstream.transform import apply_transform
    try:
        aligned_lo = np.asarray(apply_transform(
            S['fix_lo'], S['mov_lo'], np.asarray(S['lo_sp_f']), np.asarray(S['lo_sp_m']),
            transform_list=[np.asarray(A_global), deform], transform_spacing=fsp))
        mi = float(get_registration_score(aligned_lo, S['fix_lo']))
    except Exception as e:
        aligned_lo, mi = None, float('nan')
        rprint(f"    [yellow]local MI failed: {type(e).__name__}: {e}[/yellow]")

    # QC composite (warped mov + fix) at lowres -> pooled overlays folder. Reuse the MI warp; affine
    # fallback. On reuse, only (re)write if it's missing -- the warp is the one not-quite-free step here.
    ov = Path(overlay_tiff) if overlay_tiff else (out_dir / "overlay_warped.tiff")
    ov.parent.mkdir(parents=True, exist_ok=True)
    if not (reused and ov.exists()):
        try:
            _write_composite(S['fix_lo'], S['mov_lo'], S['lo_sp_f'], S['lo_sp_m'],
                             [np.asarray(A_global), deform], ov, transform_spacing=fsp, aligned=aligned_lo)
        except Exception as e:
            try:
                _write_composite(S['fix_lo'], S['mov_lo'], S['lo_sp_f'], S['lo_sp_m'],
                                 [np.asarray(A_global)], ov)
            except Exception as e2:
                rprint(f"    [yellow]composite write failed: {type(e2).__name__}: {e2}[/yellow]")

    return dict(medResid_um=med_mut, frac_under5=frac5_mut, n_mut=n_mut,
                medResid_allcells=float(np.median(d_all)), frac_under5_allcells=float(np.mean(d_all < 5.0)),
                moved=int(moved), total=int(tot), mi=mi, reused=reused)


# --------------------------------------------------------------------------- #
#  QC composite: warp the mov IMAGE and save a 2-channel ImageJ TIFF (warped + fix),
#  like the legacy register_lowres _both.tiff. Rendered at the downsampled (lowres) grid
#  so it is cheap. transform_list = [affine] (global) or [affine, deform] (local).
# --------------------------------------------------------------------------- #
def _write_composite(fix, mov, fsp, msp, transform_list, out_tiff, transform_spacing=None, aligned=None):
    from bigstream.transform import apply_transform
    if aligned is None:                          # reuse a precomputed warp (e.g. the MI warp) when given
        aligned = np.asarray(apply_transform(
            fix, mov, np.asarray(fsp), np.asarray(msp),
            transform_list=transform_list, transform_spacing=transform_spacing))
    # (Y,X,Z) -> ImageJ (Z, C=2, Y, X): channel 0 = warped mov, channel 1 = fix
    comp = np.swapaxes(np.array([aligned.transpose(2, 1, 0), fix.transpose(2, 1, 0)]), 0, 1)
    tif_imwrite(str(out_tiff), comp.astype(np.uint8), imagej=True)


# --------------------------------------------------------------------------- #
#  TAGS  (must satisfy _load_round_transform's bs(\d+)[x_](\d+)[x_](\d+) regex)
# --------------------------------------------------------------------------- #
def _global_tag(radius_um, mt, angle_deg=0.0):
    # Every suffix appears ONLY when the setting is off-default, so each tag already on disk
    # keeps its name and an experiment cannot collide with (and be silently resumed from) a
    # default-settings candidate. The tag IS the identity of a candidate.
    a = "" if abs(float(angle_deg or 0.0)) < 1e-9 else f"_a{int(round(angle_deg)):+d}"
    return f"global_cent_r{int(round(radius_um))}um_mt{mt}{a}"


def _local_tag(blocksize, lcfg):
    by, bx, bz = (int(v) for v in blocksize)
    ctx = (f"r{int(round(float(lcfg['context_radius_um'])))}um" if lcfg.get('context_radius_um')
           else "r" + "x".join(str(int(v)) for v in lcfg['context_radius']))
    # Both suffixes appear ONLY when the setting is off-default, so every tag already on disk
    # keeps its name. They exist because the tag IS the identity of a candidate: two runs that
    # differ only in an untagged setting land in the same directory, match the resume
    # fingerprint, and the second silently reports the first one's deform as its own result.
    # max_spot_match_distance_um is exactly that kind of setting and was untagged until
    # 2026-09-14.
    norb = "" if lcfg.get('rebalance_for_missing_neighbors', True) else "_norebal"
    dist = float(lcfg.get('max_spot_match_distance_um', 200.0))
    dsuf = "" if abs(dist - 200.0) < 1e-6 else f"_d{int(round(dist))}"
    mf = int(lcfg.get('match_floor', 4))
    msuf = "" if mf == 4 else f"_mf{mf}"
    return (f"bs{by}x{bx}x{bz}_ov{lcfg['overlap']}_cent_{ctx}"
            f"_mt{lcfg['match_threshold']}_f{lcfg['count_floor']}{dsuf}{msuf}{norb}")


# --------------------------------------------------------------------------- #
#  OUTPUT  -- structured plan + scored summary + red-flag assessment
# --------------------------------------------------------------------------- #
_SEV = {0: ("✓", "green", "OK"),
        1: ("⚠", "yellow", "WARN"),
        2: ("✗", "red", "RED FLAG")}


def _sev_badge(sev):
    glyph, color, label = _SEV[sev]
    return f"[{color}]{glyph} {label}[/{color}]"


def _print_msgs(sev, msgs, indent="      "):
    glyph, color, _ = _SEV[sev]
    for m in msgs:
        rprint(f"{indent}[{color}]{glyph} {m}[/{color}]")


def _print_ladder(round_to_rounds, ref, gcfg, lcfg, unattended=False):
    """One-time header: what the two stages (coarse affine, fine deform) do for every round, so the
    long run is legible from the first screen."""
    radii = [int(r) for r in gcfg['context_radius_um']]
    blocks = ', '.join('×'.join(str(int(v)) for v in b) for b in lcfg['blocksize'])
    rprint("\n" + "═" * 72)
    rprint(f"[bold] HCR→HCR registration · {len(round_to_rounds)} round(s) → HCR{ref}[/bold]")
    rprint("  [dim]Mode: cellpose centroids (nucleus landmarks)[/dim]")
    rprint("═" * 72)
    rprint(f"  [cyan]1 COARSE[/cyan]  whole-volume affine · context window {radii}µm")
    ang = float(gcfg.get('angle_search_deg', 0) or 0)
    if ang > 0:
        n = len(_angle_list(gcfg))
        rprint(f"            + rotation rescue · {n} angles ±{ang:g}° step "
               f"{float(gcfg.get('angle_step_deg', 4)):g}° · keeps 0° unless another angle beats "
               f"it by {float(gcfg.get('angle_keep_zero_margin', 1.15)):g}x")
    rprint(f"  [cyan]2 FINE  [/cyan]  local warps · block size {blocks}")
    if unattended:
        # Says what this run will actually do. The attended wording below promises a prompt that
        # is not coming, which is the one line of an unattended log nobody can check against.
        rprint(f"  [dim]Every candidate is written to disk and listed with a composite tiff; "
               f"[b]{gcfg.get('select_metric', 'mi')}[/b] picks the row, unreviewed.[/dim]")
    else:
        rprint("  [dim]Every candidate is written to disk and listed with a composite tiff; [b]mi[/b] "
               "only suggests — you pick the row.[/dim]")
    rprint("═" * 72)


def _assess_global(picked, n_fix, n_mov):
    """Red-flag the chosen global. Returns (severity 0/1/2, [messages])."""
    sev, msgs = 0, []
    ab, nm, mr = picked['above_chance'], picked['n_mut'], picked['med_resid']
    denom = max(1, min(n_fix, n_mov))
    if ab <= 0:
        sev = 2; msgs.append(f"above-chance {ab} ≤ 0 — global is NO BETTER THAN CHANCE (did not lock)")
    elif nm < 0.10 * denom:
        sev = max(sev, 1); msgs.append(f"only {nm} mutual inliers ({100*nm/denom:.0f}% of cells) — sparse lock")
    if mr == mr and mr > 25:
        sev = 2; msgs.append(f"mutual-inlier residual {mr:.1f}µm very high (>25µm)")
    elif mr == mr and mr > 15:
        sev = max(sev, 1); msgs.append(f"mutual-inlier residual {mr:.1f}µm high (>15µm)")
    return sev, msgs


def _assess_local(best, global_med):
    """Red-flag the best local candidate vs absolute gates and vs the global it refined.
    Returns (severity 0/1/2, [messages])."""
    if best is None:
        return 2, ["ALL local blocksizes failed — no deform produced"]
    sev, msgs = 0, []
    mr, fr = best['medResid_um'], best['frac_under5']   # mutual-inlier residual + frac<5 (size-robust)
    cov = best['moved'] / max(1, best['total'])
    if mr > 15:
        sev = 2; msgs.append(f"mutual-inlier residual {mr:.1f}µm > 15µm — local did NOT register")
    elif mr > 10:
        sev = max(sev, 1); msgs.append(f"mutual-inlier residual {mr:.1f}µm > 10µm — marginal")
    if fr < 0.30:                       # fraction of MATCHED (mutual-inlier) cells within 5µm; a
        sev = max(sev, 1); msgs.append(f"only {fr*100:.0f}% of matched cells within 5µm (<30%)")  # genuinely
        # good register (JS082) reaches ~50%, so 30% is the realistic warn floor.
    if cov < 0.50:
        sev = max(sev, 1); msgs.append(f"only {cov*100:.0f}% of blocks deformed (<50%) — field mostly identity")
    if global_med == global_med and mr >= global_med:
        sev = max(sev, 1); msgs.append(f"local {mr:.1f}µm ≥ global {global_med:.1f}µm — deform added nothing")
    return sev, msgs


# --------------------------------------------------------------------------- #
#  ALREADY-REGISTERED DETECTION
#  A re-run used to repeat every round from scratch -- reloading ~1GB of masks, re-sweeping
#  the coarse radii, re-asking both review questions and recomputing a ~15 min deform -- even
#  when that round was already finished and recorded. These let the driver notice and ask
#  before overwriting. Deliberately cheap: one manifest read + two stat calls, no image IO.
# --------------------------------------------------------------------------- #
def _norm_round(r):
    """'02' and 2 name the same round; compare them on equal terms."""
    return str(r).strip().lstrip('0') or '0'


def _selected_tag(full_manifest, rnd):
    """The 'global_tag/local_tag' this round is currently registered with, per the manifest's
    HCR_selected_registrations, or None."""
    try:
        sel = parse_json(full_manifest['manifest_path'])['params'].get('HCR_selected_registrations') or {}
        for r in sel.get('rounds', []):
            if _norm_round(r.get('round')) == _norm_round(rnd):
                regs = r.get('selected_registrations') or []
                return regs[0] if regs else None
    except Exception:
        pass          # unreadable/absent block -> treat as "not registered yet"
    return None


def completed_round(full_manifest, out_root, rfolder, rnd):
    """Return {tag, dir, when} when this round already has a FINISHED registration, else None.

    'Finished' = the manifest names a selected tag AND that folder holds both products the
    apply step consumes (deform.zarr + _affine.mat). A half-written candidate from an
    interrupted run has no manifest entry, so it correctly does not count as done.
    """
    tag = _selected_tag(full_manifest, rnd)
    if not tag:
        return None
    d = out_root / 'registrations' / rfolder / Path(tag)
    if not ((d / 'deform.zarr').exists() and (d / '_affine.mat').exists()):
        return None
    return dict(tag=tag, dir=str(d),
                when=time.strftime('%Y-%m-%d %H:%M', time.localtime((d / '_affine.mat').stat().st_mtime)))


# --------------------------------------------------------------------------- #
#  DRIVER
# --------------------------------------------------------------------------- #
def run_hcr_centroid_registration(full_manifest, round_to_rounds, reference_round, gcfg, lcfg, ds,
                                  choose_global=None, confirm_overwrite=None):
    """Compute global+local centroid registration for every mov round, write candidates into
    the existing registrations/ layout, and return a per-round ranked summary:

        { round: {
            'global_tag','radius_um','A','global_table' (EVERY radius, each with tag/dir/composite),
            'global_index','global_suggested',
            'candidates': [ {'tag','local_tag','blocksize','medResid_um','frac_under5',
                             'moved','total','dir','composite'} ... ranked best-first ],
        } }

    Every coarse radius AND every fine blocksize is written to disk and left there; the metrics
    only ever *suggest*. `choose_global(rnd, ref, gtable, suggested_idx) -> idx` is called after
    the coarse composites are on disk and the table is printed, so a human can open the tiffs and
    answer with an index. Leave it None (notebooks, sweeps, unattended runs) to take the suggestion.
    The coarse pick is asked BEFORE the fine stage because the deform is seeded by that affine and
    is the expensive step -- picking after the fact would mean recomputing it.

    `confirm_overwrite(rnd, ref, done) -> bool` is called for any round that is ALREADY registered
    (see completed_round), before its masks are loaded. Return False to keep the existing outputs
    and move on; that round comes back as {'skipped': True, 'tag': <existing>} so the caller can
    carry its selection forward unchanged. Leave it None to recompute every round unconditionally.

    Selection of the fine winner + manifest write-back is done by the caller (register_rounds).
    """
    out_root = output_root(full_manifest) / 'HCR'
    cellpose_dir = out_root / 'cellpose'
    # Two clearly-labeled group folders for the QC composites; ALL generation info is in the
    # filename (round, global tag, local tag) -- no per-candidate scatter, no vague "summary".
    comp_global = out_root / 'registrations' / 'composites' / 'global'
    comp_local = out_root / 'registrations' / 'composites' / 'local'
    comp_global.mkdir(parents=True, exist_ok=True)
    comp_local.mkdir(parents=True, exist_ok=True)
    ref = reference_round['round']
    results = {}
    _print_ladder(round_to_rounds, ref, gcfg, lcfg, unattended=choose_global is None)

    for ri, (rnd, mov_round) in enumerate(round_to_rounds.items(), 1):
        rprint(f"\n[bold cyan]── HCR{rnd} → HCR{ref}  ({ri}/{len(round_to_rounds)}) "
               f"{'─' * max(0, 40 - len(str(rnd)) - len(str(ref)))}[/bold cyan]")
        rfolder = get_round_folder_name(rnd, ref)

        # Ask BEFORE overwriting a round that is already registered, and before the expensive
        # mask load. Answering "keep" leaves every output untouched and moves to the next round.
        done = completed_round(full_manifest, out_root, rfolder, rnd)
        if done is not None and confirm_overwrite is not None and not confirm_overwrite(rnd, ref, done):
            rprint(f"  [green]kept existing registration[/green] — nothing recomputed")
            results[rnd] = dict(skipped=True, tag=done['tag'], dir=done['dir'],
                                global_tag=done['tag'].split('/')[0], candidates=[],
                                severity=0, flags=[])
            continue

        # Both masks come from cellpose/, which by convention holds each round in its own
        # acquired frame; the reference-warped copies live in cellpose_aligned/ and are not
        # what this step wants. _load_round_data checks each mask against its own raw image,
        # which is the real guarantee -- the folder says which frame, the assert proves it.
        fix_mask = cellpose_dir / f"{get_round_folder_name(ref, ref)}_masks.tiff"
        mov_mask = cellpose_dir / f"{get_round_folder_name(rnd, ref)}_masks.tiff"
        missing = [p for p in (fix_mask, mov_mask) if not Path(p).exists()]
        if missing:
            rprint(f"  [red]MISSING {missing} -- skipping HCR{rnd}[/red]")
        else:
            S = _load_round_data(reference_round, mov_round, fix_mask, mov_mask, ds)
            nfix, nmov = len(S['fix_cent']), len(S['mov_cent'])
            fy, fx, fz = S['fix_full'].shape; my, mx, mz = S['mov_full'].shape
            rprint(f"  data: fix {fy}×{fx}×{fz} ([b]{nfix}[/b] nuclei) · "
                   f"mov {my}×{mx}×{mz} ([b]{nmov}[/b] nuclei)")

            # ---- GLOBAL (sweep radii; EVERY one persisted, then suggested/chosen) ----
            def _emit_global(row, aligned, _rf=rfolder):
                """Persist one coarse candidate the moment it is scored: its own _affine.mat dir
                (so it is selectable later) + a QC composite reusing the MI warp. Stamps the paths
                onto the row. Nothing is discarded for losing the MI comparison."""
                tag = _global_tag(row['radius_um'], gcfg['match_threshold'],
                                  row.get('angle_deg', 0.0))
                gd = out_root / 'registrations' / _rf / tag
                gd.mkdir(parents=True, exist_ok=True)
                np.savetxt(str(gd / "_affine.mat"), row['A'])
                comp = comp_global / f"{_rf}__{tag}.tiff"
                try:
                    _write_composite(S['fix_lo'], S['mov_lo'], S['lo_sp_f'], S['lo_sp_m'],
                                     [row['A']], comp, aligned=aligned)
                except Exception as e:
                    rprint(f"      [yellow]coarse composite r{row['radius_um']}µm failed: "
                           f"{type(e).__name__}: {e}[/yellow]")
                    comp = None
                row['tag'] = tag; row['dir'] = str(gd)
                row['composite'] = str(comp) if comp else None

            gtable, sug_i = global_centroid(S, gcfg, emit=_emit_global)
            rprint(f"  [cyan][1/2] COARSE[/cyan]  {len(gtable)} context window(s) tried, "
                   f"all saved — suggested pick by [b]mi[/b]")
            rprint(f"      {'#':>3}  {'radius':>7}{'above':>8}{'n_mut':>8}{'medResid':>10}{'MI':>9}")
            for i, row in enumerate(gtable):
                mark = "  [b]◄ suggested[/b]" if i == sug_i else ""
                mr = row['med_resid'] if row['med_resid'] == row['med_resid'] else float('nan')
                rprint(f"      {i:>3}  {str(int(row['radius_um']))+'µm':>7}{row['above_chance']:>8}"
                       f"{row['n_mut']:>8}{mr:>10.2f}{row['mi']:>+9.3f}{mark}")
            rprint("      [dim]overlay images (open these before choosing):[/dim]")
            for i, row in enumerate(gtable):
                rprint(f"      [dim]  [{i}] {row['composite'] or '(write failed)'}[/dim]")

            # Advisory, not a filter: the caller may block here for a human pick. Default = suggestion.
            gi = sug_i if choose_global is None else choose_global(rnd, ref, gtable, sug_i)
            picked = gtable[gi]
            A_g, r_best, gtag = picked['A'], picked['radius_um'], picked['tag']
            gdir = Path(picked['dir'])
            if gi != sug_i:
                rprint(f"      [yellow]using row {gi} ({int(r_best)}µm) instead of the "
                       f"suggested row {sug_i}[/yellow]")

            g_sev, g_msgs = _assess_global(picked, nfix, nmov)
            if g_sev == 0:
                rprint(f"      {_sev_badge(0)} locked: {picked['n_mut']} mutual inliers "
                       f"({100*picked['n_mut']/max(1,min(nfix,nmov)):.0f}% of cells), residual {picked['med_resid']:.1f}µm")
            _print_msgs(g_sev, g_msgs)

            # RESUME fingerprint: mask identity (size+mtime, changes on re-seg) + the global affine.
            # A match -> reuse the cached deform.zarr and skip the expensive align; any change -> recompute.
            def _mfp(p):
                st = Path(p).stat(); return f"{st.st_size}:{int(st.st_mtime)}"
            round_fp = (f"{_mfp(fix_mask)}|{_mfp(mov_mask)}|"
                        f"aff:{hashlib.md5(np.asarray(A_g).round(6).tobytes()).hexdigest()[:12]}")

            # ---- LOCAL (sweep blocksizes; best by MI) ----
            nbs = len(lcfg['blocksize'])
            # Plain language only. This used to read "N tile size(s) (large->small; deform reused
            # when mask+coarse unchanged)", which named an iteration order that is meaningless with
            # one block size and stated a caching RULE the reader cannot act on. The reuse FACT is
            # reported by the result line below, which appends "(reused)" when it actually happens.
            _bl = ', '.join('×'.join(str(int(v)) for v in b) for b in lcfg['blocksize'])
            rprint(f"  [cyan][2/2] FINE[/cyan]  local warps · block size {_bl}")
            candidates = []
            # No progress bar over the tile sizes: each is ONE long opaque bigstream align (the bar
            # would just sit at 0% then jump). Print a 'computing' line so it's clearly still running.
            for bi, bs in enumerate(lcfg['blocksize'], 1):
                ltag = _local_tag(bs, lcfg)
                ldir = gdir / ltag
                bstr = '×'.join(str(int(v)) for v in bs)
                lcomp = comp_local / f"{rfolder}__{gtag}__{ltag}.tiff"
                _n = f"{bi}/{nbs} " if nbs > 1 else ""      # the counter is noise when there is one
                rprint(f"      computing local warp {_n}(block size {bstr})…")
                try:
                    m = local_centroid_one(S, A_g, bs, lcfg, ldir, fingerprint=round_fp,
                                           overlay_tiff=lcomp)
                except Exception as e:
                    rprint(f"      [red]bs{bstr} ({bi}/{nbs}) failed: {type(e).__name__}: {e}[/red]")
                    continue
                # composite (overlay_warped.tiff) is written inside local_centroid_one
                candidates.append(dict(tag=f"{gtag}/{ltag}", local_tag=ltag, blocksize=bs,
                                       dir=str(ldir), composite=str(lcomp), **m))
                tag = "  [dim](reused)[/dim]" if m.get('reused') else ""
                rprint(f"      bs{bstr:<11} MI [b]{m['mi']:+.3f}[/b]  resid(mutual) {m['medResid_um']:.2f}µm  "
                       f"frac<5 {m['frac_under5']*100:.0f}%  n_mut {m.get('n_mut','?')}  "
                       f"coverage {100*m['moved']/max(1,m['total']):.0f}%  [dim](all-cells {m['medResid_allcells']:.1f}µm)[/dim]{tag}")
            candidates.sort(key=lambda c: c['mi'] if c['mi'] == c['mi'] else float('inf'))   # best MI first

            # ---- per-round VERDICT: best score + combined red-flag assessment ----
            best = candidates[0] if candidates else None
            l_sev, l_msgs = _assess_local(best, picked['med_resid'])
            if best is not None:
                bstr = '×'.join(str(int(v)) for v in best['blocksize'])
                rprint(f"      best: [b]bs{bstr}[/b] → MI {best['mi']:+.3f}, mutual-inlier residual {best['medResid_um']:.2f}µm, "
                       f"{best['frac_under5']*100:.0f}% within 5µm, {100*best['moved']/max(1,best['total']):.0f}% coverage "
                       f"[dim](all-cells {best['medResid_allcells']:.1f}µm)[/dim]")
                if best['mi'] == best['mi'] and picked['mi'] == picked['mi']:   # both non-NaN
                    d_mi = best['mi'] - picked['mi']                            # more negative = better
                    verb = "improved" if d_mi < 0 else "worsened"
                    rprint(f"      MI coarse→fine: {picked['mi']:+.3f} → {best['mi']:+.3f} "
                           f"(Δ {d_mi:+.3f}, deform {verb} the fit)")
                rprint(f"      [dim]↳ overlay image: {best['composite']}[/dim]")
            _print_msgs(l_sev, l_msgs)
            sev = max(g_sev, l_sev)
            rprint(f"  VERDICT HCR{rnd} → HCR{ref}: {_sev_badge(sev)}"
                   + ("" if sev == 0 else f"  ([dim]coarse {_SEV[g_sev][2]} · fine {_SEV[l_sev][2]}[/dim])"))

            results[rnd] = dict(global_tag=gtag, radius_um=r_best, table=gtable, A=A_g,
                                angle_deg=gtable[gi].get('angle_deg', 0.0) if gtable else 0.0,
                                global_table=gtable, global_index=gi, global_suggested=sug_i,
                                candidates=candidates, severity=sev,
                                flags=[f"global: {m}" for m in g_msgs] + [f"local: {m}" for m in l_msgs])
    return results
