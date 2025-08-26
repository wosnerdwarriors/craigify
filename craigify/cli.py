import argparse
import os
from .providers.craig_api import parse_input, get_metadata, get_duration
from .providers.craig_download import run_download_flow
from .storage.paths import build_base_name
from .transcribe.run import run_transcribe_cli
from .summarize.run import run_summarize_cli
import json
import sys
import requests
import importlib.util
import shutil
from string import Template


def _load_config(path: str, explicit: bool = False) -> dict:
    # If user passed explicit path, require it; if default and missing, return empty dict
    if not path:
        return {}
    if not os.path.exists(path):
        if explicit:
            raise SystemExit(f"Config file not found: {path}")
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        if explicit:
            raise SystemExit(f"Failed to read config file: {path}")
        return {}


def add_common(parser: argparse.ArgumentParser):
    parser.add_argument("-i", "--input", required=True, help="Recording URL or ID")
    parser.add_argument("--key", help="Recording key (if not included in URL)")
    parser.add_argument("--output-root", default=os.path.join(os.getcwd(), 'recordings'), help="Root dir for per-recording folders")
    parser.add_argument("--clobber", action="store_true", help="Overwrite if exists")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging (more output)")
    parser.add_argument("--no-cleanup", action="store_true", help="Do not remove intermediate files (keep downloads/work directories)")
    parser.add_argument("--config", default="config.json", help="Path to config.json with API keys and other service settings")
    parser.add_argument("--skip-deps-check", action="store_true", help="Skip preflight dependency checks")


def _check_dependencies(actions: list, args) -> None:
    """Perform a lightweight preflight check for required python packages and binaries.

    actions: list of action names (e.g., ['download','transcribe'])
    args: argparse Namespace with possible namespaced options (we use getattr safely)
    Exits with SystemExit if required deps are missing unless --skip-deps-check is set.
    """
    if getattr(args, 'skip_deps_check', False):
        if getattr(args, 'verbose', False):
            print('[DEPS] Skipping dependency checks (--skip-deps-check set)')
        return

    missing_pkgs = []
    missing_bins = []

    # download action needs requests and ffmpeg binary
    if 'download' in actions:
        if importlib.util.find_spec('requests') is None:
            missing_pkgs.append('requests')
        if shutil.which('ffmpeg') is None:
            missing_bins.append('ffmpeg')

    # transcribe action: choose backend from namespaced options or defaults
    if 'transcribe' in actions:
        backend = getattr(args, 'transcribe_backend', None) or getattr(args, 'backend', None) or 'faster_whisper'
        if backend == 'faster_whisper':
            if importlib.util.find_spec('faster_whisper') is None:
                missing_pkgs.append('faster_whisper')
            if importlib.util.find_spec('torch') is None:
                missing_pkgs.append('torch')
        elif backend == 'whisper':
            if importlib.util.find_spec('whisper') is None:
                missing_pkgs.append('whisper')
            if importlib.util.find_spec('torch') is None:
                missing_pkgs.append('torch')
        elif backend == 'openai':
            if importlib.util.find_spec('openai') is None:
                missing_pkgs.append('openai')

    if missing_pkgs or missing_bins:
        print('\n[DEPS] Preflight dependency check failed:')
        if missing_bins:
            for b in missing_bins:
                print(f'  - Missing binary: {b} (install system package or ensure it is on PATH)')
        if missing_pkgs:
            print('  - Missing python packages:')
            for m in missing_pkgs:
                print(f'      {m}    (pip install {m})')
        print('\n  To bypass this check, re-run with --skip-deps-check')
        raise SystemExit('Missing dependencies')



def cmd_metadata(args):
    rec_id, key = parse_input(args.input)
    key = key or args.key
    if not key:
        raise SystemExit("--key required if not present in URL")
    meta = get_metadata(rec_id, key)
    if not meta.get('duration'):
        dur = get_duration(rec_id, key)
        if dur and dur > 0:
            meta['duration'] = dur
    base = build_base_name(meta)
    summarize_metadata(meta, rec_id)


def _format_duration_hms(seconds: int) -> str:
    try:
        total = int(seconds or 0)
    except Exception:
        total = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def summarize_metadata(meta: dict, rec_id: str | None = None):
    rec = meta.get('recording', {})
    users = meta.get('users', []) or []
    rec_id = rec_id or rec.get('id', 'unknown')
    start = rec.get('startTime', 'Unknown')
    duration = meta.get('duration', 0) or 0
    guild = (rec.get('guild') or {}).get('name', 'Unknown')
    channel = (rec.get('channel') or {}).get('name', 'Unknown')
    print("\n🎙️ Recording Summary:")
    print(f"  ID:        {rec_id}")
    print(f"  Started:   {start}")
    print(f"  Server:    {guild}")
    print(f"  Channel:   {channel}")
    try:
        secs = int(duration)
    except Exception:
        secs = 0
    print(f"  Duration:  {secs} seconds ({_format_duration_hms(secs)})")
    print(f"  Users:     {len(users)}")
    for u in users:
        username = u.get('username') or u.get('name') or u.get('nick') or 'unknown'
        track = u.get('track', '?')
        print(f"    - {username} (track {track})")
    print("")


def _load_template(path: str | None, default_path: str | None = None) -> str:
    # Try explicit path, then default_path, else built-in fallback
    if path and os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            pass
    if default_path and os.path.exists(default_path):
        try:
            with open(default_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            pass
    # fallback minimal template
    return "Recording: ${id}\nStarted: ${start}\nServer: ${server}\nChannel: ${channel}\nDuration: ${duration}\nUsers: ${users}\n"


def _render_message_template(template_str: str, meta: dict) -> str:
    rec = meta.get('recording', {})
    users = meta.get('users', []) or []
    uid_list = ', '.join([u.get('username') or u.get('name') or u.get('nick') or 'unknown' for u in users])
    vals = {
        'id': rec.get('id', 'unknown'),
        'start': rec.get('startTime', 'unknown'),
        'server': (rec.get('guild') or {}).get('name', 'unknown'),
        'channel': (rec.get('channel') or {}).get('name', 'unknown'),
        'duration': meta.get('duration', 0),
        'users': uid_list,
    }
    try:
        return Template(template_str).substitute(vals)
    except Exception:
        # best-effort fallback: return simple summary
        return f"Recording {vals['id']} on {vals['server']}/{vals['channel']} ({vals['duration']}s)"


def _validate_action_requirements(actions: list, args, cfg: dict, meta: dict):
    """Validate that requested actions have required options present (in CLI or config).

    Raises SystemExit with helpful messages when requirements are missing.
    """
    import shutil
    import importlib.util
    from .utils.discord import resolve_bot_token, resolve_channel_id, resolve_webhooks
    errs = []

    # Post action requires either webhooks or bot token + channel
    if 'post' in actions:
        webhooks = resolve_webhooks(getattr(args, 'post_discord_webhook', None), cfg)
        bot_token = resolve_bot_token(getattr(args, 'post_discord_bot_token', None), cfg)
        channel_id = resolve_channel_id(getattr(args, 'post_discord_channel', None), cfg)
        if not webhooks and not (bot_token and channel_id):
            errs.append(
                'post action requested but no webhook aliases/URLs or bot token+channel id found. '
                'Provide --post-discord-webhook or --post-discord-bot-token plus --post-discord-channel, '
                'or set them in config.json (discord.webhook_aliases or discord.bot_token and discord.channel_aliases).'
            )

    # Transcribe action with openai backend requires openai.api_key
    if 'transcribe' in actions:
        backend = getattr(args, 'transcribe_backend', None) or getattr(args, 'transcribe', None) or cfg.get('services', {}).get('default_transcribe_backend', 'faster_whisper')
        # OpenAI backend requires an API key
        if backend == 'openai':
            api_key = cfg.get('openai', {}).get('api_key') if cfg else None
            if not api_key and not os.environ.get('OPENAI_API_KEY'):
                errs.append(
                    'transcribe action using OpenAI backend requires openai.api_key in config.json or OPENAI_API_KEY env var. '
                    'Set openai.api_key in your config.json or export OPENAI_API_KEY in your environment.'
                )
        # Local backends require their packages to be installed
        if backend == 'faster_whisper':
            if importlib.util.find_spec('faster_whisper') is None:
                errs.append('transcribe backend "faster_whisper" selected but package not found. Install with: pip install faster-whisper')
        if backend == 'whisper':
            if importlib.util.find_spec('whisper') is None and importlib.util.find_spec('openai_whisper') is None:
                errs.append('transcribe backend "whisper" selected but package not found. Install with: pip install -U openai-whisper')

    # Additional check: download action requires ffmpeg on PATH
    if 'download' in actions:
        if shutil.which('ffmpeg') is None:
            errs.append(
                'download action requires ffmpeg available on PATH. Install ffmpeg (e.g. "sudo apt install ffmpeg" on Debian/Ubuntu) '
                'or add it to your PATH.'
            )

    # summarize (and other OpenAI-based actions) require OpenAI API key
    if 'summarize' in actions:
        api_key = cfg.get('openai', {}).get('api_key') if cfg else None
        if not api_key and not os.environ.get('OPENAI_API_KEY'):
            errs.append(
                'summarize action requires an OpenAI API key. Set openai.api_key in config.json or export OPENAI_API_KEY.'
            )

    if errs:
        print('\n[ERROR] Missing required options for requested actions:')
        for e in errs:
            print('  -', e)
        raise SystemExit('Missing required action options')


def cmd_download(args):
    rec_id, key = parse_input(args.input)
    key = key or args.key
    if not key:
        raise SystemExit("--key required if not present in URL")
    meta = get_metadata(rec_id, key)
    if not meta.get('duration'):
        dur = get_duration(rec_id, key)
        if dur and dur > 0:
            meta['duration'] = dur
    # Preflight dependency check
    _check_dependencies(['download'], args)

    result = run_download_flow(
        meta, rec_id, key,
        mix=args.mix,
        file_type=args.file_type,
        output_root=args.output_root,
        clobber=args.clobber,
        final_format=args.final_format,
        opus_bitrate=args.opus_bitrate,
        mp3_bitrate=args.mp3_bitrate,
    space_check=not args.space_awareness_disable,
        force_job_recreate=args.force_job_recreate,
    verbose=args.verbose,
    debug=args.debug,
    no_cleanup=args.no_cleanup,
    )
    print("Downloaded:", result['downloaded_file'])
    if result['final_file']:
        print("Final:", result['final_file'])
    print("Folder:", result['record_dir'])


def build_parser():
    p = argparse.ArgumentParser(prog="craigify", description="Craigify tools",
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("metadata", help="Show recording metadata")
    add_common(m)
    m.set_defaults(func=cmd_metadata)

    d = sub.add_parser("download", help="Download and optionally post-process")
    add_common(d)
    d.add_argument("--file-type", choices=["flac","mp3","vorbis","aac","adpcm","wav8","opus","oggflac","heaac"], default="flac")
    d.add_argument("--mix", choices=["individual","mixed"], default="individual")
    d.add_argument("--final-format", choices=["none","opus","mp3"], default="opus")
    d.add_argument("--opus-bitrate", default="24k")
    d.add_argument("--mp3-bitrate", default="128k")
    d.add_argument("--space-awareness-disable", action="store_true")
    d.add_argument("--force-job-recreate", action="store_true")
    d.set_defaults(func=cmd_download)

    # process: download + optional transcribe + summarize (skeleton)
    pr = sub.add_parser("process", help="Download, post-process, then optionally transcribe and summarize")
    add_common(pr)
    pr.add_argument("--file-type", choices=["flac","mp3","vorbis","aac","adpcm","wav8","opus","oggflac","heaac"], default="flac")
    pr.add_argument("--mix", choices=["individual","mixed"], default="individual")
    pr.add_argument("--final-format", choices=["opus","mp3"], default="opus")
    pr.add_argument("--opus-bitrate", default="24k")
    pr.add_argument("--mp3-bitrate", default="128k")
    pr.add_argument("--space-awareness-disable", action="store_true")
    pr.add_argument("--force-job-recreate", action="store_true")
    # Orchestration: ordered actions and namespaced action options
    pr.add_argument("--actions", default=None, help="Comma-separated ordered actions: metadata,download,postprocess,transcribe,summarize,post")
    # download-specific (namespaced)
    pr.add_argument("--download-file-type", choices=["flac","mp3","vorbis","aac","adpcm","wav8","opus","oggflac","heaac"], default=None)
    pr.add_argument("--download-mix", choices=["individual","mixed"], default=None)
    pr.add_argument("--download-final-format", choices=["none","opus","mp3"], default=None)
    pr.add_argument("--download-opus-bitrate", default=None)
    pr.add_argument("--download-mp3-bitrate", default=None)
    pr.add_argument("--download-space-awareness-disable", action="store_true")
    pr.add_argument("--download-force-job-recreate", action="store_true")
    # transcribe-specific (namespaced)
    pr.add_argument("--transcribe-mode", choices=["mixed","tracks"], default=None)
    pr.add_argument("--transcribe-backend", choices=["faster_whisper","whisper","openai"], default=None)
    pr.add_argument("--transcribe-model", default=None)
    pr.add_argument("--transcribe-language", default=None)
    pr.add_argument("--transcribe-device", choices=["cpu","cuda"], default=None)
    pr.add_argument("--transcribe-output-format", choices=["txt","json","vtt","srt","all"], default=None)
    pr.add_argument("--transcribe-processing-dir", default=None)
    pr.add_argument("--transcribe-clip-minutes", type=int, default=None)
    pr.add_argument("--transcribe-config", default=None)
    # transcribe niceties (namespaced)
    pr.add_argument("--transcribe-trim-silence", action="store_true", help="Trim leading/trailing silence before transcribing (namespaced)")
    pr.add_argument("--transcribe-dedupe-lines", action="store_true", help="Dedupe near-duplicate lines when merging transcripts (namespaced)")
    pr.add_argument("--transcribe-keep-context", action="store_true", help="Keep context across chunks (namespaced)")
    pr.add_argument("--transcribe-no-keep-context", action="store_true", help="Disable context chaining across chunks (namespaced)")
    # summarize-specific
    pr.add_argument("--summarize-style", choices=["none","brief","points","actions"], default=None)
    # post-specific (one-off posting)
    pr.add_argument("--post-discord-webhook", default=None, help="Discord webhook URL to post final artifacts to (optional)")
    pr.add_argument("--post-discord-channel", default=None, help="Discord channel id (if using bot token posting later)")
    pr.add_argument("--post-discord-bot-token", default=None, help="Discord bot token to use for posting (overrides config.json)")
    pr.add_argument("--post-template", default=None, help="Path to message template file to use when posting to Discord (overrides config.json)")
    pr.add_argument("--transcribe", choices=["none","mixed","tracks"], default="none")
    pr.add_argument("--summary", choices=["none","brief","points","actions"], default="none")
    pr.add_argument("--resume-record-dir", default=None, help="Explicit recordings/<folder> name to use to resume an earlier run (if multiple matches exist)")

    def _cmd_process(args):
        # Reuse metadata and orchestrate ordered actions
        rec_id, key = parse_input(args.input)
        key = key or args.key
        if not key:
            raise SystemExit("--key required if not present in URL")
        meta = get_metadata(rec_id, key)
        if not meta.get('duration'):
            dur = get_duration(rec_id, key)
            if dur and dur > 0:
                meta['duration'] = dur

        # Determine ordered actions
        if args.actions:
            actions = [a.strip() for a in args.actions.split(',') if a.strip()]
        else:
            # fallback: always download/postprocess, optionally transcribe/summarize
            actions = ['download']
            if args.transcribe and args.transcribe != 'none':
                actions.append('transcribe')
            if args.summary and args.summary != 'none':
                actions.append('summarize')

        # If post-related flags or config are present, implicitly include 'post' action
        cfg = _load_config(args.config, explicit=(args.config != 'config.json'))
        post_flags = any([args.post_discord_webhook, args.post_discord_channel, args.post_discord_bot_token])
        post_cfg = (cfg.get('discord', {}) if cfg else {})
        post_cfg_present = bool(post_cfg.get('webhook_aliases') or post_cfg.get('bot_token') or post_cfg.get('channel_aliases') or post_cfg.get('default_post_template'))
        if post_flags or post_cfg_present:
            if 'post' not in actions:
                actions.append('post')
                if args.verbose:
                    print('[INFO] Post-related options detected; adding "post" to actions')

        # Validate that the requested actions have their required options
        _validate_action_requirements(actions, args, cfg, meta)

        # Preflight dependency check for requested actions
        _check_dependencies(actions, args)

        # effective no_cleanup if transcription later needs stems
        effective_no_cleanup = args.no_cleanup or ('transcribe' in actions)
        if 'transcribe' in actions and not args.no_cleanup:
            print('[INFO] Transcription requested: preserving intermediate files for reuse (--no-cleanup implied)')

        # placeholders for results
        result = None

        # run actions in order
        for act in actions:
            act = act.lower()
            if act == 'metadata':
                summarize_metadata(meta, rec_id)

            elif act == 'download':
                # prefer namespaced options when provided
                file_type = args.download_file_type or args.file_type
                mix = args.download_mix or args.mix
                final_format = args.download_final_format if args.download_final_format is not None else args.final_format
                opus_bitrate = args.download_opus_bitrate or args.opus_bitrate
                mp3_bitrate = args.download_mp3_bitrate or args.mp3_bitrate
                space_check = not (args.download_space_awareness_disable or args.space_awareness_disable)
                force_job_recreate = args.download_force_job_recreate or args.force_job_recreate
                # If downloads/finals already exist and user didn't request clobber/force,
                # prefer reusing them. Use recording dirs to locate prior artifacts.
                base = build_base_name(meta)
                from .storage.paths import get_recording_dirs, find_existing_record_dir
                # prefer reusing an existing record dir that starts with the same base
                # If user provided an explicit resume folder name, prefer it
                existing = None
                if getattr(args, 'resume_record_dir', None):
                    rr = args.resume_record_dir
                    candidate = None
                    # If user passed an absolute path or a path that already exists, prefer it.
                    if os.path.isabs(rr):
                        candidate = rr
                    else:
                        # try rr as given (relative to cwd)
                        if os.path.isdir(rr):
                            candidate = os.path.abspath(rr)
                        else:
                            # fallback: rr is likely a folder name under output_root
                            candidate = os.path.join(args.output_root, rr)
                    if os.path.isdir(candidate):
                        existing = candidate
                if not existing:
                    existing = find_existing_record_dir(args.output_root, base)
                if existing:
                    dirs = {
                        'record': existing,
                        'downloads': os.path.join(existing, 'downloads'),
                        'work': os.path.join(existing, 'work'),
                        'final': os.path.join(existing, 'final'),
                        'meta': os.path.join(existing, 'meta'),
                        'logs': os.path.join(existing, 'logs'),
                    }
                    for d in dirs.values():
                        os.makedirs(d, exist_ok=True)
                else:
                    dirs = get_recording_dirs(args.output_root, base, clobber=False)
                downloads_dir = dirs['downloads']
                final_dir = dirs['final']

                # per-run marker filenames
                download_inprog = os.path.join(downloads_dir, f"{base}.download.inprogress")
                download_done = os.path.join(downloads_dir, f"{base}.download.complete")

                # scan for existing downloaded artifacts (zip or stems)
                existing_downloads = []
                if os.path.isdir(downloads_dir):
                    for fn in os.listdir(downloads_dir):
                        if fn.startswith('.'):
                            continue
                        if fn.endswith('.zip') or fn.endswith('.flac.zip') or fn.endswith('.flac') or fn.endswith('.tar'):
                            existing_downloads.append(os.path.join(downloads_dir, fn))

                if existing_downloads and not args.clobber and not force_job_recreate:
                    # if download was previously marked as complete (or just exists), reuse
                    if os.path.exists(download_done) or existing_downloads:
                        print('[INFO] Found existing download(s); reusing existing artifacts (use --clobber or --force-job-recreate to override)')
                        # pick the most recent downloaded candidate
                        existing_downloads.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                        result = {'downloaded_file': existing_downloads[0], 'final_file': None, 'record_dir': dirs['record']}
                        # detect existing final file too
                        final_candidates = []
                        if os.path.isdir(final_dir):
                            for fn in os.listdir(final_dir):
                                if fn.endswith('.opus') or fn.endswith('.mp3') or fn.endswith('.wav'):
                                    final_candidates.append(os.path.join(final_dir, fn))
                        if final_candidates:
                            final_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                            result['final_file'] = final_candidates[0]
                    else:
                        # in-progress marker present; warn the user
                        if os.path.exists(download_inprog):
                            raise SystemExit('[ERROR] A previous download appears to be in progress (found .inprogress marker). Remove it or use --force-job-recreate to continue')
                else:
                    # create in-progress marker
                    try:
                        os.makedirs(downloads_dir, exist_ok=True)
                        open(download_inprog, 'w').close()
                    except Exception:
                        pass
                    try:
                        result = run_download_flow(
                            meta, rec_id, key,
                            mix=mix,
                            file_type=file_type,
                            output_root=args.output_root,
                            clobber=args.clobber,
                            final_format=final_format,
                            opus_bitrate=opus_bitrate,
                            mp3_bitrate=mp3_bitrate,
                            space_check=space_check,
                            force_job_recreate=force_job_recreate,
                            verbose=args.verbose,
                            debug=args.debug,
                            no_cleanup=effective_no_cleanup,
                        )
                        # mark download complete
                        try:
                            open(download_done, 'w').close()
                        except Exception:
                            pass
                    finally:
                        try:
                            if os.path.exists(download_inprog):
                                os.remove(download_inprog)
                        except Exception:
                            pass
                print("Downloaded:", result['downloaded_file'])
                if result.get('final_file'):
                    print("Final:", result['final_file'])
                print("Folder:", result['record_dir'])

            elif act == 'postprocess':
                # create final output from existing downloads if needed
                from .providers.craig_download import post_process_to_final
                base = build_base_name(meta)
                from .storage.paths import get_recording_dirs
                dirs = get_recording_dirs(args.output_root, base, clobber=False)
                # find latest download
                dl_dir = dirs['downloads']
                dl_candidates = [os.path.join(dl_dir, f) for f in os.listdir(dl_dir) if os.path.isfile(os.path.join(dl_dir, f))]
                dl_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                if not dl_candidates:
                    raise RuntimeError('No downloaded audio found for postprocess')
                latest = dl_candidates[0]
                final_fmt = args.download_final_format or args.final_format
                opus_bitrate = args.download_opus_bitrate or args.opus_bitrate
                mp3_bitrate = args.download_mp3_bitrate or args.mp3_bitrate
                out = post_process_to_final(latest, dirs['final'], dirs['work'], base, final_fmt, opus_bitrate, mp3_bitrate, no_cleanup=effective_no_cleanup)
                print('Postprocessed ->', out)

            elif act == 'transcribe':
                # Build Namespace for transcribe runner using namespaced overrides
                if result:
                    rec_dir = result['record_dir']
                else:
                    base = build_base_name(meta)
                    from .storage.paths import get_recording_dirs, find_existing_record_dir
                    existing = None
                    if getattr(args, 'resume_record_dir', None):
                        rr = args.resume_record_dir
                        candidate = None
                        if os.path.isabs(rr):
                            candidate = rr
                        else:
                            if os.path.isdir(rr):
                                candidate = os.path.abspath(rr)
                            else:
                                candidate = os.path.join(args.output_root, rr)
                        if os.path.isdir(candidate):
                            existing = candidate
                    if not existing:
                        existing = find_existing_record_dir(args.output_root, base)
                    if existing:
                        dirs = {
                            'record': existing,
                            'downloads': os.path.join(existing, 'downloads'),
                            'work': os.path.join(existing, 'work'),
                            'final': os.path.join(existing, 'final'),
                            'meta': os.path.join(existing, 'meta'),
                            'logs': os.path.join(existing, 'logs'),
                        }
                        for d in dirs.values():
                            os.makedirs(d, exist_ok=True)
                    else:
                        dirs = get_recording_dirs(args.output_root, base, clobber=False)
                    rec_dir = dirs['record']
                # Build transcribe Namespace using namespaced options when present.
                # Use getattr fallbacks for attributes that only exist on the transcribe subparser
                # to avoid AttributeError when called from the process flow.
                trans_args = argparse.Namespace(
                    record_dir=rec_dir,
                    mode=(args.transcribe_mode or getattr(args, 'transcribe', None) or 'tracks'),
                    backend=(args.transcribe_backend or getattr(args, 'transcribe_backend', None) or 'faster_whisper'),
                    model=(args.transcribe_model or getattr(args, 'model', None) or 'small'),
                    language=(args.transcribe_language or getattr(args, 'language', None) or 'auto'),
                    device=(args.transcribe_device or getattr(args, 'device', None)),
                    trim_silence=(getattr(args, 'transcribe_trim_silence', None) or getattr(args, 'trim_silence', False)),
                    dedupe_lines=(getattr(args, 'transcribe_dedupe_lines', None) or getattr(args, 'dedupe_lines', False)),
                    # condition_on_previous_text: priority: namespaced keep/no-keep, else default True
                    condition_on_previous_text=(True if getattr(args, 'transcribe_keep_context', None) else (False if getattr(args, 'transcribe_no_keep_context', None) else True)),
                    output_format=(args.transcribe_output_format or getattr(args, 'output_format', None) or 'all'),
                    processing_dir=(args.transcribe_processing_dir or getattr(args, 'processing_dir', None)),
                    clip_minutes=(args.transcribe_clip_minutes if getattr(args, 'transcribe_clip_minutes', None) is not None else getattr(args, 'clip_minutes', None)),
                    config=(args.transcribe_config or getattr(args, 'config', None)),
                    verbose=args.verbose,
                    debug=args.debug,
                )
                # Load config.json if present or explicitly provided; only error if backend requires it
                cfg = _load_config(trans_args.config, explicit=(trans_args.config != 'config.json')) if getattr(trans_args, 'config', None) else {}
                if trans_args.backend == 'openai':
                    api_key = cfg.get('openai', {}).get('api_key') or os.environ.get('OPENAI_API_KEY')
                    if not api_key:
                        raise SystemExit('OpenAI backend selected but no api_key found in config or OPENAI_API_KEY; pass --config or set OPENAI_API_KEY')
                run_transcribe_cli(trans_args)

            elif act == 'summarize':
                if result:
                    rec_dir = result['record_dir']
                else:
                    base = build_base_name(meta)
                    from .storage.paths import get_recording_dirs
                    dirs = get_recording_dirs(args.output_root, base, clobber=False)
                    rec_dir = dirs['record']
                style = args.summarize_style or args.summary or 'brief'
                run_summarize_cli(record_dir=rec_dir, style=style)

            elif act == 'post':
                # one-off post: stubbed. If webhook provided, show that we'd post final artifacts
                if result and result.get('final_file'):
                    final_file = result['final_file']
                    print('[POST] Posting final file to discord/webhook if configured:', final_file)
                    # Load config (explicit if CLI config flag not default)
                    cfg = _load_config(args.config, explicit=(args.config != 'config.json'))
                    # Resolve webhook(s): allow alias names defined in config.discord.webhook_aliases
                    webhook_raw = args.post_discord_webhook or cfg.get('discord', {}).get('webhook_url')
                    webhook_aliases = cfg.get('discord', {}).get('webhook_aliases', {}) if cfg else {}
                    webhooks = []
                    if webhook_raw:
                        # allow comma-separated list of aliases or urls
                        for part in [p.strip() for p in webhook_raw.split(',') if p.strip()]:
                            if isinstance(webhook_aliases, dict) and part in webhook_aliases:
                                webhooks.append(webhook_aliases.get(part))
                            else:
                                webhooks.append(part)
                    else:
                        # fallback to any single webhook_url in config if present
                        w = cfg.get('discord', {}).get('webhook_url')
                        if w:
                            webhooks = [w]
                    from .utils.discord import resolve_bot_token, resolve_channel_id, resolve_webhooks
                    bot_token = resolve_bot_token(args.post_discord_bot_token, cfg)
                    webhooks = resolve_webhooks(args.post_discord_webhook, cfg)
                    channel_id = resolve_channel_id(args.post_discord_channel or None, cfg)
                    if args.verbose or args.debug:
                        print('[DEBUG] Resolved posting targets -> webhooks:', webhooks, 'bot_token:', bool(bot_token), 'channel_id:', channel_id)
                    if webhooks:
                        # post to one or more webhook URLs
                        # attach final file + merged transcripts (if present)
                        merged_txt = os.path.join(os.path.dirname(final_file), '..', 'transcripts', 'merged.txt')
                        merged_json = os.path.join(os.path.dirname(final_file), '..', 'transcripts', 'merged.json')
                        extra_files = []
                        if os.path.exists(merged_txt):
                            extra_files.append(('file', ('merged.txt', open(merged_txt, 'rb'))))
                        if os.path.exists(merged_json):
                            extra_files.append(('file', ('merged.json', open(merged_json, 'rb'))))

                        # Load and render message template
                        default_template_path = os.path.join(os.path.dirname(__file__), 'templates', 'post_message.txt')
                        tpl = _load_template(args.post_template or None, cfg.get('discord', {}).get('default_post_template') if cfg else default_template_path)
                        message_body = _render_message_template(tpl, meta)

                        for wh in webhooks:
                            try:
                                with open(final_file, 'rb') as fh:
                                    files = [('file', (os.path.basename(final_file), fh))]
                                    # include extras
                                    files.extend(extra_files)
                                    # include payload_json to set content
                                    payload = {'content': message_body}
                                    data = {'payload_json': (None, json.dumps(payload))}
                                    # merge files with payload
                                    resp = requests.post(wh, files=files + list(data.items()))
                                if resp.status_code // 100 == 2:
                                    print(f'[POST] Posted via webhook ({wh}) OK')
                                else:
                                    print(f'[POST] Webhook post failed ({wh}):', resp.status_code, resp.text[:200])
                            except Exception as e:
                                print(f'[POST] Webhook post error ({wh}):', e)
                    elif bot_token and channel_id:
                        # Use bot token to upload file via Discord API
                        try:
                            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
                            headers = {'Authorization': f'Bot {bot_token}'}
                            # prepare multipart with final file and merged transcripts if available
                            payload_files = []
                            payload_files.append(('file', (os.path.basename(final_file), open(final_file, 'rb'))))
                            merged_txt = os.path.join(os.path.dirname(final_file), '..', 'transcripts', 'merged.txt')
                            merged_json = os.path.join(os.path.dirname(final_file), '..', 'transcripts', 'merged.json')
                            if os.path.exists(merged_txt):
                                payload_files.append(('file', ('merged.txt', open(merged_txt, 'rb'))))
                            if os.path.exists(merged_json):
                                payload_files.append(('file', ('merged.json', open(merged_json, 'rb'))))

                            # Render message template for bot post
                            default_template_path = os.path.join(os.path.dirname(__file__), 'templates', 'post_message.txt')
                            tpl = _load_template(args.post_template or None, cfg.get('discord', {}).get('default_post_template') if cfg else default_template_path)
                            message_body = _render_message_template(tpl, meta)

                            # send as 'content' with files
                            data = {'content': message_body}
                            resp = requests.post(url, headers=headers, files=payload_files, data=data)
                            if resp.status_code // 100 == 2:
                                print('[POST] Posted via bot token OK')
                            else:
                                print('[POST] Bot post failed:', resp.status_code, resp.text[:200])
                        except Exception as e:
                            print('[POST] Bot post error:', e)
                    else:
                        print('[POST] No webhook or bot token/channel configured; cannot post. Pass --post-discord-webhook or configure config.json')
                else:
                    print('[POST] No final file available to post')

            else:
                print('[WARN] Unknown action:', act)
        # After all actions, print a consolidated summary of artifacts
        try:
            print('\n=== Process summary ===')
            if result:
                print('Record folder:', result.get('record_dir'))
                if result.get('downloaded_file'):
                    print('Downloaded:', result.get('downloaded_file'))
                if result.get('final_file'):
                    print('Final:', result.get('final_file'))
            # show merged transcripts if present
            base = build_base_name(meta)
            from .storage.paths import get_recording_dirs
            dirs = get_recording_dirs(args.output_root, base, clobber=False)
            trans_dir = os.path.join(dirs['record'], 'transcripts')
            if os.path.isdir(trans_dir):
                for root, _, files in os.walk(trans_dir):
                    for f in files:
                        print('  -', os.path.join(root, f))
            # if summarize was requested, also run/print summary now
            if 'summarize' in actions and (args.summarize and args.summarize != 'none'):
                print('\nSummary requested; run the summarize action to print its output above (or use --summary)')
        except Exception:
            pass
    pr.set_defaults(func=_cmd_process)

    # transcribe subcommand
    t = sub.add_parser("transcribe", help="Transcribe audio for a recording folder or URL")
    t.add_argument("record_dir", nargs='?', default=None, help="Path to recordings/<base>/ folder (optional if -i supplied)")
    # allow passing a URL to download+transcribe
    t.add_argument("-i", "--input", help="Recording URL or ID (will be downloaded then transcribed)")
    t.add_argument("--key", help="Recording key (if not included in URL)")
    t.add_argument("--output-root", default=os.path.join(os.getcwd(), 'recordings'), help="Root dir for per-recording folders")
    t.add_argument("--clobber", action="store_true", help="Overwrite if exists")
    t.add_argument("--file-type", choices=["flac","mp3","vorbis","aac","adpcm","wav8","opus","oggflac","heaac"], default="flac")
    t.add_argument("--mix", choices=["individual","mixed"], default="individual")
    t.add_argument("--final-format", choices=["none","opus","mp3"], default="opus")
    t.add_argument("--opus-bitrate", default="24k")
    t.add_argument("--mp3-bitrate", default="128k")
    t.add_argument("--space-awareness-disable", action="store_true")
    t.add_argument("--force-job-recreate", action="store_true")

    t.add_argument("--mode", choices=["mixed","tracks"], default="tracks", help="mixed=single mixed audio; tracks=per-track stems (default)")
    t.add_argument("--backend", choices=["faster_whisper","whisper","openai"], default="faster_whisper", help="Transcription backend to use")
    t.add_argument("--model", default="small", help="Model name to use for local backends or OpenAI model name")
    t.add_argument("--language", default="auto", help="Language code or 'auto' for detection")
    t.add_argument("--device", choices=["cpu","cuda"], help="Device to run local models on (auto-detected if omitted)")
    t.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence before transcribing")
    t.add_argument("--dedupe-lines", action="store_true", help="Remove near-duplicate lines in merged transcript")
    t.add_argument("--output-format", choices=["txt","json","vtt","srt","all"], default="all", help="Transcript output format(s)")
    t.add_argument("--processing-dir", default=None, help="Temp dir for per-track processing (defaults to <record_dir>/work/transcribe)")
    t.add_argument("--clip-minutes", type=int, default=0, help="Limit transcription to first N minutes of each file for debug (0=full)")
    t.add_argument("--config", default="config.json", help="Path to config.json with API keys and other service settings")
    t.add_argument("--verbose", action="store_true", help="Verbose logging for transcription steps")
    t.add_argument("--debug", action="store_true", help="Enable debug logging for download/transcribe")
    t.add_argument("--resume-record-dir", default=None, help="Explicit recordings/<folder> name to use to resume an earlier run (if multiple matches exist)")

    def _cmd_transcribe(args):
        # If input URL provided, download first into a recording folder
        rec_dir = args.record_dir
        if args.input:
            rec_id, key = parse_input(args.input)
            key = key or args.key
            if not key:
                raise SystemExit("--key required if not present in URL")
            meta = get_metadata(rec_id, key)
            if not meta.get('duration'):
                dur = get_duration(rec_id, key)
                if dur and dur > 0:
                    meta['duration'] = dur
            # If the user requested per-track transcription, avoid creating a mixed final file
            # so stems remain available for per-track ASR. Respect explicit final_format if user set it.
            final_fmt = args.final_format
            if args.mode == 'tracks' and final_fmt != 'none':
                final_fmt = 'none'
            # Preflight dependency check for download+transcribe path
            _check_dependencies(['download','transcribe'], args)

            # Attempt to reuse existing downloads if present (respect .inprogress/.complete markers)
            base = None
            try:
                # try to infer base from metadata
                base = build_base_name(meta)
            except Exception:
                base = None
            if base:
                from .storage.paths import get_recording_dirs
                dirs = get_recording_dirs(args.output_root, base, clobber=False)
                downloads_dir = dirs['downloads']
                download_inprog = os.path.join(downloads_dir, f"{base}.download.inprogress")
                download_done = os.path.join(downloads_dir, f"{base}.download.complete")
                existing_downloads = []
                if os.path.isdir(downloads_dir):
                    for fn in os.listdir(downloads_dir):
                        if fn.startswith('.'):
                            continue
                        if fn.endswith('.zip') or fn.endswith('.flac.zip') or fn.endswith('.flac') or fn.endswith('.tar'):
                            existing_downloads.append(os.path.join(downloads_dir, fn))
                if existing_downloads and not args.clobber and not args.force_job_recreate:
                    if os.path.exists(download_done) or existing_downloads:
                        existing_downloads.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                        result = {'downloaded_file': existing_downloads[0], 'final_file': None, 'record_dir': dirs['record']}
                        rec_dir = result['record_dir']
                        print('[INFO] Reusing existing download for transcription:', result['downloaded_file'])
                    else:
                        if os.path.exists(download_inprog):
                            raise SystemExit('[ERROR] A previous download appears to be in progress (found .inprogress marker). Remove it or use --force-job-recreate to continue')
                else:
                    result = run_download_flow(
                        meta, rec_id, key,
                        mix=args.mix,
                        file_type=args.file_type,
                        output_root=args.output_root,
                        clobber=args.clobber,
                        final_format=final_fmt,
                        opus_bitrate=args.opus_bitrate,
                        mp3_bitrate=args.mp3_bitrate,
                        space_check=not args.space_awareness_disable,
                        force_job_recreate=args.force_job_recreate,
                        verbose=args.verbose,
                        debug=args.debug,
                        no_cleanup=args.no_cleanup,
                    )
                    rec_dir = result['record_dir']
                    print('Downloaded ->', result['downloaded_file'])
        if not rec_dir:
            raise SystemExit('record_dir required if no --input provided')
        # Now call the transcribe runner with the full args namespace
        # reuse existing run_transcribe_cli which accepts the argparse Namespace
        run_transcribe_cli(args.__class__(**vars(args)) if False else args)

    t.set_defaults(func=_cmd_transcribe)

    # summarize subcommand (skeleton)
    s = sub.add_parser("summarize", help="Summarize transcript(s) in a recording folder")
    s.add_argument("record_dir", help="Path to recordings/<base>/ folder")
    s.add_argument("--style", choices=["brief","points","actions"], default="brief")
    s.set_defaults(func=lambda a: run_summarize_cli(record_dir=a.record_dir, style=a.style))

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
