"""Quality-check rendered clips and build a contact sheet per clip for visual review.

Usage:
  python scripts/qc.py work/<video>/clips.json

Checks: resolution, duration bounds, audio present, loudness, black frames,
dead air at start, captions present, face-tracking coverage, word-boundary cuts.
Writes work/<video>/qc_report.json and work/<video>/clip_XX/sheet.jpg.
Exit code 1 if any clip FAILs.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_brand, load_json, require_ffmpeg, run, save_json, video_info


def loudness(path):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-filter_complex",
             "ebur128=peak=true", "-f", "null", "-"], check=False)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else None


def black_ratio(path, dur):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf",
             "blackdetect=d=0.3:pix_th=0.10", "-an", "-f", "null", "-"], check=False)
    total = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", p.stderr))
    return total / dur if dur else 0


def lead_silence(path):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
             "silencedetect=n=-40dB:d=0.5", "-vn", "-f", "null", "-"], check=False)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    if starts and starts[0] <= 0.05 and ends:
        return ends[0]
    return 0.0


def contact_sheet(path, dur, out):
    # 6 frames across the clip, 3x2 grid, small enough to eyeball quickly
    n = 6
    times = [dur * (i + 0.5) / n for i in range(n)]
    sel = "+".join(f"between(t,{t:.2f},{t + 0.04:.2f})" for t in times)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf",
         f"select='{sel}',scale=360:640,tile=3x2:padding=6:color=white",
         "-frames:v", "1", "-vsync", "vfr", str(out)], check=False)
    return out.exists()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips_json")
    ap.add_argument("--brand", default=None)
    a = ap.parse_args()
    require_ffmpeg()
    cj = Path(a.clips_json)
    if not cj.is_absolute():
        cj = (Path.cwd() / cj) if (Path.cwd() / cj).exists() else ROOT / cj
    workdir = cj.parent
    plan = load_json(cj)
    brand, _ = load_brand(a.brand or plan.get("brand"))
    q = brand.get("qc", {})
    o = brand["output"]
    manifest = load_json(workdir / "render_manifest.json")
    transcript = load_json(workdir / "transcript.json")
    words = [w for s in transcript["segments"] for w in s["words"]]

    report, any_fail = {}, False
    for cid, r in sorted(manifest["clips"].items()):
        out = Path(r["output"])
        issues, warns = [], []
        if not out.exists():
            report[cid] = {"status": "FAIL", "issues": ["output file missing"]}
            any_fail = True
            continue
        info = video_info(out)
        if (info["width"], info["height"]) != (o["width"], o["height"]):
            issues.append(f"resolution {info['width']}x{info['height']} != {o['width']}x{o['height']}")
        d = info["duration"]
        if abs(d - r["duration"]) > 0.6:
            issues.append(f"duration {d:.1f}s differs from planned {r['duration']:.1f}s")
        if d < q.get("min_sec", 15):
            warns.append(f"short clip ({d:.1f}s < {q.get('min_sec', 15)}s)")
        if d > q.get("max_sec", 90):
            warns.append(f"long clip ({d:.1f}s > {q.get('max_sec', 90)}s)")
        if not info["has_audio"]:
            issues.append("no audio track")
        lufs = loudness(out) if info["has_audio"] else None
        tgt = q.get("target_lufs", -14)
        if lufs is not None and abs(lufs - tgt) > 2.5:
            warns.append(f"loudness {lufs:.1f} LUFS (target {tgt})")
        br = black_ratio(out, d)
        if br > 0.1:
            issues.append(f"{br:.0%} of clip is black")
        ls = lead_silence(out) if info["has_audio"] else 0
        if ls > 1.0:
            warns.append(f"{ls:.1f}s of dead air at start")
        if r.get("caption_chunks", 0) == 0:
            issues.append("no captions generated (no speech in range?)")
        if r.get("layout") == "track" and r.get("face_coverage", 1) < 0.4:
            warns.append(f"face found in only {r.get('face_coverage', 0):.0%} of frames; "
                         "consider layout 'fit'")
        if r.get("camera_moves", 0) > max(6, d / 6):
            warns.append(f"{r['camera_moves']} camera moves; framing may feel jumpy")
        for edge in (r["start"], r["end"]):
            if any(w["s"] + 0.03 < edge < w["e"] - 0.03 for w in words):
                warns.append(f"cut at {edge:.2f}s lands mid-word")
        sheet = workdir / f"clip_{cid}" / "sheet.jpg"
        contact_sheet(out, d, sheet)
        status = "FAIL" if issues else ("WARN" if warns else "PASS")
        any_fail |= status == "FAIL"
        report[cid] = {"status": status, "title": r.get("title"), "output": str(out),
                       "duration": round(d, 2), "lufs": lufs, "issues": issues,
                       "warnings": warns, "sheet": str(sheet)}
        print(f"[{status}] {cid} {r.get('title', '')} ({d:.1f}s, {lufs} LUFS)")
        for x in issues:
            print(f"    FAIL: {x}")
        for x in warns:
            print(f"    warn: {x}")
        print(f"    sheet: {sheet}")
    save_json(workdir / "qc_report.json", report)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
