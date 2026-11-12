
# Clip a long video

All commands run from the project root with the venv Python: `.venv\Scripts\python.exe`.
Source videos live in `inbox\`. Finished clips land in `output\<video>\`.

## 1. Transcribe (once per video)
```
.venv\Scripts\python.exe scripts\transcribe.py "inbox\<file>"
```
Writes `work\<video>\transcript.txt` (timestamped lines, seconds). Long videos take a while; tell the user it's running.

## 2. Pick clips
Read `transcript.txt` in full. Choose clips that match the user's request. Defaults if they didn't say:
5 clips, 25–60 s each.

A good clip:
- Opens on a strong line (claim, question, number, story beat). No "so, um, yeah" warm-up.
- Stands alone. A stranger understands it without the rest of the video.
- Ends on a payoff or a complete thought, not mid-argument.
- Doesn't overlap another clip.

Write `work\<video>\clips.json`:
```json
{
  "request": "<the user's request, verbatim>",
  "clips": [
    {"id": "01", "title": "Short descriptive title",
     "start": 132.4, "end": 178.9,
     "hook": "3-7 word on-screen hook",
     "layout": "track",
     "why": "one line on why this works"}
  ]
}
```
- `start`/`end` are seconds from transcript.txt. The renderer snaps them to word boundaries.
- `hook` is optional. Omit it if the user doesn't want on-screen titles.
- `layout`: use `track` for talking heads (follows the speaker's face) and `fit` for screen shares, slides or wide multi-person shots (full frame over a blurred fill).
- Use `"brand": "brand/<client>.json"` at the top level for a non-default client brand.

## 3. Render
```
.venv\Scripts\python.exe scripts\render.py work\<video>\clips.json [--only 01,03]
```

## 4. QC (always)
```
.venv\Scripts\python.exe scripts\qc.py work\<video>\clips.json
```
Then **look at every `sheet.jpg`** listed (Read tool) and check:
- Is the speaker's face in frame and not cut off?
- Are captions readable and clear of the face and the logo?
- Is the hook legible?

Fix and re-render only the affected clips with `--only`:
- FAIL → fix before delivering.
- Face off-frame or "face found in only X%" → set `"layout": "fit"`.
- Mid-word cut or weak open/close → adjust `start`/`end`.
- Captions overlap the face → raise `caption.margin_v` in the brand file (lower on screen = smaller number).

## 5. Report
Give a short table: id, title, length, QC status, file path. Mention anything you changed after QC.

## Brand setup (new client)
Copy `brand\brand.json` to `brand\<client>.json`. Set the colors (hex) and font name, and put the logo PNG (transparent background) in `brand\`.
For a custom font, drop the .ttf/.otf in `brand\fonts\` and use the font's family name, e.g. "Montserrat ExtraBold".
