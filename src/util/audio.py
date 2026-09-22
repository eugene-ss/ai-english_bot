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


def remove_files(*paths: str) -> None:
    for path in paths:
        if os.path.exists(path):
            os.remove(path)
