import argparse
from pathlib import Path
from easipass import functional as fc
from easipass import tiling as tl
from easipass import registrations as rf
from easipass import registrations_landmarks as rf_landmarks
from easipass import meta as mt
from easipass import segmentation as sg
from easipass import importers as im
from easipass.meta import rprint

# This is the main pipeline script that runs the entire pipeline

# https://drive.google.com/file/d/1HZNh7aqJr-vTsLsSGlFmi11HuEvYlgZ-/view?usp=sharing

def main(args = None):
    '''
    We can either start main with arguments or from command line 
    See README.md for more information
    '''
    session = []

    # Parse the manifest file
    full_manifest = mt.main_pipeline_manifest(args.manifest)
    full_manifest['check_alignment'] = getattr(args, 'check_alignment', False)
    specs, has_hires = mt.verify_manifest(full_manifest, args)

    if getattr(args, 'tiff_only', False):
        rprint("[bold cyan]in vivo 2P -> ex vivo volume alignment[/bold cyan]")
    elif args.only_hcr:
        rprint("[bold cyan]HCR rounds + segmentation[/bold cyan]")
    if full_manifest['check_alignment']:
        rprint("[bold cyan]Alignment check: reference HCR round only, stopping after 2P-HCR matching[/bold cyan]")

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
            # Temporarily set session to have all planes for registration
            session_with_all_planes = session.copy()
            if 'functional_planes' in full_manifest['data']['two_photon_imaging']['sessions'][0]:
                # Already has functional_planes
                pass
            else:
                # Add additional_functional_planes to session for registration
                session_with_all_planes['functional_plane'] = [reference_plane]
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
            if 'functional_planes' not in full_manifest['data']['two_photon_imaging']['sessions'][0]:
                session_with_all_planes['functional_plane'] = [reference_plane]
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

    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True, help='Path to the pipeline manifest file e.g. examples/CIM132.hjson')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--only_hcr', action='store_true', help='HCR rounds + segmentation only; no 2P data')
    mode.add_argument('--tiff_only', action='store_true',
                      help='Align a pre-processed 2P mean image (TIFF) to an ex vivo volume. '
                           'See examples/demo_tiff_minimal.hjson.')
    parser.add_argument('--check_alignment', action='store_true',
                        help='Stop after registering and matching 2P to the reference HCR round. '
                             'Later rounds need not be acquired yet; re-run without the flag to finish.')

    args = parser.parse_args()
    if args.check_alignment and args.only_hcr:
        parser.error('--check_alignment aligns 2P to HCR, which --only_hcr excludes')
    #args = {'manifest': 'examples/CIM132.hjson'}
    main(args)
    
