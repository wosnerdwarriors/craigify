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
    # summarize-specific
    pr.add_argument("--summarize-style", choices=["none","brief","points","actions"], default=None)
    # post-specific (one-off posting)
    pr.add_argument("--post-discord-webhook", default=None, help="Discord webhook URL to post final artifacts to (optional)")
    pr.add_argument("--post-discord-channel", default=None, help="Discord channel id (if using bot token posting later)")
    pr.add_argument("--transcribe", choices=["none","mixed","tracks"], default="none")
    pr.add_argument("--summary", choices=["none","brief","points","actions"], default="none")

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
                    from .storage.paths import get_recording_dirs
                    dirs = get_recording_dirs(args.output_root, base, clobber=False)
                    rec_dir = dirs['record']
                trans_args = argparse.Namespace(
                    record_dir=rec_dir,
                    mode=(args.transcribe_mode or args.transcribe or 'tracks'),
                    backend=(args.transcribe_backend or 'faster_whisper'),
                    model=(args.transcribe_model or args.model or 'small'),
                    language=(args.transcribe_language or args.language or 'auto'),
                    device=(args.transcribe_device or args.device),
                    trim_silence=False,
                    dedupe_lines=False,
                    output_format=(args.transcribe_output_format or args.output_format or 'all'),
                    processing_dir=(args.transcribe_processing_dir or args.processing_dir),
                    clip_minutes=(args.transcribe_clip_minutes if args.transcribe_clip_minutes is not None else args.clip_minutes),
                    config=(args.transcribe_config or args.config),
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
                    webhook = args.post_discord_webhook or cfg.get('discord', {}).get('webhook_url')
                    bot_token = cfg.get('discord', {}).get('bot_token')
                    channel_id = args.post_discord_channel or cfg.get('discord', {}).get('channel_id')
                    if webhook:
                        # simple webhook file upload
                        try:
                            with open(final_file, 'rb') as fh:
                                files = {'file': fh}
                                resp = requests.post(webhook, files=files)
                            if resp.status_code // 100 == 2:
                                print('[POST] Posted via webhook OK')
                            else:
                                print('[POST] Webhook post failed:', resp.status_code, resp.text[:200])
                        except Exception as e:
                            print('[POST] Webhook post error:', e)
                    elif bot_token and channel_id:
                        # Use bot token to upload file via Discord API
                        try:
                            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
                            headers = {'Authorization': f'Bot {bot_token}'}
                            with open(final_file, 'rb') as fh:
                                files = {'file': fh}
                                resp = requests.post(url, headers=headers, files=files)
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
