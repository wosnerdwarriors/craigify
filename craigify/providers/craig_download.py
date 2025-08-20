import os
import json
import shutil
import zipfile
from .craig_api import get_job, post_job, delete_job, build_download_url
from ..storage.paths import get_recording_dirs, build_base_name, derive_local_filename
from ..storage.manifest import read_manifest, write_manifest, update_manifest
from ..utils.ffmpeg import ffmpeg_exists, run_ffmpeg
import requests


def get_free_space_bytes(path: str) -> int | None:
    orig = path
    while not os.path.exists(path):
        path = os.path.dirname(path)
        if path in ("", "/"):
            break
    try:
        stat = os.statvfs(path)
        return stat.f_frsize * stat.f_bavail
    except Exception:
        return None


def download_stream(url: str, outpath: str, exclusive: bool = False):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        mode = 'xb' if exclusive else 'wb'
        with open(outpath, mode) as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)


def poll_until_ready(recording_id: str, key: str, interval: float = 2.0, timeout: int = 600, verbose: bool = False, debug: bool = False):
    import time
    start = time.time()
    while True:
        data = get_job(recording_id, key)
        job = data.get('job') if isinstance(data, dict) else None
        if job:
            status = job.get('status')
            fname = job.get('outputFileName')
            size = job.get('outputSize')
            if verbose:
                print(f"[VERBOSE] Job status: {status}, file: {fname}, size: {size}")
            if status in ('finished','complete','completed','done') and fname:
                return fname, size
            if status in ('error','failed','cancelled','canceled'):
                raise RuntimeError(f"Job failed with status: {status}")
        if time.time() - start > timeout:
            raise TimeoutError("Timed out waiting for job to complete")
        time.sleep(interval)


def post_process_to_final(downloaded_path: str, final_dir: str, work_dir: str, base_name: str, final_format: str, opus_bitrate: str = "24k", mp3_bitrate: str = "128k", no_cleanup: bool = False):
    if final_format not in ("opus", "mp3"):
        return None
    if not ffmpeg_exists():
        raise RuntimeError("ffmpeg not found in PATH")
    if final_format == 'opus':
        out = os.path.join(final_dir, base_name + '.opus')
        if downloaded_path.lower().endswith('.zip'):
            stems = os.path.join(work_dir, 'stems')
            os.makedirs(stems, exist_ok=True)
            with zipfile.ZipFile(downloaded_path, 'r') as zf:
                zf.extractall(stems)
            inputs = []
            for root, _, files in os.walk(stems):
                for n in files:
                    if n.lower().endswith(('.flac','.wav','.ogg')):
                        inputs.append(os.path.join(root, n))
            if not inputs:
                raise RuntimeError("No audio stems found after unzip")
            cmd = ['ffmpeg','-y']
            for p in inputs:
                cmd += ['-i', p]
            n = len(inputs)
            filter_complex = f"amix=inputs={n}:dropout_transition=0:normalize=0, aformat=channel_layouts=mono, aresample=48000"
            cmd += ['-filter_complex', filter_complex, '-c:a','libopus','-b:a', opus_bitrate,'-vbr','on','-application','voip','-ac','1','-ar','48000', out]
            run_ffmpeg(cmd)
            if os.path.exists(out):
                    if os.path.isdir(stems) and not no_cleanup:
                        shutil.rmtree(stems, ignore_errors=True)
        else:
            cmd = ['ffmpeg','-y','-i', downloaded_path,'-c:a','libopus','-b:a',opus_bitrate,'-vbr','on','-application','voip','-ac','1','-ar','48000', out]
            run_ffmpeg(cmd)
        return out
    else:
        out = os.path.join(final_dir, base_name + '.mp3')
        if downloaded_path.lower().endswith('.zip'):
            stems = os.path.join(work_dir, 'stems')
            os.makedirs(stems, exist_ok=True)
            with zipfile.ZipFile(downloaded_path, 'r') as zf:
                zf.extractall(stems)
            inputs = []
            for root, _, files in os.walk(stems):
                for n in files:
                    if n.lower().endswith(('.flac','.wav','.ogg')):
                        inputs.append(os.path.join(root, n))
            if not inputs:
                raise RuntimeError("No audio stems found after unzip")
            cmd = ['ffmpeg','-y']
            for p in inputs:
                cmd += ['-i', p]
            n = len(inputs)
            filter_complex = f"amix=inputs={n}:dropout_transition=0:normalize=0, aformat=channel_layouts=mono, aresample=48000"
            cmd += ['-filter_complex', filter_complex, '-c:a','libmp3lame','-b:a', mp3_bitrate,'-ac','1','-ar','48000', out]
            run_ffmpeg(cmd)
            if os.path.exists(out):
                    if os.path.isdir(stems) and not no_cleanup:
                        shutil.rmtree(stems, ignore_errors=True)
        else:
            cmd = ['ffmpeg','-y','-i', downloaded_path,'-c:a','libmp3lame','-b:a', mp3_bitrate,'-ac','1','-ar','48000', out]
            run_ffmpeg(cmd)
        return out


def run_download_flow(metadata: dict, recording_id: str, key: str, *, mix: str, file_type: str, output_root: str, clobber: bool, final_format: str = 'none', opus_bitrate: str = '24k', mp3_bitrate: str = '128k', space_check: bool = True, force_job_recreate: bool = False, verbose: bool = False, debug: bool = False, no_cleanup: bool = False):
    base_name = build_base_name(metadata)
    dirs = get_recording_dirs(output_root, base_name, clobber=clobber)
    # persist metadata
    try:
        with open(os.path.join(dirs['meta'], 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    # init/update manifest
    update_manifest(dirs['record'], {
        'input': {'id': recording_id, 'key': key},
        'artifacts': {
            'record_dir': dirs['record'],
            'downloads_dir': dirs['downloads'],
            'final_dir': dirs['final'],
            'work_dir': dirs['work'],
        }
    })
    # Determine job body
    body = json.dumps({
        'type': 'recording',
        'options': {
            'container': 'mix' if mix == 'mixed' else 'zip',
            'format': file_type,
        }
    })

    # Reuse existing job or recreate
    job_resp = get_job(recording_id, key)
    ej = job_resp.get('job') if isinstance(job_resp, dict) else None
    # persist job snapshot
    try:
        with open(os.path.join(dirs['meta'], 'job.json'), 'w', encoding='utf-8') as f:
            json.dump(job_resp, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    if force_job_recreate and ej:
        delete_job(recording_id, key)
        ej = None
    if ej:
        status = ej.get('status')
        if status in ('finished','complete','completed','done') and ej.get('outputFileName'):
            filename = ej.get('outputFileName')
            fsize = ej.get('outputSize')
        elif status in ('error','failed','cancelled','canceled'):
            if verbose:
                print("[VERBOSE] Existing job in error state; creating new job")
            post_job(recording_id, key, body)
            filename, fsize = poll_until_ready(recording_id, key, verbose=verbose, debug=debug)
        else:
            filename, fsize = poll_until_ready(recording_id, key, verbose=verbose, debug=debug)
    else:
        if verbose:
            print("[VERBOSE] Creating new job on server")
        post_job(recording_id, key, body)
        filename, fsize = poll_until_ready(recording_id, key, verbose=verbose, debug=debug)

    local_name = derive_local_filename(filename, base_name)
    out_path = os.path.join(dirs['downloads'], local_name)
    dl_url = build_download_url(filename)
    update_manifest(dirs['record'], {
        'download': {
            'remote_file': filename,
            'local_file': out_path,
            'url': dl_url,
            'expected_size': fsize,
        }
    })

    if space_check and isinstance(fsize, int):
        free = get_free_space_bytes(dirs['downloads'])
        if free is not None and free < fsize:
            raise RuntimeError(f"Not enough free space: need {fsize}, have {free}")

    if not os.path.exists(out_path):
        if verbose:
            print(f"[VERBOSE] Downloading {dl_url} -> {out_path}")
        download_stream(dl_url, out_path, exclusive=not clobber)
        if verbose:
            print("[VERBOSE] Download complete")
    update_manifest(dirs['record'], {
        'download': {
            'completed': True
        }
    })

    final_out = None
    if final_format in ('opus','mp3'):
        final_out = post_process_to_final(out_path, dirs['final'], dirs['work'], base_name, final_format, opus_bitrate, mp3_bitrate, no_cleanup=no_cleanup)
        update_manifest(dirs['record'], {
            'final': {
                'file': final_out,
                'format': final_format
            }
        })

    return {
        'record_dir': dirs['record'],
        'downloads_dir': dirs['downloads'],
        'final_dir': dirs['final'],
        'work_dir': dirs['work'],
        'downloaded_file': out_path,
        'final_file': final_out,
    }
