#!/usr/bin/env python3
# CraigProessor.py - Multi-track FLAC downloader with robust CLI and metadata extraction
import argparse
import os
import re
import requests
import sys
import time
import random
import string
import zipfile
import subprocess
import shutil
from datetime import datetime
from urllib.parse import urlparse, parse_qs

def extractRecordingIdAndKey(inputVal):
	if inputVal.startswith("http://") or inputVal.startswith("https://"):
		parsed = urlparse(inputVal)
		if "craig.horse" in parsed.netloc and parsed.path.startswith("/rec/"):
			recId = parsed.path.split("/rec/")[1].split("?")[0]
			key = parse_qs(parsed.query).get("key", [None])[0]
			return recId, key
		elif "craig.chat" in parsed.netloc and parsed.path.startswith("/home/"):
			recId = parsed.path.split("/home/")[1].split("/")[0]
			key = parse_qs(parsed.query).get("key", [None])[0]
			return recId, key
	if validateRecordingId(inputVal):
		return inputVal, None
	return None, None

def validateRecordingId(rid):
	return bool(re.fullmatch(r"[A-Za-z0-9]{12}", rid))

def fetchMetadata(recordingId, key, verbose=False, debug=False):
	url = f"https://craig.horse/api/v1/recordings/{recordingId}?key={key}"
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
		"Accept": "application/json",
		"Referer": f"https://craig.horse/rec/{recordingId}?key={key}"
	}
	if verbose:
		print(f"[VERBOSE] Fetching metadata: {url}")
	resp = requests.get(url, headers=headers)
	if debug:
		print(f"[DEBUG] Metadata status: {resp.status_code}")
		print(f"[DEBUG] Headers: {resp.headers}")
		print(f"[DEBUG] Body: {repr(resp.text[:1000])}")
	if resp.status_code != 200:
		print(f"[ERROR] Could not fetch metadata: {resp.status_code}")
		sys.exit(1)
	return resp.json()

def fetchDuration(recordingId, key, verbose=False, debug=False):
	url = f"https://craig.horse/api/v1/recordings/{recordingId}/duration?key={key}"
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
		"Accept": "application/json",
		"Referer": f"https://craig.horse/rec/{recordingId}?key={key}"
	}
	if verbose:
		print(f"[VERBOSE] Fetching duration: {url}")
	resp = requests.get(url, headers=headers)
	if debug:
		print(f"[DEBUG] Duration status: {resp.status_code}")
		print(f"[DEBUG] Duration body: {repr(resp.text)}")
	if resp.status_code != 200:
		return None
	try:
		data = resp.json()
		return int(data.get('duration', 0))
	except Exception:
		return None

def post_job(recordingId, key, job_body, verbose=False, debug=False):
	url = f"https://craig.horse/api/v1/recordings/{recordingId}/job?key={key}"
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
		"Accept": "application/json",
		"Content-Type": "application/json",
		"Referer": f"https://craig.horse/rec/{recordingId}?key={key}"
	}
	if verbose:
		print(f"[VERBOSE] Creating job: {url}")
		print(f"[VERBOSE] Body: {job_body}")
	resp = requests.post(url, headers=headers, data=job_body)
	if debug:
		print(f"[DEBUG] Job POST status: {resp.status_code}")
		print(f"[DEBUG] Job POST body: {repr(resp.text)}")
	if resp.status_code != 200:
		print(f"[ERROR] Failed to create job: {resp.status_code}")
		sys.exit(1)
	return resp.json()

def get_job(recordingId, key, verbose=False, debug=False):
	url = f"https://craig.horse/api/v1/recordings/{recordingId}/job?key={key}"
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
		"Accept": "application/json",
		"Referer": f"https://craig.horse/rec/{recordingId}?key={key}"
	}
	resp = requests.get(url, headers=headers)
	if debug:
		print(f"[DEBUG] Job GET status: {resp.status_code}")
		print(f"[DEBUG] Job GET body: {repr(resp.text)}")
	if resp.status_code != 200:
		print(f"[ERROR] Failed to fetch job: {resp.status_code}")
		sys.exit(1)
	return resp.json()

def delete_job(recordingId, key, verbose=False, debug=False):
	url = f"https://craig.horse/api/v1/recordings/{recordingId}/job?key={key}"
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
		"Accept": "application/json",
		"Referer": f"https://craig.horse/rec/{recordingId}?key={key}"
	}
	if verbose:
		print(f"[VERBOSE] Deleting existing job: {url}")
	resp = requests.delete(url, headers=headers)
	if debug:
		print(f"[DEBUG] Job DELETE status: {resp.status_code}")
		print(f"[DEBUG] Job DELETE body: {repr(resp.text)}")
	# 200/204 are OK; if 404 no job, also OK
	if resp.status_code not in (200, 204, 404):
		print(f"[WARN] Failed to delete existing job (status {resp.status_code}), proceeding anyway")

def normalizeFilename(s):
	s = re.sub(r'[^\w\-_. ]', '_', s)
	s = re.sub(r'[\s]+', '_', s)
	return s.strip('_')

def normalize_slug(s):
	if not s:
		return "unknown"
	s = re.sub(r'[^A-Za-z0-9._-]+', '_', s)
	s = re.sub(r'_+', '_', s)
	return s.strip('_')

def parse_start_iso(iso_str):
	try:
		if iso_str.endswith('Z'):
			iso_str = iso_str[:-1] + '+00:00'
		return datetime.fromisoformat(iso_str)
	except Exception:
		return None

def format_duration_compact(seconds):
	try:
		total = int(seconds or 0)
	except Exception:
		total = 0
	h = total // 3600
	m = (total % 3600) // 60
	s = total % 60
	if h > 0:
		return f"{h}h{m:02d}m{s:02d}s"
	if m > 0:
		return f"{m}m{s:02d}s"
	return f"{s}s"

def build_base_filename(metadata):
	rec = metadata.get('recording', {})
	users = metadata.get('users', [])
	rec_id = rec.get('id', 'unknown')
	start_iso = rec.get('startTime') or ''
	guild = (rec.get('guild') or {}).get('name')
	channel = (rec.get('channel') or {}).get('name')
	dur = metadata.get('duration', 0)
	dt = parse_start_iso(start_iso)
	if dt is not None:
		ts = dt.strftime('%Y%m%dT%H%M%SZ') if dt.tzinfo else dt.strftime('%Y%m%dT%H%M%S')
	else:
		ts = genTimestamp()
	server_slug = normalize_slug(guild)
	channel_slug = normalize_slug(channel)
	dur_str = format_duration_compact(dur)
	user_count = len(users)
	return f"{ts}_{server_slug}_{channel_slug}_{rec_id}_{user_count}u_{dur_str}"

def derive_local_filename(remote_filename, base):
	# Preserve multi-part extension (e.g., .flac.zip)
	dot = remote_filename.find('.')
	if dot == -1:
		return base
	return base + remote_filename[dot:]

def randSuffix():
	return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

def genTimestamp():
	return time.strftime('%Y%m%d_%H%M%S', time.gmtime())

def ensureUniqueDir(basePath, clobber=False):
	if not os.path.exists(basePath):
		try:
			os.makedirs(basePath)
			return basePath
		except Exception as e:
			print(f"[ERROR] Could not create directory {basePath}: {e}")
			sys.exit(1)
	if clobber:
		return basePath
	attempts = 0
	while attempts < 50:
		suffix = f"_{genTimestamp()}_{randSuffix()}"
		newPath = basePath + suffix
		if not os.path.exists(newPath):
			try:
				os.makedirs(newPath)
				return newPath
			except Exception as e:
				print(f"[ERROR] Could not create directory {newPath}: {e}")
				sys.exit(1)
		attempts += 1
	print(f"[ERROR] Too many duplicate directories, aborting.")
	sys.exit(1)

def summarizeMetadata(metadata):
	rec = metadata.get("recording", {})
	users = metadata.get("users", [])
	rec_id = rec.get("id", "Unknown")
	start = rec.get("startTime", "Unknown")
	duration = metadata.get("duration", 0)
	guild = (rec.get("guild") or {}).get("name", "Unknown")
	channel = (rec.get("channel") or {}).get("name", "Unknown")
	print("\n🎙️ Recording Summary:")
	print(f"  ID:        {rec_id}")
	print(f"  Started:   {start}")
	print(f"  Server:    {guild}")
	print(f"  Channel:   {channel}")
	print(f"  Duration:  {int(duration)} seconds ({time.strftime('%H:%M:%S', time.gmtime(duration))})")
	print(f"  Users:     {len(users)}")
	for u in users:
		print(f"    - {u.get('username','unknown')} (track {u.get('track','?')})")
	print("")

def get_free_space_bytes(path):
	# Must be an existing path
	orig_path = path
	while not os.path.exists(path):
		path = os.path.dirname(path)
		if path == '' or path == '/':
			break
	try:
		stat = os.statvfs(path)
		return stat.f_frsize * stat.f_bavail
	except Exception as e:
		print(f"[WARN] Could not statvfs {orig_path}: {e}")
		return None

def get_remote_file_size(url):
	try:
		resp = requests.head(url, allow_redirects=True)
		if resp.status_code == 200 and 'Content-Length' in resp.headers:
			return int(resp.headers['Content-Length'])
	except Exception as e:
		print(f"[WARN] Could not get size for {url}: {e}")
	return None

def download_file(url, outpath, exclusive=False):
	try:
		with requests.get(url, stream=True) as r:
			r.raise_for_status()
			mode = 'xb' if exclusive else 'wb'
			with open(outpath, mode) as f:
				for chunk in r.iter_content(chunk_size=8192):
					f.write(chunk)
		return True
	except Exception as e:
		print(f"[ERROR] Download failed for {url}: {e}")
		return False

def parseArgs():
	parser = argparse.ArgumentParser(description="CraigBot Utility")
	parser.add_argument("-i", "--input", required=True, help="Recording URL or ID")
	parser.add_argument("--key", help="Recording key (if not included in URL)")
	parser.add_argument("--output-dir", help="Root output directory. We'll create a per-recording subfolder with downloads/, work/, and final/ inside (default: ./craig/recordings)")
	parser.add_argument("--clobber", action="store_true", help="Overwrite files/folders if they exist")
	parser.add_argument("--space-awareness-disable", action="store_true", help="Disable disk space check before downloading (enabled by default)")
	parser.add_argument("--action", choices=["metadata", "download"], default="metadata", help="Action to perform")
	parser.add_argument("--file-type", choices=["flac","mp3","vorbis","aac","adpcm","wav8","opus","oggflac","heaac"], default="flac", help="Audio format to request")
	parser.add_argument("--mix", choices=["individual","mixed"], default="individual", help="Individual (zip of per-track) or mixed (single track)")
	parser.add_argument("--final-format", choices=["none","opus","mp3"], default="none", help="Optional post-process to final format")
	parser.add_argument("--opus-bitrate", default="24k", help="Opus bitrate for final output, e.g. 24k, 32k")
	parser.add_argument("--mp3-bitrate", default="128k", help="MP3 bitrate for final output, e.g. 128k")
	parser.add_argument("--no-cleanup", action="store_true", help="Keep intermediate files (zip, extracted FLACs)")
	parser.add_argument("--force-job-recreate", action="store_true", help="Delete any existing job and create a new one")
	parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
	parser.add_argument("--debug", action="store_true", help="Enable debug mode (dump all HTTP and parsing info)")
	return parser.parse_args()


# Actions
def action_metadata(metadata):
	summarizeMetadata(metadata)

def poll_until_ready(recordingId, key, interval=2, timeout=600, verbose=False, debug=False):
	start = time.time()
	while True:
		job = get_job(recordingId, key, verbose=verbose, debug=debug)
		data = job.get('job')
		if data is None:
			if verbose:
				print("[VERBOSE] No job yet; waiting...")
		else:
			status = data.get('status')
			fname = data.get('outputFileName')
			fsize = data.get('outputSize')
			if verbose:
				print(f"[VERBOSE] Job status: {status}, file: {fname}, size: {fsize}")
			if status in ('finished','complete','completed','done') and fname:
				return fname, fsize
			if status in ('error','failed','cancelled','canceled'):
				print(f"[ERROR] Job failed with status: {status}")
				sys.exit(1)
		if time.time() - start > timeout:
			print("[ERROR] Timed out waiting for job to complete")
			sys.exit(1)
		time.sleep(interval)

def action_download(metadata, args):
	# Create structured directories to avoid cluttering repo root
	rec = metadata.get('recording', {})
	base_name = build_base_filename(metadata)
	root_dir = args.output_dir or os.path.join(os.getcwd(), 'craig', 'recordings')
	record_dir = ensureUniqueDir(os.path.join(root_dir, base_name), clobber=args.clobber)
	downloads_dir = os.path.join(record_dir, 'downloads')
	work_dir = os.path.join(record_dir, 'work')
	final_dir = os.path.join(record_dir, 'final')
	os.makedirs(downloads_dir, exist_ok=True)
	os.makedirs(work_dir, exist_ok=True)
	os.makedirs(final_dir, exist_ok=True)
	print(f"[INFO] Recording folder: {record_dir}")
	if args.verbose:
		print(f"[VERBOSE] downloads: {downloads_dir}\n[VERBOSE] work: {work_dir}\n[VERBOSE] final: {final_dir}")

	# Determine job options
	import json as _json
	if args.mix == 'mixed':
		job_body = _json.dumps({
			'type': 'recording',
			'options': {
				'container': 'mix',
				'format': args.file_type
			}
		})
	else:
		job_body = _json.dumps({
			'type': 'recording',
			'options': {
				'container': 'zip',
				'format': args.file_type
			}
		})

	# Need id and key again
	rid, key = extractRecordingIdAndKey(args.input)
	key = key or args.key
	if not key:
		print('[ERROR] --key required (or include in URL)')
		sys.exit(1)

	# Check for existing job first
	existing = get_job(rid, key, verbose=args.verbose, debug=args.debug)
	ej = existing.get('job') if isinstance(existing, dict) else None
	filename = None
	fsize = None

	if ej and not args.force_job_recreate:
		status = ej.get('status')
		if args.verbose:
			print(f"[VERBOSE] Existing job detected with status: {status}")
		if status in ('finished','complete','completed','done') and ej.get('outputFileName'):
			filename = ej.get('outputFileName')
			fsize = ej.get('outputSize')
		elif status in ('error','failed','cancelled','canceled'):
			if args.verbose:
				print("[VERBOSE] Existing job is failed/canceled; creating a new one")
			post_job(rid, key, job_body, verbose=args.verbose, debug=args.debug)
			filename, fsize = poll_until_ready(rid, key, verbose=args.verbose, debug=args.debug)
		else:
			# pending/running; poll
			filename, fsize = poll_until_ready(rid, key, verbose=args.verbose, debug=args.debug)
	else:
		if args.force_job_recreate and ej:
			delete_job(rid, key, verbose=args.verbose, debug=args.debug)
		# Create new job
		post_job(rid, key, job_body, verbose=args.verbose, debug=args.debug)
		filename, fsize = poll_until_ready(rid, key, verbose=args.verbose, debug=args.debug)
	# Build metadata-based local name and download
	local_name = derive_local_filename(filename, base_name)
	dl_url = f"https://craig.horse/dl/{filename}"
	out_path = os.path.join(downloads_dir, local_name)
	if not args.space_awareness_disable:
		free = get_free_space_bytes(downloads_dir)
		if fsize is not None and isinstance(fsize, int) and free is not None and free < fsize:
			print(f"[ERROR] Not enough free space: need {fsize} bytes, have {free} bytes")
			sys.exit(1)
	if os.path.exists(out_path) and not args.clobber:
		print(f"[INFO] File already exists, skipping download: {out_path}")
	else:
		print(f"[INFO] Downloading {dl_url} -> {out_path}")
		ok = download_file(dl_url, out_path, exclusive=not args.clobber)
		if not ok:
			print("[ERROR] Download failed")
			sys.exit(1)
		print("[DONE] Download complete")

	# Post-process to final format if requested
	if args.final_format != 'none':
		post_process_to_final(out_path, final_dir, work_dir, base_name, args)


def _unzip_to_dir(zip_path, dest_dir, verbose=False):
	if verbose:
		print(f"[VERBOSE] Unzipping {zip_path} -> {dest_dir}")
	with zipfile.ZipFile(zip_path, 'r') as zf:
		zf.extractall(dest_dir)
	return dest_dir

def _find_files_by_ext(root_dir, exts):
	found = []
	for base, _, files in os.walk(root_dir):
		for name in files:
			if any(name.lower().endswith(ext) for ext in exts):
				found.append(os.path.join(base, name))
	return found

def _ffmpeg_exists():
	return shutil.which('ffmpeg') is not None

def _mix_to_opus(inputs, output_path, bitrate="24k", verbose=False):
	if not _ffmpeg_exists():
		print("[ERROR] ffmpeg not found in PATH. Please install ffmpeg.")
		sys.exit(1)
	# Build ffmpeg command: amix all inputs, mono 48k, encode libopus
	cmd = ['ffmpeg', '-y']
	for inp in inputs:
		cmd += ['-i', inp]
	n = len(inputs)
	# Normalize off; simple sum-mix; then force mono and 48k
	filter_complex = f"amix=inputs={n}:dropout_transition=0:normalize=0, aformat=channel_layouts=mono, aresample=48000"
	cmd += [
		'-filter_complex', filter_complex,
		'-c:a', 'libopus',
		'-b:a', bitrate,
		'-vbr', 'on',
		'-application', 'voip',
		'-ac', '1',
		'-ar', '48000',
		output_path
	]
	if verbose:
		print(f"[VERBOSE] Running ffmpeg: {' '.join(cmd)}")
	try:
		subprocess.run(cmd, check=True)
	except subprocess.CalledProcessError as e:
		print(f"[ERROR] ffmpeg failed: {e}")
		sys.exit(1)

def _transcode_to_opus(input_path, output_path, bitrate="24k", verbose=False):
	if not _ffmpeg_exists():
		print("[ERROR] ffmpeg not found in PATH. Please install ffmpeg.")
		sys.exit(1)
	cmd = [
		'ffmpeg','-y','-i', input_path,
		'-c:a','libopus','-b:a', bitrate,'-vbr','on','-application','voip','-ac','1','-ar','48000',
		output_path
	]
	if verbose:
		print(f"[VERBOSE] Running ffmpeg: {' '.join(cmd)}")
	try:
		subprocess.run(cmd, check=True)
	except subprocess.CalledProcessError as e:
		print(f"[ERROR] ffmpeg failed: {e}")
		sys.exit(1)

def _mix_to_mp3(inputs, output_path, bitrate="128k", verbose=False):
	if not _ffmpeg_exists():
		print("[ERROR] ffmpeg not found in PATH. Please install ffmpeg.")
		sys.exit(1)
	cmd = ['ffmpeg', '-y']
	for inp in inputs:
		cmd += ['-i', inp]
	n = len(inputs)
	filter_complex = f"amix=inputs={n}:dropout_transition=0:normalize=0, aformat=channel_layouts=mono, aresample=48000"
	cmd += [
		'-filter_complex', filter_complex,
		'-c:a', 'libmp3lame',
		'-b:a', bitrate,
		'-ac', '1',
		'-ar', '48000',
		output_path
	]
	if verbose:
		print(f"[VERBOSE] Running ffmpeg: {' '.join(cmd)}")
	try:
		subprocess.run(cmd, check=True)
	except subprocess.CalledProcessError as e:
		print(f"[ERROR] ffmpeg failed: {e}")
		sys.exit(1)

def _transcode_to_mp3(input_path, output_path, bitrate="128k", verbose=False):
	if not _ffmpeg_exists():
		print("[ERROR] ffmpeg not found in PATH. Please install ffmpeg.")
		sys.exit(1)
	cmd = [
		'ffmpeg','-y','-i', input_path,
		'-c:a','libmp3lame','-b:a', bitrate,'-ac','1','-ar','48000',
		output_path
	]
	if verbose:
		print(f"[VERBOSE] Running ffmpeg: {' '.join(cmd)}")
	try:
		subprocess.run(cmd, check=True)
	except subprocess.CalledProcessError as e:
		print(f"[ERROR] ffmpeg failed: {e}")
		sys.exit(1)

def post_process_to_final(downloaded_path, final_dir, work_dir, base_name, args):
	# Decide strategy based on downloaded file type and requested final format
	final_ext = args.final_format
	if final_ext == 'opus':
		final_name = base_name + '.opus'
		final_path = os.path.join(final_dir, final_name)
		# If we have a zip (stems), unzip and mix
		if downloaded_path.lower().endswith('.zip'):
			stems_dir = os.path.join(work_dir, 'stems')
			os.makedirs(stems_dir, exist_ok=True)
			_unzip_to_dir(downloaded_path, stems_dir, verbose=args.verbose)
			flacs = _find_files_by_ext(stems_dir, ['.flac', '.wav', '.ogg'])
			if len(flacs) == 0:
				print("[ERROR] No audio stems found after unzip.")
				sys.exit(1)
			_mix_to_opus(flacs, final_path, bitrate=args.opus_bitrate, verbose=args.verbose)
			print(f"[DONE] Created {final_path}")
			if not args.no_cleanup:
				try:
					shutil.rmtree(stems_dir)
				except Exception:
					pass
		else:
			# Single file downloaded (e.g., server-mixed). Transcode to opus.
			_transcode_to_opus(downloaded_path, final_path, bitrate=args.opus_bitrate, verbose=args.verbose)
			print(f"[DONE] Created {final_path}")
			# Keep original download in downloads/ by default
	elif final_ext == 'mp3':
		final_name = base_name + '.mp3'
		final_path = os.path.join(final_dir, final_name)
		if downloaded_path.lower().endswith('.zip'):
			stems_dir = os.path.join(work_dir, 'stems')
			os.makedirs(stems_dir, exist_ok=True)
			_unzip_to_dir(downloaded_path, stems_dir, verbose=args.verbose)
			flacs = _find_files_by_ext(stems_dir, ['.flac', '.wav', '.ogg'])
			if len(flacs) == 0:
				print("[ERROR] No audio stems found after unzip.")
				sys.exit(1)
			_mix_to_mp3(flacs, final_path, bitrate=args.mp3_bitrate, verbose=args.verbose)
			print(f"[DONE] Created {final_path}")
			if not args.no_cleanup:
				try:
					shutil.rmtree(stems_dir)
				except Exception:
					pass
		else:
			_transcode_to_mp3(downloaded_path, final_path, bitrate=args.mp3_bitrate, verbose=args.verbose)
			print(f"[DONE] Created {final_path}")
			# Keep original download in downloads/ by default


def main():
	args = parseArgs()

	rec_id, key = extractRecordingIdAndKey(args.input)
	if not validateRecordingId(rec_id):
		print("[ERROR] Invalid recording ID or URL")
		sys.exit(1)
	if not key:
		key = args.key
	if not key:
		print("[ERROR] Recording key missing. Provide via URL or --key")
		sys.exit(1)

	metadata = fetchMetadata(rec_id, key, verbose=args.verbose, debug=args.debug)
	# Always attempt to fetch duration if missing/zero
	if not metadata.get('duration'):
		dur = fetchDuration(rec_id, key, verbose=args.verbose, debug=args.debug)
		if dur and dur > 0:
			metadata['duration'] = dur

	if args.action == "metadata":
		action_metadata(metadata)
	elif args.action == "download":
		action_download(metadata, args)

if __name__ == "__main__":
	main()
