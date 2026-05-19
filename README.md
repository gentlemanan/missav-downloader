# missav-downloader

Lightweight Python script to download videos from `missav.*` as `.ts` files.

## Usage

```bash
uvx --from git+https://github.com/gentlemanan/missav-downloader missav <URL>
```

### Options

```bash
usage: missav [-h] [-o OUTPUT] [-q] [-w WORKERS] url

MissAV video downloader

positional arguments:
  url                   MissAV video URL (e.g., https://missav.ai/sone-543)

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output directory (default: downloads)
  -q, --quiet           Suppress output messages
  -w, --workers WORKERS
                        Parallel download workers (default: 16)         Suppress progress output
```

### Examples

```bash
uvx --from git+https://github.com/gentlemanan/missav-downloader missav https://missav.ai/sone-543

# Custom output directory
uvx --from git+https://github.com/gentlemanan/missav-downloader missav https://missav.ai/sone-543 -o ~/Videos
```

## Output

Videos are saved as `<title>.ts` (MPEG-TS). All major players (VLC, mpv, IINA) play `.ts` natively.
