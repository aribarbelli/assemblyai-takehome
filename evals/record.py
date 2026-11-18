"""Record the evaluation clips, one at a time, as 16 kHz mono WAV files in evals/clips/.

    python evals/record.py            # walks through every clip (skips ones already recorded)
    python evals/record.py hesitant   # re-record one clip by name

For each clip: press Enter to start, say the line, press Enter to stop. Then play it back, keep it,
or redo it.
"""

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from clips import CLIPS

SAMPLE_RATE = 16000  # what the streaming STT model receives in the tutor
OUT_DIR = Path(__file__).parent / "clips"


def record() -> np.ndarray:
    chunks: list[np.ndarray] = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        callback=lambda data, *_: chunks.append(data.copy())):
        input("  ● Recording... press Enter to stop.")
    return np.concatenate(chunks) if chunks else np.zeros((0, 1), dtype="int16")


def save(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(audio.tobytes())


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    only = sys.argv[1:]
    clips = [c for c in CLIPS if not only or c["name"] in only]
    print(f"Mic: {sd.query_devices(kind='input')['name']}\n"
          "Speak at your normal volume, as you would to the tutor. "
          "Leave about a second of silence before and after.\n")
    for i, clip in enumerate(clips, 1):
        path = OUT_DIR / f"{clip['name']}.wav"
        if path.exists() and not only:
            print(f"[{i}/{len(clips)}] {clip['name']}: already recorded, skipping\n")
            continue
        print(f"[{i}/{len(clips)}] {clip['bucket']}")
        print(f"  Say:  {clip['say']}")
        while True:
            input("  Press Enter to start recording.")
            audio = record()
            seconds = len(audio) / SAMPLE_RATE
            print(f"  Got {seconds:.1f} s.")
            choice = input("  [Enter] keep   [p] play back   [r] redo: ").strip().lower()
            while choice == "p":
                # macOS's own player: playing through sounddevice and then reopening the mic
                # could leave the next recording stuck.
                preview = OUT_DIR / ".preview.wav"
                save(preview, audio)
                subprocess.run(["afplay", str(preview)])
                preview.unlink(missing_ok=True)
                choice = input("  [Enter] keep   [p] play back   [r] redo: ").strip().lower()
            if choice != "r":
                save(path, audio)
                print(f"  Saved {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}\n")
                break
    print("Done. Tell Claude the clips are recorded.")


if __name__ == "__main__":
    main()
