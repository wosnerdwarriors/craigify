import os


def run_summarize_cli(*, record_dir: str, style: str = "brief"):
    # Stub: look for transcripts and print what would be summarized
    transcripts_dir = os.path.join(record_dir, 'final', 'transcripts')
    if not os.path.isdir(transcripts_dir):
        print("[summarize] No transcripts found at:", transcripts_dir)
        return
    files = [os.path.join(transcripts_dir, n) for n in os.listdir(transcripts_dir) if n.lower().endswith(('.vtt','.srt','.json','.jsonl','.txt'))]
    if not files:
        print("[summarize] No transcript files to summarize.")
        return
    print(f"[summarize] (stub) Would summarize ({style}) files:")
    for f in files:
        print("  ", f)
