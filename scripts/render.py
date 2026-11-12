"""Render vertical, on-brand clips from a clips.json plan.

Usage:
  python scripts/render.py work/<video>/clips.json [--only 01,03] [--brand brand/brand.json]

clips.json (written by Claude after reading transcript.txt):
{
  "clips": [
    {"id": "01", "title": "Why most restaurants lose catering orders",
     "start": 132.4, "end": 178.9,
     "hook": "You're losing catering orders here",   # optional on-screen hook
     "layout": "track"                               # optional: track | fit
    }
  ]
}
The source video is read from work/<video>/transcript.json.
"""
import argparse
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (OUTPUT, ROOT, hex_to_ass, load_brand, load_json, require_ffmpeg,
                    run, save_json, slugify, video_info)

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
YUNET = ROOT / "models" / "face_detection_yunet_2023mar.onnx"


# ---------------------------------------------------------------- boundaries
def all_words(transcript):
    return [dict(w, seg=s["id"]) for s in transcript["segments"] for w in s["words"]]


def snap_bounds(words, start, end, duration):
    """Move cut points to word boundaries so clips never start/end mid-word."""
    first = next((w for w in words if w["s"] >= start - 0.4), None)
    s = max(0.0, first["s"] - 0.12) if first else start
    inside = [w for w in words if w["e"] <= end + 0.4 and w["s"] >= s]
    if inside:
        last = inside[-1]
        idx = words.index(last)
        nxt = words[idx + 1]["s"] if idx + 1 < len(words) else duration
        e = min(last["e"] + 0.35, max(last["e"] + 0.05, nxt - 0.02), duration)
    else:
        e = end
    return round(s, 3), round(e, 3)


# ---------------------------------------------------------------- face tracking
def make_detector(cv2):
    if YUNET.exists():
        det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7, 0.3, 5000)

        def detect(img):
            h, w = img.shape[:2]
            det.setInputSize((w, h))
            _, faces = det.detect(img)
            if faces is None:
                return []
            return [(f[0], f[1], f[2], f[3]) for f in faces]
        return detect, "yunet"
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def detect(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return [tuple(r) for r in casc.detectMultiScale(g, 1.1, 5, minSize=(40, 40))]
    return detect, "haar"


def track_crop(video, start, end, W, H, crop_w, step=0.2):
    """Return [(t_rel, x)] piecewise-constant crop positions following the main face."""
    import cv2
    detect, kind = make_detector(cv2)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    skip = max(1, int(round(fps * step)))
    scale = 640 / max(W, 1)
    samples = []
    t = start
    while t < end:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))
        faces = detect(small)
        cx = None
        if faces:
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx = (x + w / 2) / scale
        samples.append((t - start, cx))
        for _ in range(skip - 1):
            cap.grab()
        t += skip / fps
    cap.release()

    center = W / 2
    found = [c for _, c in samples if c is not None]
    if not found:
        return [(0.0, int((W - crop_w) / 2))], kind, 0.0
    # fill gaps with last known position
    filled, last = [], found[0]
    for ts, c in samples:
        last = c if c is not None else last
        filled.append((ts, last))
    # rolling median to kill jitter
    k = 5
    smooth = []
    for i, (ts, _) in enumerate(filled):
        win = [c for _, c in filled[max(0, i - k // 2): i + k // 2 + 1]]
        smooth.append((ts, statistics.median(win)))
    # hysteresis: only "cut" the virtual camera when the subject moves a lot for a while
    thresh, hold = 0.07 * W, 3
    cur = smooth[0][1]
    segs = [(0.0, cur)]
    run_n = 0
    for ts, c in smooth:
        if abs(c - cur) > thresh:
            run_n += 1
            if run_n >= hold:
                cur = c
                segs.append((max(0.0, ts - step * (hold - 1)), cur))
                run_n = 0
        else:
            run_n = 0
    out = []
    for ts, c in segs:
        x = int(min(max(c - crop_w / 2, 0), W - crop_w))
        x -= x % 2
        if not out or abs(out[-1][1] - x) > 2:
            out.append((round(ts, 2), x))
    coverage = len([c for _, c in samples if c is not None]) / max(len(samples), 1)
    return out, kind, coverage


def crop_x_expr(segs):
    expr = str(segs[-1][1])
    for (t_next, _), (_, x) in zip(reversed(segs[1:]), reversed(segs[:-1])):
        expr = f"if(lt(t,{t_next}),{x},{expr})"
    return expr


# ---------------------------------------------------------------- captions
def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def clean(w, upper):
    w = w.replace("{", "(").replace("}", ")").replace("\\", "")
    return w.upper() if upper else w


def build_ass(words, start, end, hook, brand, ow, oh):
    c = brand["caption"]
    hk = brand.get("hook", {})
    hl = hex_to_ass(c["highlight"])
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {ow}", f"PlayResY: {oh}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{c['font']},{c['size']},{hex_to_ass(c['color'])},{hex_to_ass(c['color'])},"
        f"{hex_to_ass(c['outline_color'])},&H80000000,-1,0,0,0,100,100,0,0,1,{c['outline']},"
        f"{c.get('shadow', 0)},2,80,80,{c['margin_v']},1",
        f"Style: Hook,{hk.get('font', c['font'])},{hk.get('size', 60)},{hex_to_ass(hk.get('color', '#FFFFFF'))},"
        f"{hex_to_ass(hk.get('color', '#FFFFFF'))},{hex_to_ass(hk.get('box_color', '#000000'))},"
        f"{hex_to_ass(hk.get('box_color', '#000000'))},-1,0,0,0,100,100,0,0,3,18,0,8,90,90,"
        f"{hk.get('margin_v', 220)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    ws = [dict(w, s=w["s"] - start, e=w["e"] - start) for w in words
          if w["e"] > start and w["s"] < end]
    upper = c.get("uppercase", True)
    chunks, cur = [], []
    for w in ws:
        txt = " ".join(x["w"] for x in cur + [w])
        gap = cur and (w["s"] - cur[-1]["e"] > 0.6)
        if cur and (len(cur) >= c["max_words"] or len(txt) > c["max_chars"] or gap
                    or cur[-1]["w"][-1:] in ".?!," or w.get("seg") != cur[-1].get("seg")):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    clip_len = end - start
    for ci, ch in enumerate(chunks):
        nxt_chunk = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else clip_len
        for i, w in enumerate(ch):
            t0 = w["s"]
            t1 = ch[i + 1]["s"] if i + 1 < len(ch) else min(nxt_chunk, w["e"] + 0.4)
            if t1 - t0 < 0.05:
                t1 = t0 + 0.05
            parts = []
            for j, x in enumerate(ch):
                word = clean(x["w"], upper)
                parts.append(f"{{\\c{hl}\\fscx108\\fscy108}}{word}{{\\r}}" if j == i else word)
            lines.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},Cap,,0,0,0,,{' '.join(parts)}")
    if hook and hk.get("enabled", True):
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(min(hk.get('duration', 3.0), clip_len))},"
                     f"Hook,,0,0,0,,{{\\fad(150,250)}}{clean(hook, False)}")
    return "\n".join(lines) + "\n", len(chunks)


# ---------------------------------------------------------------- ffmpeg
def logo_overlay(brand, ow, oh):
    lg = brand.get("logo") or {}
    f = lg.get("file")
    if not f:
        return None, None
    p = Path(f) if Path(f).is_absolute() else ROOT / f
    if not p.exists():
        return None, None
    m = lg.get("margin", 40)
    pos = {
        "top-right": f"W-w-{m}:{m}", "top-left": f"{m}:{m}",
        "bottom-right": f"W-w-{m}:H-h-{m}", "bottom-left": f"{m}:H-h-{m}",
    }.get(lg.get("position", "top-right"), f"W-w-{m}:{m}")
    filt = (f"[1:v]scale={lg.get('width', 180)}:-1,format=rgba,"
            f"colorchannelmixer=aa={lg.get('opacity', 0.9)}[lg]")
    return p, (filt, pos)


def loudnorm_filter(src, start, dur, target):
    """Two-pass EBU R128: measure this exact segment, then apply a linear gain."""
    import json as _json
    # gentle speech compression first, so peaks don't block the loudness gain
    pre = "highpass=f=70,acompressor=threshold=-24dB:ratio=3:attack=5:release=150:makeup=2"
    base = f"loudnorm=I={target}:TP=-1.0:LRA=9"
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(dur), "-i", str(src),
             "-vn", "-af", f"{pre},{base}:print_format=json", "-f", "null", "-"], check=False)
    try:
        m = _json.loads(p.stderr[p.stderr.rindex("{"): p.stderr.rindex("}") + 1])
        return (f"{pre},{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
                f"offset={m['target_offset']}:linear=true")
    except Exception:
        return f"{pre},{base}"


def encode(cmd_base, out, workdir):
    encoders = [
        ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"],
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"],
    ]
    last = None
    for enc in encoders:
        cmd = cmd_base + enc + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                                "-ar", "48000", "-movflags", "+faststart", str(out)]
        p = run(cmd, cwd=workdir, check=False)
        if p.returncode == 0:
            return enc[1]
        last = p.stderr[-2500:]
    raise RuntimeError(f"ffmpeg failed:\n{last}")


def render_clip(clip, src, info, words, brand, outdir, workdir):
    o = brand["output"]
    ow, oh, fps = o["width"], o["height"], o.get("fps", 30)
    start, end = snap_bounds(words, float(clip["start"]), float(clip["end"]), info["duration"])
    dur = round(end - start, 3)
    cid = str(clip["id"]).zfill(2)
    cdir = workdir / f"clip_{cid}"
    cdir.mkdir(parents=True, exist_ok=True)

    ass, nchunks = build_ass(words, start, end, clip.get("hook"), brand, ow, oh)
    (cdir / "captions.ass").write_text(ass, encoding="utf-8")

    W, H = info["width"], info["height"]
    layout = clip.get("layout") or brand.get("layout", "track")
    target_ar = ow / oh
    fonts_rel = Path("../../../brand/fonts").as_posix()
    track_meta = {}
    if layout == "fit" or W / H <= target_ar + 0.01:
        # blurred-fill background + full frame centered (screen recordings, already-vertical)
        vf = (f"[0:v]fps={fps},split[a][b];"
              f"[a]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},boxblur=30:2,eq=brightness=-0.08[bg];"
              f"[b]scale={ow}:{oh}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]")
        layout = "fit"
    else:
        crop_w = int(H * target_ar)
        crop_w -= crop_w % 2
        segs, kind, coverage = track_crop(src, start, end, W, H, crop_w)
        track_meta = {"detector": kind, "face_coverage": round(coverage, 2), "camera_moves": len(segs) - 1}
        vf = (f"[0:v]fps={fps},crop={crop_w}:{H}:x='{crop_x_expr(segs)}':y=0,"
              f"scale={ow}:{oh}:flags=lanczos,setsar=1[v0]")
    vf += f";[v0]subtitles=captions.ass:fontsdir='{fonts_rel}'[v1]"

    logo, lgo = logo_overlay(brand, ow, oh)
    inputs = ["-ss", str(start), "-t", str(dur), "-i", str(src)]
    if logo:
        inputs += ["-i", str(logo)]
        vf += f";{lgo[0]};[v1][lg]overlay={lgo[1]}[vout]"
    else:
        vf += ";[v1]null[vout]"
    af = loudnorm_filter(src, start, dur, brand.get("qc", {}).get("target_lufs", -14))
    out = outdir / f"{cid}_{slugify(clip.get('title', 'clip'))}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", vf,
           "-map", "[vout]", "-map", "0:a?", "-af", af, "-r", str(fps)]
    encoder = encode(cmd, out, cdir)
    return {"id": cid, "title": clip.get("title"), "hook": clip.get("hook"),
            "planned": [clip["start"], clip["end"]], "start": start, "end": end,
            "duration": dur, "layout": layout, "caption_chunks": nchunks,
            "encoder": encoder, "output": str(out), **track_meta}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips_json")
    ap.add_argument("--only", default=None, help="comma-separated clip ids")
    ap.add_argument("--brand", default=None)
    a = ap.parse_args()
    require_ffmpeg()

    cj = Path(a.clips_json)
    if not cj.is_absolute():
        cj = (Path.cwd() / cj) if (Path.cwd() / cj).exists() else ROOT / cj
    workdir = cj.parent
    plan = load_json(cj)
    transcript = load_json(workdir / "transcript.json")
    brand, _ = load_brand(a.brand or plan.get("brand"))
    src = Path(plan.get("source") or transcript["video"])
    info = video_info(src)
    words = all_words(transcript)
    outdir = OUTPUT / workdir.name
    outdir.mkdir(parents=True, exist_ok=True)

    only = {x.strip().zfill(2) for x in a.only.split(",")} if a.only else None
    manifest_p = workdir / "render_manifest.json"
    manifest = load_json(manifest_p) if manifest_p.exists() else {"clips": {}}
    for clip in plan["clips"]:
        cid = str(clip["id"]).zfill(2)
        if only and cid not in only:
            continue
        print(f"Rendering {cid}: {clip.get('title', '')} ...", flush=True)
        r = render_clip(clip, src, info, words, brand, outdir, workdir)
        manifest["clips"][cid] = r
        print(f"  -> {r['output']} ({r['duration']:.1f}s, {r['layout']}, {r['encoder']})")
    manifest["source"] = str(src)
    save_json(manifest_p, manifest)
    print(f"Manifest: {manifest_p}\nNext: python scripts/qc.py {cj.relative_to(ROOT) if cj.is_relative_to(ROOT) else cj}")


if __name__ == "__main__":
    main()
