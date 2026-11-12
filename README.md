# Sira Clips: the Windows vibe-editing toolkit

Turn one long video (a podcast, interview, webinar, Q&A or livestream) into vertical, captioned, on-brand short clips. You describe the clips you want in plain English, and Claude does the rest.

> "Make 5 clips from inbox\chef-interview.mp4 about our catering, 30–45 seconds each."

What you get for each clip:
- A 1080×1920 vertical video that keeps the speaker's face in frame
- Captions with the current word highlighted, in your brand's font and colors
- A short hook title for the first 3 seconds
- Your logo
- Audio leveled for social media (about −14 LUFS)
- An automatic quality check before you see it

## How it works

1. **Transcribe:** `faster-whisper` (GPU when available) produces word-level timestamps.
2. **Pick the clips:** Claude Code reads the transcript and chooses clips that match your request. It writes them to a `clips.json` plan.
3. **Render:** ffmpeg cuts each clip, snapping to word boundaries. OpenCV face detection (YuNet) drives a 9:16 crop that follows the speaker. Captions are rendered as ASS subtitles with word-by-word highlighting, then the hook title and logo overlay are added. Two-pass loudness normalization runs, and it encodes with NVENC (or libx264 as a fallback).
4. **QC:** automated checks cover resolution, length, loudness, black frames, dead air and mid-word cuts. A contact sheet per clip lets Claude review the framing visually and fix what's off.

Python + ffmpeg + OpenCV + faster-whisper, orchestrated by Claude Code. Everything runs locally.

Built by [Sira](https://www.sira.services). **Don't want to set it up yourself?** We'll install it on your PC, set up your brand kit and train your team: [book a call](https://www.sira.services/clips#install).

---

## What you need

| | |
|---|---|
| Computer | Windows 10 or 11 PC, 16 GB RAM or more |
| GPU | NVIDIA GPU recommended (any RTX). It also runs on CPU, just slower. |
| Claude | A paid Claude plan (Pro or Max) with [Claude Code](https://docs.claude.com/en/docs/claude-code) installed |
| Disk | About 5 GB free for models, plus room for your videos |

## Install (about 10 minutes)

1. Unzip this folder somewhere outside OneDrive, for example `C:\sira-clips`. Synced folders slow down large video files.
2. Open **PowerShell** in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
   ```
   This installs ffmpeg and Python if they're missing, creates a private Python environment and downloads the face-detection model. If it installs ffmpeg, close PowerShell, open it again and run the same command a second time.
3. Install Claude Code if you don't have it yet. Instructions are in Anthropic's docs (linked above).

## Make your first clips

1. Copy a long video into the `inbox\` folder.
2. Open PowerShell in the toolkit folder and type `claude`.
3. Ask for what you want, in plain English. Some examples:
   - *"Make 5 clips from inbox\episode-12.mp4. Pick the most surprising moments, 30–60 seconds."*
   - *"Find every question from the audience in inbox\qa.mp4 and make one clip per answer."*
   - *"3 clips about pricing, no hook titles, use the fit layout because it's a screen share."*

Claude transcribes the video, picks the moments, renders the clips, runs the quality check, looks at frames from each clip and fixes anything that's off. Finished clips go to `output\<video name>\`.

The first transcription downloads the speech model (about 1.5 GB). After that, an hour-long video transcribes in a few minutes on a GPU.

## Make it look like your brand

Open `brand\brand.json` and change:

| Setting | What it does |
|---|---|
| `caption.font` | Font name, e.g. `"Montserrat ExtraBold"`. Put custom .ttf/.otf files in `brand\fonts\`. |
| `caption.color` / `caption.highlight` | Caption color and the color of the word being spoken |
| `caption.margin_v` | Caption height from the bottom (larger = higher) |
| `hook.*` | Hook title style, or set `"enabled": false` |
| `logo.file` | Your logo. A transparent PNG at `brand\logo.png` works best. |
| `layout` | `track` follows the speaker's face; `fit` shows the full frame over a blurred background |

Several brands? Copy `brand.json` to `brand\client-name.json` and tell Claude which one to use.

## Folders

```
inbox\    your source videos
output\   finished clips
work\     transcripts, clip plans, QC reports (safe to delete)
brand\    brand settings, logo, fonts
scripts\  the pipeline (transcribe, render, qc)
```

## Running it without Claude

```powershell
.venv\Scripts\python.exe scripts\transcribe.py inbox\video.mp4
# write work\video\clips.json yourself (format in WORKFLOW.md)
.venv\Scripts\python.exe scripts\render.py work\video\clips.json
.venv\Scripts\python.exe scripts\qc.py work\video\clips.json
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found` | Close and reopen PowerShell after setup, or run `winget install Gyan.FFmpeg` |
| Transcription is slow | No NVIDIA GPU was found, so it's running on CPU. It still works; it just takes longer. |
| Speaker cut off at the edge | Ask Claude to use the `fit` layout for that clip |
| Captions cover the face | Raise or lower `caption.margin_v` in your brand file |

## Want it done for you?

Sira installs and runs this for businesses: setup on your PC, your brand kit, team training, or fully done-for-you clips every month.
**[Book a free call →](https://www.sira.services/clips#install)**

---
Licensed for use in your own business. See `LICENSE`. © Aira Development LLC (Sira).
