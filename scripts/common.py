"""Shared helpers for the Sira Clips pipeline."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"


def load_json(p):
    with open(p, "r", encoding="utf-8-sig") as f:  # tolerate BOM from Windows editors
        return json.load(f)


def save_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_brand(path=None):
    path = Path(path) if path else ROOT / "brand" / "brand.json"
    if not path.is_absolute():
        path = ROOT / path
    return load_json(path), path


def slugify(s, n=40):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:n] or "clip"


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}\n{p.stderr[-3000:]}")
    return p


def ffprobe(path):
    p = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    return json.loads(p.stdout)


def video_info(path):
    d = ffprobe(path)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    fps = 30.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, dd = v["avg_frame_rate"].split("/")
        fps = float(n) / float(dd) if float(dd) else 30.0
    w, h = (int(v["width"]), int(v["height"])) if v else (0, 0)
    # honor rotation metadata (phone footage)
    rot = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int(v.get("tags", {}).get("rotate", rot))
    if abs(rot) in (90, 270):
        w, h = h, w
    return {
        "width": w, "height": h, "fps": fps,
        "duration": float(d["format"].get("duration", 0)),
        "has_audio": a is not None,
    }


def hex_to_ass(hex_color, alpha=0):
    """#RRGGBB -> &HAABBGGRR (alpha 0=opaque, 255=transparent)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def stem_dir(video_path):
    stem = slugify(Path(video_path).stem, 60)
    d = WORK / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def fmt_ts(sec):
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    return f"{h:d}:{m:02d}:{s:05.2f}" if h else f"{m:02d}:{s:05.2f}"


def require_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH. Install with: winget install Gyan.FFmpeg")


def add_cuda_dll_dirs():
    """Make pip-installed NVIDIA cuBLAS/cuDNN DLLs visible on Windows."""
    if os.name != "nt":
        return
    try:
        import importlib.util
        for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime"):
            spec = importlib.util.find_spec(pkg)
            if not spec or not spec.submodule_search_locations:
                continue
            for loc in spec.submodule_search_locations:
                b = Path(loc) / "bin"
                if b.exists():
                    os.add_dll_directory(str(b))
                    os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass
