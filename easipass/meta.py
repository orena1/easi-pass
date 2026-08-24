import os
import sys
import hjson
import numpy as np
from pathlib import Path

# Rich-compat shim. All pipeline modules import rprint / track / Prompt from
# here so the fallback lives in one place. If rich isn't installed (e.g. a
# stripped-down notebook env), modules still import cleanly and lose only
# the Rich markup formatting.
try:
    from rich import print as rprint
    from rich.progress import track
    from rich.prompt import Prompt
except ImportError:
    rprint = print

    def track(iterable, *args, **kwargs):
        return iterable

    class Prompt:
        @staticmethod
        def ask(prompt, choices=None, default=None, **kwargs):
            # Mirror rich's Prompt.ask: SHOW the options and the default, and keep asking
            # until the answer is one of them. Previously `choices` was accepted and then
            # ignored, so without rich the user saw a bare prompt with no hint of the valid
            # answers, and a typo was returned verbatim -- landing in whatever the caller's
            # else-branch did (at the automation checkpoint, silently skipping the plane).
            suffix = f" [{'/'.join(choices)}]" if choices else ""
            if default is not None:
                suffix += f" ({default})"
            while True:
                ans = input(f"{str(prompt)}{suffix}: ").strip()
                if not ans and default is not None:
                    return default
                if not choices or ans in choices:
                    return ans
                print(f"  Please enter one of: {', '.join(choices)}")


def flush_input():
    """Discard anything already typed at the terminal. Call immediately before a blocking
    review prompt.

    Why this is needed: the stages between two review prompts are long and silent (one
    piecewise deform runs ~15 min printing nothing), which invites people to tap Enter to
    check the run is still alive. Those newlines sit in the tty buffer and are swallowed
    instantly by the NEXT input(), so the following prompt appears to never happen -- it
    returns '' and silently takes the default. Flushing first means every review prompt
    actually stops and waits for a fresh answer.

    No-op when stdin is not a tty, so piped/scripted runs keep their supplied input.
    """
    try:
        if not sys.stdin.isatty():
            return
    except Exception:
        return                              # detached/odd stdin: nothing safe to flush
    try:
        import termios                      # POSIX -- the pipeline runs on Linux
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        try:
            import msvcrt                   # Windows
            while msvcrt.kbhit():
                msvcrt.getwch()
        except Exception:
            pass                            # can't flush here; the prompt still works


def parse_json(json_file):
    """
    Parse a json/hjson manifest. Normalizes base_path slashes so the same
    manifest works whether loaded on Linux (/mnt/...) or Windows (\\...), and
    resolves a relative base_path against the manifest's own directory so a
    manifest can sit beside its data and travel with it.
    """
    with open(json_file, 'r') as f:
        manifest = hjson.load(f)

    # `sample_name` is the general spelling; `mouse_name` is what the lab's
    # manifests use and what the code reads throughout. Accept either.
    data = manifest.get('data', {})
    if 'sample_name' in data and 'mouse_name' not in data:
        data['mouse_name'] = data['sample_name']

    bp = manifest.get('data', {}).get('base_path')
    if isinstance(bp, str):
        bp = bp.replace('\\', '/')
        # Checked explicitly rather than with Path.is_absolute(): on Windows a
        # POSIX path like /mnt/nasquatch/... has no drive and would be reported
        # as relative, which would silently rewrite every lab manifest.
        is_absolute = bp.startswith('/') or (len(bp) > 1 and bp[1] == ':')
        if not is_absolute:
            bp = (Path(json_file).resolve().parent / bp).resolve().as_posix()
        manifest['data']['base_path'] = bp
    return manifest


def output_root(full_manifest) -> Path:
    """Pipeline OUTPUT directory: base_path / mouse_name / OUTPUT."""
    data = full_manifest['data']
    return Path(data['base_path']) / data['mouse_name'] / 'OUTPUT'
    
def user_input_missing(check_results, message, color):
    """Prompt if any path in check_results is missing.

    check_results rows are (path, exists). The exists flag is recomputed here
    rather than trusted: callers build these with np.array([[path, bool]]),
    which numpy coerces to a string array, turning False into the truthy
    'False' and making the comparison silently never match. Re-statting also
    makes 'check-again' do something -- it previously re-printed the same
    cached list forever.
    """
    paths = [str(row[0]) for row in check_results]
    while True:
        missing = [p for p in paths if not os.path.exists(p)]
        if not missing:
            return
        print("Missing:")
        for p in missing:
            print(f"  {p}")
        # The message carries rich markup, so it goes through rprint; only the bare label is
        # handed to Prompt.ask (the no-rich fallback would print the tags literally).
        # Spell out what each answer DOES -- 'y' here continues the run with these files
        # absent, which is the consequential one and was never stated.
        rprint(f"\n[italic {color}]{message}[/italic {color}]")
        rprint("  [green]y[/green]           = continue anyway, without these files")
        rprint("  [red]n[/red]           = stop now")
        rprint("  [yellow]check-again[/yellow] = re-check these paths (add the files first, then choose this)")
        out = Prompt.ask("Your choice", choices=["y", "n", "check-again"])
        if out == 'n':
            sys.exit()
        if out == 'y':
            return

def verify_manifest(manifest, args):
    '''
    Verify that the json file is valid
    '''

    if 'cellpose_channel' not in manifest['params']['HCR_cellpose']:
        raise ValueError("'cellpose_channel' must be specified in HCR_cellpose params. (e.g., 0 for first channel, 1 for second channel).")
    
    if not args.only_hcr and '2p_cellpose' not in manifest['params']:
        raise ValueError("'2p_cellpose' configuration must be specified in params when processing 2P data.")
            
    
    manifest = manifest['data']

    # backward compat: accept old key name
    if 'two_photons_imaging' in manifest and 'two_photon_imaging' not in manifest:
        manifest['two_photon_imaging'] = manifest.pop('two_photons_imaging')

    base_path = Path(manifest['base_path'])
    mouse_name = manifest['mouse_name']

    # A manifest with no functional section can only be an HCR-only run, so
    # infer it rather than asserting and making the user re-issue the command
    # with a flag that carries no information the manifest lacks.
    if not args.only_hcr and 'two_photon_imaging' not in manifest:
        rprint("[dim]No two_photon_imaging section: running FISH rounds only.[/dim]")
        args.only_hcr = True

    # 2P validation only when not in HCR-only mode
    session = None
    has_hires = False
    if not args.only_hcr:
        assert len(manifest['two_photon_imaging']['sessions'])==1, 'only support one 2P sessions'
        session = manifest['two_photon_imaging']['sessions'][0]
        if getattr(args, 'tiff_only', False):
            if session.get('input_format') and session['input_format'] != 'tiff':
                rprint(f"[yellow]--tiff_only: ignoring manifest input_format={session['input_format']!r}[/yellow]")
            session['input_format'] = 'tiff'

        # Required, not defaulted. The historical default was 'sbx', the one
        # format that only works inside the Andermann lab, so a manifest that
        # simply omitted this silently took the least portable path.
        input_format = session.get('input_format')
        if input_format is None:
            raise ValueError(
                "two_photon_imaging.sessions[0].input_format is required. Choose one:\n"
                "  tiff     pre-processed 2P mean images at 2P/plane_{N}.tiff -- the standard path\n"
                "  suite2p  an existing Suite2p output folder\n"
                "  sbx      raw ScanBox .sbx (Andermann-lab internal acquisition format)\n"
                "\n"
                "See examples/demo_tiff.hjson for a complete example.")
        if input_format not in ('tiff', 'suite2p', 'sbx'):
            raise ValueError(
                f"Unknown input_format {input_format!r}. Expected 'tiff', 'suite2p' or 'sbx'.\n"
                "A misspelled value previously fell through to the ScanBox path.")

    #test that reference round exists
    reference_round = manifest['HCR_confocal_imaging']['reference_round']
    for i in manifest['HCR_confocal_imaging']['rounds']:
        if i['round'] == reference_round:
            break
    else:
        raise Exception(f"reference round was not found {reference_round} is not in rounds")

    if not args.only_hcr and input_format == 'tiff':
        # Validate tiff inputs exist
        twop_dir = base_path / mouse_name / '2P'
        planes = session.get('functional_planes', session.get('functional_plane', []))
        for plane in planes:
            tiff_path = twop_dir / f'plane_{plane}.tiff'
            if not tiff_path.exists():
                raise FileNotFoundError(f"Expected 2P tiff input not found: {tiff_path}")
            # Detect pre-stitched hires from presence of plane_{N}_hires.tiff
            if (twop_dir / f'plane_{plane}_hires.tiff').exists():
                has_hires = True

    elif not args.only_hcr and input_format == 'suite2p':
        # Validate suite2p folder exists
        suite2p_path = base_path / mouse_name / '2P' / 'suite2p' / 'plane0' / 'ops.npy'
        user_input_missing(np.array([[suite2p_path, os.path.exists(suite2p_path)]]), 'Suite2p path is missing, do you wish to continue?', color='pink')

    elif not args.only_hcr:
        # Default SBX mode — original validation
        date_two_photons = session['date']
        check_results = []
        for k in session:
            if '_run' in k:
                for run in session[k]:
                    run_path_sbx = base_path / mouse_name / '2P' /  f'{mouse_name}_{date_two_photons}_{run}' / f'{mouse_name}_{date_two_photons}_{run}.sbx'
                    check_results.append([run_path_sbx,os.path.exists(run_path_sbx)])
        check_results = np.array(check_results)
        user_input_missing(check_results, 'Some 2p runs are missing, do you wish to continue?', color='red')

        # verify that functional run exists.
        suite2p_run = session['functional_run'][0]
        suite2p_path = base_path / mouse_name / '2P' /  f'{mouse_name}_{date_two_photons}_{suite2p_run}' / 'suite2p' /'plane0/ops.npy'
        user_input_missing(np.array([[suite2p_path, os.path.exists(suite2p_path)]]), 'Suite2p path is missing, do you wish to continue?', color='pink')

    # Verify anatomical runs configuration. Hires tile stitching from raw
    # sbx tiles is orthogonal to the functional input source — it runs for
    # both sbx and suite2p modes whenever anatomical_hires_*_runs are
    # declared. Tiff mode skips sbx-based stitching entirely (users supply
    # a pre-stitched plane_{N}_hires.tiff instead) and has_hires is set
    # above based on that file's presence.
    if not args.only_hcr and input_format != 'tiff':
        has_lowres_green = len(session.get('anatomical_lowres_green_runs', [])) > 0
        has_hires_green = len(session.get('anatomical_hires_green_runs', [])) > 0

        if has_hires_green:
            assert not has_lowres_green, "Cannot have both lowres and hires runs"
            assert len(session['anatomical_hires_green_runs'])==len(session['anatomical_hires_red_runs']), "Number of hires green and red runs do not match"
            has_hires = True
            # Validate hires tile .sbx files exist (suite2p mode skips sbx
            # validation above but still needs the tile sbx files for stitching)
            if input_format == 'suite2p':
                date_two_photons = session.get('date')
                if date_two_photons:
                    tile_check = []
                    for run in session['anatomical_hires_green_runs'] + session['anatomical_hires_red_runs']:
                        tile_sbx = base_path / mouse_name / '2P' / f'{mouse_name}_{date_two_photons}_{run}' / f'{mouse_name}_{date_two_photons}_{run}.sbx'
                        tile_check.append([tile_sbx, os.path.exists(tile_sbx)])
                    user_input_missing(np.array(tile_check), 'Some hires tile sbx files are missing, do you wish to continue?', color='red')
        elif has_lowres_green:
            assert len(session['anatomical_lowres_green_runs'])==len(session['anatomical_lowres_red_runs']), "Number of lowres green and red runs do not match"
        # else: no anatomical runs — lowres mode using Suite2p mean image only

    # verify that unwarp_config exists (only needed for high-res workflow)
    if has_hires and 'unwarp_config' in session:
        if not os.path.exists(session['unwarp_config']):
            new_path = base_path / 'Calibration_files_for_unwarping' / session['unwarp_config']
            if not os.path.exists(new_path):
                raise Exception(f"unwarp config file does not exist {session['unwarp_config']} and not in {new_path}")
            session['unwarp_config'] = new_path

    return {'reference_round':reference_round, 'session':session}, has_hires

def main_pipeline_manifest(json_file):
    """
    Parse the pipeline manifest json file and verify that the required fields are present
    """
    manifest = parse_json(json_file)
    manifest['manifest_path'] = json_file
    required_fields = ['base_path', 'mouse_name']
    for field in required_fields:
        if field not in manifest['data']:
            raise ValueError(f"Required field {field} not found in pipeline manifest")
    
    # ToDo, add more checks here

    return manifest

def get_automation_config(params):
    """
    Get automation config with sensible defaults.

    If 'automation' section is missing, defaults to manual (backward compatible).

    Config options (all use 'auto' or 'manual'):
    - twop_to_hcr: 'auto' or 'manual'
        - 'manual' (default): User-provided BigWarp landmarks only
        - 'auto': Automated registration refinement (still requires manual landmarks as starting point)
    - lowres_to_hires: 'auto' or 'manual'
        - 'manual' (default): User-provided BigWarp landmarks + TPS
        - 'auto': Automated SIFT feature matching + RANSAC affine
    - stitching: 'auto' or 'manual'
        - 'manual' (default): User-provided BigStitcher coordinates
        - 'auto': Automated SIFT + phase correlation stitching
    """
    automation = params.get('automation', {})
    return {
        'twop_to_hcr': automation.get('twop_to_hcr', 'manual'),
        'lowres_to_hires': automation.get('lowres_to_hires', 'manual'),
        'stitching': automation.get('stitching', 'manual'),
    }

def check_rotation(manifest):
    manifest = parse_json(manifest['manifest_path'])
    # Support both old and new name
    if 'rotation_2p_to_HCR' in manifest['params'] or 'rotation_2p_to_HCRspec' in manifest['params']:
        return True
    else:
        return False


# =============================================================================
# Parameter accessor functions (with backward compatibility)
# =============================================================================

def get_rotation_config(params):
    """Get rotation/coordinate transform config. Supports old and new names."""
    # New name first, fall back to old
    return params.get('rotation_2p_to_HCR', params.get('rotation_2p_to_HCRspec', {}))


def get_hcr_to_hcr_registration_config(params):
    """
    Get HCR-to-HCR registration config. Supports old and new names/formats.

    Returns dict with 'downsampling' as [x, y, z] array.
    """
    # Try new name first
    config = params.get('HCR_to_HCR_registration', {})
    if config:
        # New format: downsampling as array
        if 'downsampling' in config:
            return config
        # Old field names in new location
        return {
            'downsampling': [
                config.get('red_mut_x', 3),
                config.get('red_mut_y', 3),
                config.get('red_mut_z', 2)
            ]
        }

    # Fall back to old name (HCR_to_HCR_params)
    old_config = params.get('HCR_to_HCR_params', {})
    return {
        'downsampling': [
            old_config.get('red_mut_x', 3),
            old_config.get('red_mut_y', 3),
            old_config.get('red_mut_z', 2)
        ]
    }


def get_stitching_config(params):
    """Get stitching config. Supports old and new names."""
    # New name first, fall back to old
    return params.get('stitching', params.get('auto_stitch_params', {}))


def get_intensity_extraction_config(params):
    """Get intensity extraction config. Supports old and new names."""
    # New name first, fall back to old
    return params.get('intensity_extraction', params.get('HCR_probe_intensity_extraction', {}))


def get_round_folder_name(round_num: int, reference_round_num: int) -> str:
    """Get the folder name for an HCR round based on whether it's the reference.

    Args:
        round_num: The HCR round number
        reference_round_num: The reference HCR round number

    Returns:
        "HCR{N}" for reference round, "HCR{N}_to_HCR{ref}" for other rounds
    """
    if round_num == reference_round_num:
        return f"HCR{round_num}"
    return f"HCR{round_num}_to_HCR{reference_round_num}"


