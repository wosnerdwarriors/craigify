import os
import re
import time
import random
import string
from datetime import datetime


def normalize_slug(s: str | None) -> str:
    if not s:
        return "unknown"
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def format_duration_compact(seconds: int | None) -> str:
    total = int(seconds or 0)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def parse_start_iso(iso_str: str | None):
    if not iso_str:
        return None
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        return datetime.fromisoformat(iso_str)
    except Exception:
        return None


def gen_timestamp() -> str:
    return time.strftime('%Y%m%d_%H%M%S', time.gmtime())


def rand_suffix() -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))


def build_base_name(metadata: dict) -> str:
    rec = metadata.get('recording', {})
    rec_id = rec.get('id', 'unknown')
    start_iso = rec.get('startTime') or ''
    guild = (rec.get('guild') or {}).get('name')
    channel = (rec.get('channel') or {}).get('name')
    dur = metadata.get('duration', 0)
    dt = parse_start_iso(start_iso)
    if dt is not None:
        ts = dt.strftime('%Y%m%dT%H%M%SZ') if dt.tzinfo else dt.strftime('%Y%m%dT%H%M%S')
    else:
        ts = gen_timestamp()
    server_slug = normalize_slug(guild)
    channel_slug = normalize_slug(channel)
    dur_str = format_duration_compact(dur)
    user_count = len(metadata.get('users', []))
    return f"{ts}_{server_slug}_{channel_slug}_{rec_id}_{user_count}u_{dur_str}"


def derive_local_filename(remote_filename: str, base: str) -> str:
    dot = remote_filename.find('.')
    if dot == -1:
        return base
    return base + remote_filename[dot:]


def ensure_unique_dir(base_path: str, clobber: bool = False) -> str:
    if not os.path.exists(base_path):
        os.makedirs(base_path, exist_ok=True)
        return base_path
    if clobber:
        return base_path
    for _ in range(50):
        suffix = f"_{gen_timestamp()}_{rand_suffix()}"
        new_path = base_path + suffix
        if not os.path.exists(new_path):
            os.makedirs(new_path, exist_ok=True)
            return new_path
    raise RuntimeError("Too many duplicate directories; aborting")


def get_recording_dirs(output_root: str, base_name: str, clobber: bool = False):
    record_dir = ensure_unique_dir(os.path.join(output_root, base_name), clobber=clobber)
    downloads = os.path.join(record_dir, 'downloads')
    work = os.path.join(record_dir, 'work')
    final = os.path.join(record_dir, 'final')
    meta = os.path.join(record_dir, 'meta')
    logs = os.path.join(record_dir, 'logs')
    for d in (downloads, work, final, meta, logs):
        os.makedirs(d, exist_ok=True)
    return {
        'record': record_dir,
        'downloads': downloads,
        'work': work,
        'final': final,
        'meta': meta,
        'logs': logs,
    }


def find_existing_record_dir(output_root: str, base_name: str) -> str | None:
    """Return an existing record dir under output_root whose basename starts with base_name.

    If multiple matches are found, return the most recently modified one. Return None if not found.
    """
    root = os.path.abspath(output_root)
    if not os.path.isdir(root):
        return None
    candidates = []
    for name in os.listdir(root):
        if not name.startswith(base_name):
            continue
        full = os.path.join(root, name)
        if os.path.isdir(full):
            candidates.append(full)
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]
