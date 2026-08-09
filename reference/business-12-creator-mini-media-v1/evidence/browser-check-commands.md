# Browser validation commands

```bash
python3 -m http.server 4173 --directory reference/business-12-creator-mini-media-v1
python3 validate_creator_media.py
ffmpeg -y -framerate 7 -i relay-frames/frame-%02d.png -c:v libx264 -pix_fmt yuv420p -movflags +faststart format-relay.mp4
```

Browser: system Chromium in headless mode. Exact repository files were rendered in memory because sandbox policy blocked both localhost and file navigation.
Desktop viewport: 1440×1000.
Mobile viewport: 390×844.
Reduced motion: Playwright context `reduced_motion="reduce"`.
