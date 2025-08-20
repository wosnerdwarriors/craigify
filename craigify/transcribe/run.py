import os
import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from ..storage.manifest import update_manifest
from ..utils.ffmpeg import ffmpeg_exists, run_ffmpeg


def _read_config(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _ensure_processing_dir(record_dir: str, processing_dir: Optional[str]):
    if processing_dir:
        os.makedirs(processing_dir, exist_ok=True)
        return processing_dir
    default = os.path.join(record_dir, 'work', 'transcribe')
    os.makedirs(default, exist_ok=True)
    return default


def _mix_stems_to_temp(stems_dir: str, out_path: str, verbose: bool = False):
    # Find audio stems and call ffmpeg to mix to mono 48k WAV/OPUS suitable for model
    inputs = []
    for root, _, files in os.walk(stems_dir):
        for n in files:
            if n.lower().endswith(('.flac', '.wav', '.ogg')):
                inputs.append(os.path.join(root, n))
    if not inputs:
        raise RuntimeError('No stems found to mix')
    cmd = ['ffmpeg', '-y']
    for p in inputs:
        cmd += ['-i', p]
    n = len(inputs)
    filter_complex = f"amix=inputs={n}:dropout_transition=0:normalize=0, aformat=channel_layouts=mono, aresample=48000"
    cmd += ['-filter_complex', filter_complex, '-ac', '1', '-ar', '48000', out_path]
    if verbose:
        print('[VERBOSE] ffmpeg mix command:', ' '.join(cmd))
    run_ffmpeg(cmd)
    return out_path


def _extract_zip_to_work(zip_path: str, work_dir: str, verbose: bool = False):
    stems = os.path.join(work_dir, 'stems')
    os.makedirs(stems, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(stems)
    return stems


# Backend implementations (lazy imports to avoid heavy deps at module load)


def _run_faster_whisper(audio_path: str, model_name: str, device: str, lang: Optional[str], clip_minutes: int, verbose: bool, output_prefix: str):
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise RuntimeError('faster-whisper not installed; pip install faster-whisper')
    use_device = device or ('cuda' if shutil.which('nvidia-smi') else 'cpu')
    model = WhisperModel(model_name, device=use_device)
    trans_kwargs = {}
    if lang and lang != 'auto':
        trans_kwargs['language'] = lang
    if clip_minutes and clip_minutes > 0:
        trans_kwargs['max_length'] = clip_minutes * 60
    segments, info = model.transcribe(audio_path, **trans_kwargs)
    # write VTT and plain text
    vtt = output_prefix + '.vtt'
    txt = output_prefix + '.txt'
    with open(vtt, 'w', encoding='utf-8') as f_v, open(txt, 'w', encoding='utf-8') as f_t:
        f_v.write('WEBVTT\n\n')
        for i, seg in enumerate(segments, start=1):
            start = seg.start
            end = seg.end
            text = seg.text.strip()
            f_v.write(f"{i}\n{start:.3f} --> {end:.3f}\n{text}\n\n")
            f_t.write(f"[{start:.3f}] {text}\n")
    return [vtt, txt]


def _run_whisper(audio_path: str, model_name: str, device: str, lang: Optional[str], clip_minutes: int, verbose: bool, output_prefix: str):
    try:
        import whisper
    except Exception:
        raise RuntimeError('openai/whisper package not installed; pip install -U openai-whisper')
    use_device = device or ('cuda' if shutil.which('nvidia-smi') else 'cpu')
    model = whisper.load_model(model_name, device=use_device)
    opts = {'language': None if (lang == 'auto' or not lang) else lang, 'verbose': verbose}
    if clip_minutes and clip_minutes > 0:
        opts['clip_timestamps'] = f"0,{clip_minutes*60}"
    result = model.transcribe(audio_path, **opts)
    out_vtt = output_prefix + '.vtt'
    out_txt = output_prefix + '.txt'
    with open(out_vtt, 'w', encoding='utf-8') as f_v, open(out_txt, 'w', encoding='utf-8') as f_t:
        f_v.write('WEBVTT\n\n')
        for i, seg in enumerate(result['segments'], start=1):
            start = seg['start']
            end = seg['end']
            text = seg['text'].strip()
            f_v.write(f"{i}\n{start:.3f} --> {end:.3f}\n{text}\n\n")
            f_t.write(f"[{start:.3f}] {text}\n")
    return [out_vtt, out_txt]


def _run_openai_whisper(audio_path: str, model_name: str, api_key: str, lang: Optional[str], clip_minutes: int, verbose: bool, output_prefix: str):
    # Use openai's whisper ASR via the `openai` package (requires API key in env or config)
    try:
        import openai
    except Exception:
        raise RuntimeError('openai package not installed; pip install openai')
    openai.api_key = api_key
    # Upload file and request transcription
    with open(audio_path, 'rb') as fh:
        resp = openai.Audio.transcriptions.create(model=model_name, file=fh)
    # resp may include text; write simple txt
    out_txt = output_prefix + '.txt'
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(resp.get('text', ''))
    return [out_txt]


def run_transcribe_cli(args):
    # args may be Namespace or dict depending on how CLI called; accept both
    if hasattr(args, 'record_dir'):
        record_dir = args.record_dir
        mode = args.mode
        backend = args.backend
        model = args.model
        lang = args.language
        device = getattr(args, 'device', None)
        trim = getattr(args, 'trim_silence', False)
        dedupe = getattr(args, 'dedupe_lines', False)
        out_fmt = getattr(args, 'output_format', 'all')
        proc_dir = getattr(args, 'processing_dir', None)
        clip = getattr(args, 'clip_minutes', 0)
        config_path = getattr(args, 'config', 'config.json')
        verbose = getattr(args, 'verbose', False)
    else:
        # called programmatically: args is likely a dict
        record_dir = args.get('record_dir')
        mode = args.get('mode', 'mixed')
        backend = args.get('backend', 'faster_whisper')
        model = args.get('model', 'small')
        lang = args.get('language', 'auto')
        device = args.get('device')
        trim = args.get('trim_silence', False)
        dedupe = args.get('dedupe_lines', False)
        out_fmt = args.get('output_format', 'all')
        proc_dir = args.get('processing_dir')
        clip = args.get('clip_minutes', 0)
        config_path = args.get('config', 'config.json')
        verbose = args.get('verbose', False)

    record_dir = os.path.abspath(record_dir)
    if not os.path.exists(record_dir):
        raise RuntimeError(f"record_dir does not exist: {record_dir}")

    cfg = _read_config(config_path)
    api_key = None
    if backend == 'openai':
        api_key = cfg.get('openai', {}).get('api_key') or os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise RuntimeError('OpenAI backend selected but no api_key found in config or OPENAI_API_KEY')

    proc_dir = _ensure_processing_dir(record_dir, proc_dir)
    downloads = os.path.join(record_dir, 'downloads')
    final = os.path.join(record_dir, 'final')
    work = os.path.join(record_dir, 'work')
    os.makedirs(proc_dir, exist_ok=True)

    artifacts = []

    # prefer final mixed file if available for mixed
    if mode == 'mixed':
        # look for final/<base>.opus or downloads/*.zip or downloads/*mixed*
        candidates = []
        for f in os.listdir(final):
            if f.lower().endswith(('.opus', '.mp3', '.wav', '.flac')):
                candidates.append(os.path.join(final, f))
        if candidates:
            audio_path = candidates[0]
            if verbose:
                print('[VERBOSE] Using final audio for mixed transcription:', audio_path)
        else:
            # find most recent download
            dl_candidates = [os.path.join(downloads, f) for f in os.listdir(downloads) if os.path.isfile(os.path.join(downloads, f))]
            dl_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            if not dl_candidates:
                raise RuntimeError('No downloaded audio found to transcribe')
            latest = dl_candidates[0]
            if latest.lower().endswith('.zip'):
                stems = _extract_zip_to_work(latest, work, verbose=verbose)
                tmp = os.path.join(proc_dir, 'mixed_for_transcribe.opus')
                _mix_stems_to_temp(stems, tmp, verbose=verbose)
                audio_path = tmp
            else:
                audio_path = latest

        out_prefix = os.path.join(record_dir, 'transcripts', 'mixed')
        os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
        if backend == 'faster_whisper':
            produced = _run_faster_whisper(audio_path, model, device, lang, clip, verbose, out_prefix)
        elif backend == 'whisper':
            produced = _run_whisper(audio_path, model, device, lang, clip, verbose, out_prefix)
        else:
            produced = _run_openai_whisper(audio_path, model, api_key, lang, clip, verbose, out_prefix)
        artifacts.extend(produced)

    else:
        # tracks mode: find zip in downloads and transcribe each stem
        dl_candidates = [os.path.join(downloads, f) for f in os.listdir(downloads) if os.path.isfile(os.path.join(downloads, f))]
        dl_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        if not dl_candidates:
            raise RuntimeError('No downloaded audio found to transcribe (tracks mode)')
        latest = dl_candidates[0]
        if not latest.lower().endswith('.zip'):
            raise RuntimeError('Tracks mode requires zip of individual stems')
        stems = _extract_zip_to_work(latest, work, verbose=verbose)
        stem_files = []
        for root, _, files in os.walk(stems):
            for n in files:
                if n.lower().endswith(('.flac', '.wav', '.ogg')):
                    stem_files.append(os.path.join(root, n))
        if not stem_files:
            raise RuntimeError('No stems found inside zip')
        track_out_dir = os.path.join(record_dir, 'transcripts', 'tracks')
        os.makedirs(track_out_dir, exist_ok=True)
        for sf in stem_files:
            base = os.path.splitext(os.path.basename(sf))[0]
            out_prefix = os.path.join(track_out_dir, base)
            if backend == 'faster_whisper':
                produced = _run_faster_whisper(sf, model, device, lang, clip, verbose, out_prefix)
            elif backend == 'whisper':
                produced = _run_whisper(sf, model, device, lang, clip, verbose, out_prefix)
            else:
                produced = _run_openai_whisper(sf, model, api_key, lang, clip, verbose, out_prefix)
            artifacts.extend(produced)

    # dedupe step could be added here if requested
    update_manifest(record_dir, {'transcription': {'backend': backend, 'model': model, 'artifacts': artifacts}})
    print('\nTranscription complete. Artifacts:')
    for a in artifacts:
        print('  -', a)
    return artifacts
