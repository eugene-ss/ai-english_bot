import os
import subprocess

def convert_ogg_to_wav(input_path: str, output_path: str) -> None:
    command = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def convert_wav_to_ogg_opus(input_path: str, output_path: str) -> None:
    """Telegram voice требует OGG/Opus, моно."""
    command = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vn",
        "-ac", "1",
        "-c:a", "libopus",
        "-b:a", "48k",
        output_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:] if result.stderr else "ffmpeg opus encode failed")

def remove_files(*paths: str) -> None:
    for path in paths:
        if os.path.exists(path):
            os.remove(path)
