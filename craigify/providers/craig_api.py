import requests
from urllib.parse import urlparse, parse_qs

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
    "Accept": "application/json",
}

BASE = "https://craig.horse"


def parse_input(input_val: str):
    if input_val.startswith("http://") or input_val.startswith("https://"):
        parsed = urlparse(input_val)
        if "craig.horse" in parsed.netloc and parsed.path.startswith("/rec/"):
            rec_id = parsed.path.split("/rec/")[1].split("?")[0]
            key = parse_qs(parsed.query).get("key", [None])[0]
            return rec_id, key
        if "craig.chat" in parsed.netloc and parsed.path.startswith("/home/"):
            rec_id = parsed.path.split("/home/")[1].split("/")[0]
            key = parse_qs(parsed.query).get("key", [None])[0]
            return rec_id, key
    return input_val, None


def get_metadata(recording_id: str, key: str, headers: dict | None = None):
    url = f"{BASE}/api/v1/recordings/{recording_id}?key={key}"
    h = {**DEFAULT_HEADERS, **(headers or {}), "Referer": f"{BASE}/rec/{recording_id}?key={key}"}
    r = requests.get(url, headers=h)
    r.raise_for_status()
    return r.json()


def get_duration(recording_id: str, key: str, headers: dict | None = None):
    url = f"{BASE}/api/v1/recordings/{recording_id}/duration?key={key}"
    h = {**DEFAULT_HEADERS, **(headers or {}), "Referer": f"{BASE}/rec/{recording_id}?key={key}"}
    r = requests.get(url, headers=h)
    if r.status_code != 200:
        return None
    try:
        return int(r.json().get("duration", 0))
    except Exception:
        return None


def post_job(recording_id: str, key: str, body_json: str, headers: dict | None = None):
    url = f"{BASE}/api/v1/recordings/{recording_id}/job?key={key}"
    h = {**DEFAULT_HEADERS, **(headers or {}), "Content-Type": "application/json", "Referer": f"{BASE}/rec/{recording_id}?key={key}"}
    r = requests.post(url, headers=h, data=body_json)
    r.raise_for_status()
    return r.json()


def get_job(recording_id: str, key: str, headers: dict | None = None):
    url = f"{BASE}/api/v1/recordings/{recording_id}/job?key={key}"
    h = {**DEFAULT_HEADERS, **(headers or {}), "Referer": f"{BASE}/rec/{recording_id}?key={key}"}
    r = requests.get(url, headers=h)
    r.raise_for_status()
    return r.json()


def delete_job(recording_id: str, key: str, headers: dict | None = None):
    url = f"{BASE}/api/v1/recordings/{recording_id}/job?key={key}"
    h = {**DEFAULT_HEADERS, **(headers or {}), "Referer": f"{BASE}/rec/{recording_id}?key={key}"}
    r = requests.delete(url, headers=h)
    # 200/204 OK; 404 OK (no job)
    if r.status_code not in (200, 204, 404):
        r.raise_for_status()
    return True


def build_download_url(filename: str):
    return f"{BASE}/dl/{filename}"
