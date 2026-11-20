# TubeForge

A local-first Flask web control surface for `yt-dlp`, `ffmpeg`, and `ffprobe`.

Visual static only demo available at https://tubeforge.khosrofar.me

## Features
- **Fetch (`yt-dlp`)**: Option registry, format explorer, playlist selection, chapter templates, and split-job queuing.
- **Media Lab (`ffmpeg`)**: Transcode, trim, concat, subtitle burn/soft-mux, loudness normalisation, hardware acceleration sync, and target file-size calculator.
- **Filter Studio**: Visual `-vf` / `-af` chain builder with live frame preview.
- **Library & Inspector**: File browser, `ffprobe` stream/chapter inspector, interactive In/Out preview deck, and native OS file/folder picker.
- **Transport Dock**: Concurrent worker pool with live SSE progress and log streaming.

## Running
```bash
python3 run.py
```

Or build a standalone single-file script:
```bash
python3 build_singlefile.py
python3 dist/tubeforge.py
```

## Tests
```bash
python3 -m pytest -v
```
