import argparse
import os
from .providers.craig_api import parse_input, get_metadata, get_duration
from .providers.craig_download import run_download_flow
from .storage.paths import build_base_name
from .transcribe.run import run_transcribe_cli
from .summarize.run import run_summarize_cli


def add_common(parser: argparse.ArgumentParser):
    parser.add_argument("-i", "--input", required=True, help="Recording URL or ID")
    parser.add_argument("--key", help="Recording key (if not included in URL)")
    parser.add_argument("--output-root", default=os.path.join(os.getcwd(), 'recordings'), help="Root dir for per-recording folders")
    parser.add_argument("--clobber", action="store_true", help="Overwrite if exists")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging (more output)")


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
    pr.add_argument("--transcribe", choices=["none","mixed","tracks"], default="none")
    pr.add_argument("--summary", choices=["none","brief","points","actions"], default="none")

    def _cmd_process(args):
        # reuse download
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
        )
        print("Downloaded:", result['downloaded_file'])
        if result['final_file']:
            print("Final:", result['final_file'])
        print("Folder:", result['record_dir'])
        # Transcribe and summarize (skeletons)
        if args.transcribe != 'none':
            run_transcribe_cli(record_dir=result['record_dir'], mode=args.transcribe)
        if args.summary != 'none':
            run_summarize_cli(record_dir=result['record_dir'], style=args.summary)

    pr.set_defaults(func=_cmd_process)

    # transcribe subcommand
    t = sub.add_parser("transcribe", help="Transcribe audio for a recording folder")
    t.add_argument("record_dir", help="Path to recordings/<base>/ folder")
    t.add_argument("--mode", choices=["mixed","tracks"], default="mixed", help="mixed=single mixed audio; tracks=per-track stems")
    t.add_argument("--backend", choices=["faster_whisper","whisper","openai"], default="faster_whisper", help="Transcription backend to use")
    t.add_argument("--model", default="small", help="Model name to use for local backends (e.g. tiny, base, small, medium, large) or OpenAI model name")
    t.add_argument("--language", default="auto", help="Language code or 'auto' for detection")
    t.add_argument("--device", choices=["cpu","cuda"], help="Device to run local models on (auto-detected if omitted)")
    t.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence before transcribing")
    t.add_argument("--dedupe-lines", action="store_true", help="Remove near-duplicate lines in merged transcript")
    t.add_argument("--output-format", choices=["txt","json","vtt","srt","all"], default="all", help="Transcript output format(s)")
    t.add_argument("--processing-dir", default=None, help="Temp dir for per-track processing (defaults to <record_dir>/work/transcribe)")
    t.add_argument("--clip-minutes", type=int, default=0, help="Limit transcription to first N minutes of each file for debug (0=full)")
    t.add_argument("--config", default="config.json", help="Path to config.json with API keys and other service settings")
    t.add_argument("--verbose", action="store_true", help="Verbose logging for transcription steps")
    t.set_defaults(func=lambda a: run_transcribe_cli(a))

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
