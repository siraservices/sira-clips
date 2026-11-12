# Sira Clips

Turns long videos into vertical, captioned, on-brand short clips on Windows. Built by Sira (Aira Development LLC).

- To make clips, follow `WORKFLOW.md`. Use it whenever the user asks for clips, shorts, reels, TikToks or highlights from a video.
- Python: always `.venv\Scripts\python.exe`. Never use the system Python.
- Folders: `inbox\` holds source videos, `work\` holds transcripts, plans and QC, `output\` holds finished clips, `brand\` holds brand files, logos and fonts.
- Requirements: ffmpeg on PATH. An NVIDIA GPU is optional (used for transcription and encoding when present; the pipeline falls back to CPU).
- Never delete anything in `inbox\` or `output\` unless the user asks.
- Re-run `scripts\setup.ps1` if the venv is missing.
