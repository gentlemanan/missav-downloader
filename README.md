# missav-downloader

Lightweight Python script to download videos from missav.ai as `.ts` files.

## Usage

```bash
uvx --from git+https://github.com/gentlemanan/missav-downloader missav <URL>
```

### Options

```
positional arguments:
  url                   MissAV video URL (e.g. https://missav.ai/sone-543)

options:
  -o, --output DIR      Output directory (default: downloads)
  -w, --workers N       Parallel download workers (default: 2× CPU, max 16)
  -q, --quiet           Suppress progress output
```

### Examples

```bash
uvx --from git+https://github.com/gentlemanan/missav-downloader missav https://missav.ai/sone-543

# Custom output directory
uvx --from git+https://github.com/gentlemanan/missav-downloader missav https://missav.ai/sone-543 -o ~/Videos
```

## Output

Videos are saved as `<title>.ts` (MPEG-TS). All major players (VLC, mpv, IINA) play `.ts` natively.
