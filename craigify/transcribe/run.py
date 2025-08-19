import os


def run_transcribe_cli(*, record_dir: str, mode: str = "mixed"):
    # Stub: detect audio files and print what would be transcribed
    final_dir = os.path.join(record_dir, 'final')
    downloads_dir = os.path.join(record_dir, 'downloads')

    if mode == 'mixed':
        # prefer final mixed file (opus/mp3), else any single downloaded mix
        candidates = []
        for n in os.listdir(final_dir):
            if n.lower().endswith(('.opus', '.mp3', '.wav', '.flac', '.ogg')):
                candidates.append(os.path.join(final_dir, n))
        if not candidates:
            for n in os.listdir(downloads_dir):
                if not n.lower().endswith('.zip') and n.lower().endswith(('.opus', '.mp3', '.wav', '.flac', '.ogg')):
                    candidates.append(os.path.join(downloads_dir, n))
        if not candidates:
            print("[transcribe] No mixed audio found to transcribe.")
            return
        print("[transcribe] (stub) Would transcribe:")
        for c in candidates:
            print("  ", c)
    else:
        # tracks: expect zip of stems downloaded; or stems extracted in work/stems
        work_stems = os.path.join(record_dir, 'work', 'stems')
        if os.path.isdir(work_stems):
            stems = [os.path.join(work_stems, n) for n in os.listdir(work_stems) if n.lower().endswith(('.flac','.wav','.ogg'))]
            if stems:
                print("[transcribe] (stub) Would transcribe stems:")
                for s in stems:
                    print("  ", s)
                return
        zips = [n for n in os.listdir(downloads_dir) if n.lower().endswith('.zip')]
        if not zips:
            print("[transcribe] No stems zip found; download with --mix individual first.")
            return
        print("[transcribe] (stub) Would unzip and transcribe:")
        for z in zips:
            print("  ", os.path.join(downloads_dir, z))
