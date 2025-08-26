#!/usr/bin/env python3
# This is a legacy file that i had written before trying to write an "all in one tool"
# i keep this around for reference and will be deleted at some stage



import argparse
import glob
import os
import time
import json
import subprocess
from datetime import timedelta
from difflib import SequenceMatcher

import torch
import whisper
from tqdm import tqdm
from whisper.tokenizer import LANGUAGES, TO_LANGUAGE_CODE


def parseArgs():
	supportedLangs = sorted(set(TO_LANGUAGE_CODE.keys()).union(set(LANGUAGES.values())))
	exampleText = """\
Examples:
  whisper_transcribe.py \\
    --audio-files *.flac \\
    --model medium \\
    --language en \\
    --trim-silence \\
    --dedupe-lines \\
    --use-gpu \\
    --processing-dir speaker_output \\
    --final-file merged_transcript.txt
"""

	parser = argparse.ArgumentParser(
		description="Transcribe multiple audio files using Whisper with optional silence trimming, deduplication, and GPU detection.",
		epilog=exampleText,
		formatter_class=argparse.RawDescriptionHelpFormatter
	)

	parser.add_argument("--audio-files", nargs="+", required=True,
		help="List or glob of audio files to transcribe (e.g. *.flac)")
	parser.add_argument("--model", default="medium",
		help="Whisper model to use (tiny, base, small, medium, large) [default: medium]")
	parser.add_argument("--language", default="auto",
		help="Language (use 'auto' for detection, or one of: {}) [default: auto]".format(', '.join(supportedLangs)))
	parser.add_argument("--keep-context", dest="condition_on_previous_text", action="store_true", default=True,
		help="Use previous chunk as context for better continuity (Whisper's --condition_on_previous_text) [default: True]")
	parser.add_argument("--no-keep-context", dest="condition_on_previous_text", action="store_false",
		help="Disable context chaining to avoid hallucinated repeats")
	parser.add_argument("--trim-silence", action="store_true",
		help="Trim silence from audio using ffmpeg before transcribing [default: False]")
	parser.add_argument("--silence-threshold", default="-50dB",
		help="Silence threshold for trimming [default: -50dB]")
	parser.add_argument("--dedupe-lines", action="store_true",
		help="Remove repeated/duplicated lines in merged transcript [default: False]")
	parser.add_argument("--output-format", default="txt", choices=["txt", "json", "vtt", "srt", "tsv", "all"],
		help="Transcript output format [default: txt]")
	parser.add_argument("--verbose", action="store_true",
		help="Enable Whisper debug/status output [default: True]")
	parser.add_argument("--processing-dir", default="transcription_output",
		help="Directory for per-speaker outputs [default: transcription_output]")
	parser.add_argument("--final-file", required=True,
		help="Path to save final combined transcript")
	parser.add_argument("--process-subset-minutes", type=int, default=0,
		help="Limit transcription to first N minutes of each file for debugging (0 = full) [default: 0]")
	parser.add_argument("--use-gpu", action="store_true",
		help="Force GPU usage. Fail if not available.")
	parser.add_argument("--prefer-gpu", action="store_true",
		help="Prefer GPU if available, else fallback to CPU.")

	return parser.parse_args()


def normalizeLanguage(lang):
	if lang == "auto":
		return None
	langLower = lang.lower()
	if langLower in TO_LANGUAGE_CODE:
		return TO_LANGUAGE_CODE[langLower]
	if langLower in LANGUAGES.values():
		return langLower
	raise ValueError(f"Unsupported language: {lang}")


def trimSilenceWithFFmpeg(inputPath, outputPath, threshold):
	cmd = [
		"ffmpeg", "-y", "-i", inputPath,
		"-af", f"silenceremove=start_periods=1:start_threshold={threshold}:start_silence=0.3",
		outputPath
	]
	subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def isSimilar(a, b, threshold=0.9):
	return SequenceMatcher(None, a, b).ratio() > threshold


def detectDevice(args):
	if args.use_gpu:
		if not torch.cuda.is_available():
			print("❌ GPU requested but not available. Install CUDA or check your drivers.")
			exit(1)
		return "cuda"

	if args.prefer_gpu and torch.cuda.is_available():
		print("✅ GPU detected, using CUDA")
		return "cuda"

	return "cpu"


def main():
	args = parseArgs()
	device = detectDevice(args)

	audioPaths = []
	for pattern in args.audio_files:
		audioPaths.extend(sorted(glob.glob(pattern)))

	if not audioPaths:
		print("❌ No matching audio files found.")
		return

	os.makedirs(args.processing_dir, exist_ok=True)
	langCode = normalizeLanguage(args.language)

	print(f"🧠 Loading model: {args.model} (device: {device})")
	model = whisper.load_model(args.model, device=device)

	mergedSegments = []

	print(f"🎧 Processing {len(audioPaths)} file(s)...\n")

	for path in tqdm(audioPaths, desc="Processing"):
		start = time.time()
		speaker = os.path.splitext(os.path.basename(path))[0]
		processPath = path

		if args.trim_silence:
			trimmedPath = os.path.join(args.processing_dir, f"{speaker}_trimmed.flac")
			trimSilenceWithFFmpeg(path, trimmedPath, args.silence_threshold)
			processPath = trimmedPath

		kwargs = {
			"language": langCode,
			"verbose": args.verbose,
			"condition_on_previous_text": args.condition_on_previous_text
		}
		if args.process_subset_minutes > 0:
			kwargs["clip_timestamps"] = f"0,{args.process_subset_minutes * 60}"

		result = model.transcribe(processPath, **kwargs)

		baseOut = os.path.join(args.processing_dir, speaker)
		formats = ["txt", "json", "vtt", "srt", "tsv"] if args.output_format == "all" else [args.output_format]

		for fmt in formats:
			with open(f"{baseOut}.{fmt}", "w", encoding="utf-8") as f:
				if fmt == "txt":
					for seg in result["segments"]:
						startTime = str(timedelta(seconds=int(seg["start"])))
						f.write(f"[{startTime}] {seg['text'].strip()}\n")
				elif fmt == "json":
					json.dump(result["segments"], f, indent=2)
				else:
					f.write(f"⚠️ Format {fmt} not supported in this script.\n")

		for seg in result["segments"]:
			mergedSegments.append({
				"start": seg["start"],
				"end": seg["end"],
				"speaker": speaker,
				"text": seg["text"].strip()
			})

		tqdm.write(f"✅ {speaker} done in {time.time() - start:.1f}s")

	# Sort by start time
	mergedSegments.sort(key=lambda x: x["start"])

	# Dedupe
	if args.dedupe_lines:
		deduped = []
		for seg in mergedSegments:
			if deduped and isSimilar(deduped[-1]["text"], seg["text"]) and (seg["start"] - deduped[-1]["end"] < 3):
				continue
			deduped.append(seg)
		mergedSegments = deduped

	# Final output
	with open(args.final_file, "w", encoding="utf-8") as f:
		if args.output_format == "json":
			json.dump(mergedSegments, f, indent=2)
		else:
			for seg in mergedSegments:
				startTime = str(timedelta(seconds=int(seg["start"])))
				f.write(f"[{startTime}] {seg['speaker']}: {seg['text']}\n")

	print("\n✅ Done.")
	print(f"📁 Final merged transcript: {args.final_file}")
	print(f"📂 Intermediate files: {args.processing_dir}")


if __name__ == "__main__":
	main()

