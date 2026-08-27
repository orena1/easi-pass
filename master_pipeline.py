import argparse
from pathlib import Path

try:
    from easipass import functional as fc
    from easipass import tiling as tl
    from easipass import registrations as rf
    from easipass import registrations_landmarks as rf_landmarks
    from easipass import meta as mt
    from easipass import segmentation as sg
    from easipass import importers as im
    from easipass.meta import rprint
except ImportError as exc:
    # Each easipass module falls back to a flat import so it can also be used from a
    # notebook. That fallback masks the real cause: a missing third-party package
    # surfaces as "No module named 'registrations'" (or 'functional', or 'meta'),
    # which are internal modules and not the problem. Work out what is actually
    # absent and say so, rather than handing the user another command to run.
    import os
    import sys
    import importlib.util

    # Keep this in sync with what easipass/*.py actually imports at module level. An omission
    # here is not harmless: the package's flat-import fallbacks turn ANY failure inside a module
    # into "No module named '<internal module>'", so a package missing from this list produces a
    # message that names an internal module and sends the user looking in the wrong place.
    # tqdm / pystackreg / distributed were missing until 2026-08-25 and did exactly that.
    _REQUIRED = ['numpy', 'scipy', 'pandas', 'skimage', 'tifffile', 'cv2', 'SimpleITK',
                 'cellpose', 'matplotlib', 'hjson', 'zarr', 'sklearn', 'numba',
                 'dask', 'distributed', 'bigstream', 'ClusterWrap', 'sbxreader', 'suite2p',
                 'tqdm', 'pystackreg']
    _missing = [m for m in _REQUIRED if importlib.util.find_spec(m) is None]

    # If the failure names one of OUR OWN modules, a flat-import fallback fired and the real
    # cause is hidden. Import the leaf modules directly, in dependency order, to surface it --
    # meta and registrations_utils have the fewest fallbacks, so the true error appears there.
    _INTERNAL = {'meta', 'registrations', 'registrations_utils', 'registrations_landmarks',
                 'functional', 'tiling', 'segmentation', 'importers', 'automation',
                 'auto_stitching', 'bigstream_functions', 'somaprint', 'somaprint_hcr',
                 'hcr_centroid_registration', 'analysis_utils'}
    _real = None
    if getattr(exc, 'name', None) in _INTERNAL:
        for _leaf in ('easipass.meta', 'easipass.registrations_utils', 'easipass.registrations',
                      'easipass.functional', 'easipass.tiling', 'easipass.segmentation'):
            try:
                importlib.import_module(_leaf)
            except Exception as _e2:          # noqa: BLE001 - reporting, not handling
                _real = f"{_leaf}: {type(_e2).__name__}: {_e2}"
                break
    # VIRTUAL_ENV first: a venv activated inside a conda env shadows it on PATH,
    # so it is the one actually in use, and naming the conda env instead sends
    # the reader to the wrong place.
    _env = os.environ.get('VIRTUAL_ENV') or os.environ.get('CONDA_DEFAULT_ENV') or '(none)'

    _lines = ["EASI-PASS could not start: %s" % exc, ""]
    if len(_missing) > 3:
        # Wholesale absence: this is the wrong interpreter, not a broken install.
        _lines += [
            "Nothing is installed in this environment, so this is almost certainly the",
            "wrong one. Active environment: %s" % _env,
            "",
            "    source .venv/bin/activate      # or wherever you created it",
            "    conda env list                 # if you used conda; active is marked *",
            "",
            "If you have not installed EASI-PASS yet, from the repository root,",
            "whichever of these you already have:",
            "",
            "    conda env create -f environment.yml && conda activate easipass",
            "    pip install -e . -c requirements.txt",
            "",
            "    uv venv --python 3.12 && source .venv/bin/activate",
            "    uv pip install -e . -c requirements.txt",
        ]
    elif _missing:
        _lines += [
            "Active environment: %s" % _env,
            "Missing dependencies: %s" % ", ".join(_missing),
            "",
            "Reinstall them with, from the repository root:",
            "",
            "    uv pip install -e . -c requirements.txt",
        ]
    elif _real:
        # Everything on the list is present, but an internal module still failed to import. The
        # message above names an internal module only because a fallback fired; this is the cause.
        _lines += [
            "Active environment: %s" % _env,
            "Interpreter: %s" % sys.executable,
            "",
            "The name above is one of EASI-PASS's own modules, which means the real error was",
            "masked by a flat-import fallback. The actual failure is:",
            "",
            "    %s" % _real,
            "",
            "If that names a third-party package, install it and add it to _REQUIRED in",
            "master_pipeline.py so the next person gets told directly:",
            "",
            "    uv pip install -e . -c requirements.txt",
        ]
    else:
        _lines += [
            "Every dependency is importable, so this is not a missing package.",
            "Active environment: %s" % _env,
            "Interpreter: %s" % sys.executable,
            "",
            "Run from the repository root, so that the easipass package next to",
            "master_pipeline.py is the one that gets imported.",
        ]
    raise SystemExit("\n".join(_lines) + "\n") from exc

# This is the main pipeline script that runs the entire pipeline

# https://drive.google.com/file/d/1HZNh7aqJr-vTsLsSGlFmi11HuEvYlgZ-/view?usp=sharing

def _parse_args(argv=None):
    '''
    Build the CLI and parse it. Kept separate from main() so the `easipass`
    console-script entry point can parse its own arguments -- setuptools calls
    main() with no arguments, which previously left args as None.
    '''
    parser = argparse.ArgumentParser(
        prog='easipass',
        description='EASI-PASS: 2-photon to HCR registration and mask matching pipeline.')
    parser.add_argument('--manifest', required=True,
                        help='Path to the pipeline manifest file, e.g. examples/demo_tiff.hjson')
    parser.add_argument('--only_hcr', action='store_true',
                        help='FISH rounds + segmentation only; skip the functional side. '
                             'Inferred automatically when the manifest has no two_photon_imaging '
                             'section; pass it explicitly to skip the 2P half of a full manifest.')
    parser.add_argument('--check_alignment', action='store_true',
                        help='Stop after registering and matching 2P to the reference FISH round. '
                             'Later rounds need not be acquired yet; re-run without the flag to finish.')
    # How the functional side is read is a property of the data, so it lives in
    # the manifest as input_format. Accepted silently so old commands still run.
    parser.add_argument('--tiff_only', action='store_true', help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.check_alignment and args.only_hcr:
        parser.error('--check_alignment aligns 2P to FISH, which --only_hcr excludes')
    if args.tiff_only:
        rprint("[yellow]--tiff_only is no longer needed: set input_format: \"tiff\" in the "
               "manifest session instead. Continuing with tiff.[/yellow]")
    return args


def _print_resolved_config(full_manifest, args, has_hires):
    '''
    Echo what the manifest and flags actually resolved to, before any work
    starts. The mode is otherwise implicit: a manifest silently decides how the
    functional side is read and whether a hi-res bridge was found, and both are
    easy to get wrong in ways that only surface much later as a confusing
    failure. Cheap to print, and it is the first thing to check in a bug report.
    '''
    data = full_manifest['data']
    rounds = data['HCR_confocal_imaging']['rounds']
    ref = data['HCR_confocal_imaging']['reference_round']

    rprint("\n[bold]Resolved configuration[/bold]")
    rprint(f"  sample          {data['mouse_name']}")
    rprint(f"  base path       {data['base_path']}")

    if args.only_hcr:
        rprint("  functional      [dim]none (--only_hcr)[/dim]")
    else:
        session = data['two_photon_imaging']['sessions'][0]
        planes = session.get('functional_planes', session.get('functional_plane', []))
        fmt = session.get('input_format')
        note = " [dim](forced by --tiff_only)[/dim]" if getattr(args, 'tiff_only', False) else ""
        lab_only = " [yellow](in-lab ScanBox format)[/yellow]" if fmt == 'sbx' else ""
        rprint(f"  functional      {fmt}{note}{lab_only}, {len(planes)} plane(s): {', '.join(map(str, planes))}")
        rprint(f"  hi-res bridge   {'yes' if has_hires else 'no'}")

    rprint(f"  FISH rounds     {len(rounds)} ({', '.join(str(r['round']) for r in rounds)}), reference {ref}")
    if len(rounds) == 1:
        rprint("                  [dim]single round: no round-to-round registration[/dim]")
    rprint("")


def main(args = None):
    '''
    We can either start main with arguments or from command line
    See README.md for more information
    '''
    if args is None:
        args = _parse_args()

    session = []

    # Parse the manifest file
    full_manifest = mt.main_pipeline_manifest(args.manifest)
    full_manifest['check_alignment'] = getattr(args, 'check_alignment', False)
    specs, has_hires = mt.verify_manifest(full_manifest, args)

    if args.only_hcr:
        rprint("[bold cyan]FISH rounds + segmentation[/bold cyan]")
    else:
        rprint("[bold cyan]in vivo 2P -> ex vivo volume alignment[/bold cyan]")
    if full_manifest['check_alignment']:
        rprint("[bold cyan]Alignment check: reference FISH round only, stopping after 2P-FISH matching[/bold cyan]")

    _print_resolved_config(full_manifest, args, has_hires)

    # Get automation config (defaults to 'manual' if not specified)
    automation = mt.get_automation_config(full_manifest.get('params', {}))
    if automation['twop_to_hcr'] == 'auto':
        rprint(f"[bold cyan]Automation enabled:[/bold cyan] twop_to_hcr={automation['twop_to_hcr']}")

    # Publish the reference HCR volume up front. It is the acquired stack verbatim,
    # so it costs a file copy, and it is one of the two images BigWarp opens.
    rf.publish_reference_round(full_manifest)

    if args.only_hcr:
        # HCR-only has no cross-modal landmark step, so nothing is gained by
        # deferring segmentation here -- keep the original order.
        sg.run_cellpose(full_manifest)
        rf.register_rounds(full_manifest)
        rf.align_masks_to_reference(full_manifest)
        sg.extract_probe_intensity(full_manifest)

        # For HCR-only mode, just do align_masks and merge
        sg.align_masks(full_manifest, session, only_hcr=True, reference_plane=None)
        # Hybrid HCR↔HCR matcher (best-plane IoU overlap + soma repair); augments
        # the per-round CSVs so merge uses the consensus pick (no-op if disabled).
        sg.align_somaprint_hcr(full_manifest, session, only_hcr=True)
        sg.merge_masks(full_manifest, session, only_hcr=True)

    else:
        # TODO: Refactor plane iteration - currently we copy session and mutate
        # functional_plane each iteration, while functions also read from the original
        # manifest to get reference_plane. This works but is confusing. Consider passing
        # current_plane and reference_plane as explicit parameters instead.
        session = full_manifest['data']['two_photon_imaging']['sessions'][0].copy()

        # Get all planes to process
        # Support both old and new manifest formats
        if 'functional_planes' in session:
            # New format: all planes in one list
            all_planes = list(session['functional_planes'])
        else:
            # Old format: functional_plane + optional additional_functional_planes
            all_planes = list(session['functional_plane'])
            if 'additional_functional_planes' in session:
                all_planes.extend(session['additional_functional_planes'])

        # First plane is the reference (used for HCR alignment and landmarks)
        reference_plane = all_planes[0]

        # --- Prep: mode-dispatched, no segmentation. Produces the 2P images the
        # landmark step opens (stitching for sbx, a copy + rotate for tiff).
        for plane in all_planes:
            session['functional_plane'] = [plane]
            prepare_plane(full_manifest, session, has_hires)

        # Prep may have written a rotation the user chose at the ORIENTATION
        # prompt. functional.py re-reads the manifest from disk before rotating
        # the image, but the mask-side rotation in registrations.py reads this
        # in-memory copy, so without this refresh the landmark grid and the mask
        # grid disagree by exactly the flip the user just asked for.
        full_manifest['params'] = mt.parse_json(full_manifest['manifest_path'])['params']

        # --- Landmarks: the manual step runs before any cellpose. BigWarp works on
        # the 2P mean (or stitched hi-res) against the acquired HCR volume, neither
        # of which is segmented, so making the user sit through cellpose first only
        # delayed the point where a bad alignment becomes visible.
        rf.ensure_twop_to_hcr_landmarks(
            full_manifest, has_hires, int(reference_plane),
            automation_enabled=(automation['twop_to_hcr'] == 'auto'))

        # --- Segmentation. 2P cellpose reads the un-rotated mean image written
        # during prep, so running it here segments exactly what it did before.
        cellpose_seg_files = []
        for plane in all_planes:
            session['functional_plane'] = [plane]
            cellpose_seg_files.append((plane, im.load_functional_masks(full_manifest, session)))
        sg.verify_2p_cellpose_segmentations(cellpose_seg_files)

        # HCR segmentation, then HCR-HCR registration, then the labels are aligned
        # into the HCR01 frame for matching, then intensities on the acquired rounds.
        sg.run_cellpose(full_manifest)
        rf.register_rounds(full_manifest)
        rf.align_masks_to_reference(full_manifest)
        if not full_manifest['check_alignment']:
            sg.extract_probe_intensity(full_manifest)

        # Now do low-res to high-res registration for ALL planes at once
        # Method depends on automation config: 'landmarks' (default) or 'auto' (SIFT-based)
        if has_hires:
            # This step handles every plane at once, so it needs a session that says so.
            # The copy inherits whatever plane the loop above finished on, which is
            # meaningless here -- both plane keys are set explicitly so a reader of
            # either one gets the reference plane, not the last one segmented.
            session_with_all_planes = session.copy()
            session_with_all_planes['functional_plane'] = [reference_plane]
            if 'functional_planes' not in full_manifest['data']['two_photon_imaging']['sessions'][0]:
                session_with_all_planes['additional_functional_planes'] = [p for p in all_planes if p != reference_plane]

            lowres_method = automation.get('lowres_to_hires', 'manual')
            if lowres_method == 'auto':
                rprint(f"\n[bold cyan]Running automated (SIFT) low-res to high-res registration[/bold cyan]\n")
                rf.register_lowres_to_hires(full_manifest, session_with_all_planes)
            else:
                rprint(f"\n[bold cyan]Running landmark-based low-res to high-res registration[/bold cyan]\n")
                rf_landmarks.register_lowres_to_hires_landmarks(full_manifest, session_with_all_planes)
        else:
            # Standard mode: create rotated masks (in hi-res mode, register_lowres_to_hires does this)
            session_with_all_planes = session.copy()
            session_with_all_planes['functional_plane'] = [reference_plane]
            if 'functional_planes' not in full_manifest['data']['two_photon_imaging']['sessions'][0]:
                session_with_all_planes['additional_functional_planes'] = [p for p in all_planes if p != reference_plane]
            rf.create_rotated_masks_for_standard_mode(full_manifest, session_with_all_planes)

        # Now run 2P-to-HCR registration for each plane (needs transformed masks from above)
        for plane in all_planes:
            session['functional_plane'] = [plane]
            rprint(f"\n[bold yellow]Running 2P→HCR registration for plane {plane}[/bold yellow]\n")
            rf.twop_to_hcr_registration(
                full_manifest, session, has_hires,
                automation_enabled=(automation['twop_to_hcr'] == 'auto')
            )
            input_format = fc._get_input_format(session)
            if input_format not in ('tiff', 'suite2p'):
                sg.extract_electrophysiology_intensities(full_manifest, session)

        # Now align 2P masks to HCR and merge (needs twop_aligned_3d.tiff from above)
        for plane in all_planes:
            session['functional_plane'] = [plane]
            rprint(f"\n[bold yellow]Aligning and merging masks for plane {plane}[/bold yellow]\n")
            # Determine if this is the reference plane
            plane_reference = None if plane == reference_plane else reference_plane
            sg.align_masks(full_manifest, session, only_hcr=args.only_hcr, reference_plane=plane_reference)
            # Augment IoU CSV with somaprint columns (geometric matcher,
            # parallel to IoU; no-op if disabled in manifest).
            sg.align_somaprint(full_manifest, session, only_hcr=args.only_hcr)
            # Hybrid HCR↔HCR matcher → consensus round_{R}_mask. The per-round CSVs
            # are (re)generated only on the reference-plane pass (plane_reference is
            # None), which runs first, so populate them once here; idempotent.
            if plane_reference is None:
                sg.align_somaprint_hcr(full_manifest, session, only_hcr=args.only_hcr)
            if not full_manifest['check_alignment']:
                sg.merge_masks(full_manifest, session, only_hcr=args.only_hcr)

        if not full_manifest['check_alignment']:
            sg.print_match_summary(full_manifest, all_planes)

        rprint('\n' + '='*80)
        if full_manifest['check_alignment']:
            rprint(f"[bold green]Alignment check complete for {full_manifest['data']['mouse_name']}[/bold green]")
            rprint(f"Review the overlays in "
                   f"[yellow]{mt.output_root(full_manifest) / '2P' / 'registered' / 'QualityCheck'}[/yellow]")
            rprint(f"To finish the remaining rounds and build the output tables, re-run without "
                   f"[cyan]--check_alignment[/cyan]")
        else:
            rprint(f"[bold green]Pipeline completed successfully for {full_manifest['data']['mouse_name']}![/bold green]")
        rprint('='*80)


def prepare_plane(full_manifest, session, has_hires):
    """Prepare the 2P images for a single plane, without segmenting anything.

    Everything here is cheap and mode-dispatched, and it is all the landmark step
    needs: tiff mode copies and rotates the user's mean image, suite2p pulls meanImg
    out of ops.npy, sbx runs the tile pipeline. Segmentation is a separate call
    (importers.load_functional_masks) so the manual BigWarp work can happen first.

    Functional lowres mean extraction (driven by input_format) and hires tile
    stitching (driven by has_hires) are orthogonal: any input_format can opt
    into hires stitching by declaring anatomical_hires_*_runs in the manifest.
    """
    plane = session['functional_plane'][0]
    input_format = fc._get_input_format(session)
    rprint(f"\n[bold green]Preparing 2P plane {plane}[/bold green]")

    # 1. Hires tile stitching first (sbx + suite2p modes). Running stitching
    # ahead of the lowres rotation prompt means the user gets a 2-channel
    # (green + red) stitched preview to judge the flip/rotation against HCR.
    # Tiff mode skips here because the user supplies a pre-stitched
    # plane_{N}_hires.tiff which prepare_tiff_input handles.
    if has_hires and input_format != 'tiff':
        tl.process_session_sbx(full_manifest, session)
        tl.unwarp_tiles(full_manifest, session)
        tl.stitch_tiles_and_rotate(full_manifest, session)

    # 2. Functional lowres mean image. If stitching prompted and wrote a
    # *_rotated.tiff above, the lowres rotation step below will skip the
    # prompt and pick up the same rotation_config from the updated manifest.
    # Dispatch lives in src/importers.py (behavior-identical across formats).
    im.load_functional_mean(full_manifest, session)


if __name__ == "__main__":
    main()

