import os
import subprocess

def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = result.stderr[-800:] if result.stderr else "no stderr"
        raise RuntimeError(f"ffmpeg failed ({' '.join(command[:4])}...): {tail}")

def convert_ogg_to_wav(input_path: str, output_path: str) -> None:
    """OGG/Opus от Telegram в WAV 16 кГц моно — формат, который ждёт Whisper."""
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", input_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ])

def convert_wav_to_ogg_opus(
    input_path: str, output_path: str, tempo: float = 1.0
) -> None:
    """Telegram voice требует OGG/Opus, моно.

    `tempo` замедляет или ускоряет речь фильтром atempo, который сохраняет
    высоту голоса. Допустимый диапазон фильтра — от 0.5 до 2.0.
    """
    command = ["ffmpeg", "-y", "-i", input_path, "-vn", "-ac", "1"]
    if abs(tempo - 1.0) > 1e-3:
        command += ["-filter:a", f"atempo={max(0.5, min(2.0, tempo)):.3f}"]
    command += ["-c:a", "libopus", "-b:a", "48k", output_path]
    _run_ffmpeg(command)

def remove_files(*paths: str) -> None:
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
