# missav-downloader

Lightweight Python script to download videos from missav.ai as `.mp4` files. Handles Cloudflare protection via headless Chromium (Playwright).

## Usage

1. On first run, install the required headless Chromium browser (~150MB)
```bash
uvx --with playwright missav-downloader playwright install chromium
```

2. Download a video
```bash
uvx --from git+https://github.com/gentlemanan/missav-downloader missav <URL>
```

### Options

```
positional arguments:
  url                   MissAV video URL

options:
  -o, --output DIR      Output directory (default: downloads)
  -w, --workers N       Parallel download workers (default: 2× CPU, max 16)
  -q, --quiet           Suppress progress output
```

### Examples

```bash
uvx --from git+https://github.com/gentlemanan/missav-downloader missav https://missav.ai/cn/abf-353-uncensored-leak

uvx --from git+https://github.com/gentlemanan/missav-downloader missav https://missav.ai/dm31/cn/stars-128 -o ~/Videos
```

## Requirements

- **ffmpeg** must be available in `PATH` for the TS→MP4 remux step.
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`

## Output

Videos are saved as `<title>.mp4`. Playable in any video player.
