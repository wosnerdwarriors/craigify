import json
import os
from typing import Any, Dict


def manifest_path(record_dir: str) -> str:
    return os.path.join(record_dir, 'manifest.json')


def read_manifest(record_dir: str) -> Dict[str, Any]:
    path = manifest_path(record_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def write_manifest(record_dir: str, data: Dict[str, Any]):
    path = manifest_path(record_dir)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def update_manifest(record_dir: str, patch: Dict[str, Any]):
    m = read_manifest(record_dir)
    m.update(patch)
    write_manifest(record_dir, m)
