"""Transcribe a long video with word-level timestamps.

Usage:
  python scripts/transcribe.py inbox/episode.mp4 [--model medium] [--language en]

Writes work/<video>/transcript.json (segments + words) and transcript.txt
(timestamped lines Claude reads to pick clips).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (ROOT, add_cuda_dll_dirs, fmt_ts, require_ffmpeg, run,
                    save_json, stem_dir, video_info)


def load_model(name, device_pref):
    add_cuda_dll_dirs()
    from faster_whisper import WhisperModel
    attempts = []
    if device_pref in ("auto", "cuda"):
        attempts += [("cuda", "float16"), ("cuda", "int8_float16")]
    attempts += [("cpu", "int8")]
    last = None
    for device, ctype in attempts:
        try:
            m = WhisperModel(name, device=device, compute_type=ctype)
            return m, device, ctype
        except Exception as e:  # missing CUDA libs, not enough VRAM, etc.
            last = e
    raise RuntimeError(f"Could not load Whisper model: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default=None, help="tiny/base/small/medium/large-v3 (default: medium on GPU, small on CPU)")
    ap.add_argument("--language", default=None, help="e.g. en, es (default: auto-detect)")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    require_ffmpeg()
    video = Path(a.video)
    if not video.is_absolute():
        video = (Path.cwd() / video) if (Path.cwd() / video).exists() else ROOT / video
    if not video.exists():
        sys.exit(f"Video not found: {video}")

    d = stem_dir(video)
    out_json = d / "transcript.json"
    if out_json.exists() and not a.force:
        print(f"Transcript already exists: {out_json} (use --force to redo)")
        return

    info = video_info(video)
    if not info["has_audio"]:
        sys.exit("Video has no audio track; nothing to transcribe.")

    # Decode with ffmpeg ourselves (avoids PyAV version issues), 16 kHz mono float32
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)

    model_name = a.model
    model, device, ctype = None, None, None
    if model_name is None:
        model_name = "medium"
        try:
            model, device, ctype = load_model(model_name, a.device)
            if device == "cpu":
                model_name = "small"
                model, device, ctype = load_model(model_name, "cpu")
        except Exception:
            model_name = "small"
    if model is None:
        model, device, ctype = load_model(model_name, a.device)
    print(f"Whisper {model_name} on {device} ({ctype}); video {fmt_ts(info['duration'])}")

    t0 = time.time()
    segs, tinfo = model.transcribe(audio, language=a.language, word_timestamps=True,
                                   vad_filter=True, beam_size=5)
    segments = []
    for s in segs:
        words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                  "p": round(w.probability, 3)} for w in (s.words or []) if w.word.strip()]
        segments.append({"id": len(segments), "start": round(s.start, 3), "end": round(s.end, 3),
                         "text": s.text.strip(), "words": words})
        print(f"\r  transcribed to {fmt_ts(s.end)}", end="", flush=True)
    print()

    data = {"video": str(video), "language": tinfo.language, "duration": info["duration"],
            "width": info["width"], "height": info["height"], "fps": info["fps"],
            "model": model_name, "segments": segments}
    save_json(out_json, data)
    with open(d / "transcript.txt", "w", encoding="utf-8") as f:
        f.write(f"# {video.name} | {fmt_ts(info['duration'])} | lang={tinfo.language}\n")
        f.write("# Format: [start_sec - end_sec] text   (seconds are what clips.json uses)\n")
        for s in segments:
            f.write(f"[{s['start']:.2f} - {s['end']:.2f}] {s['text']}\n")
    print(f"Done in {time.time()-t0:.0f}s -> {d / 'transcript.txt'}")


if __name__ == "__main__":
    main()
