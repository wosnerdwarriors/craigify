import shutil
import subprocess


def ffmpeg_exists() -> bool:
    return shutil.which('ffmpeg') is not None


def run_ffmpeg(cmd: list[str]):
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e}") from e
