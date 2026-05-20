#!/usr/bin/env python
# /// script
# dependencies = [
#   "requests",
#   "playwright",
#   "m3u8",
#   "pycryptodome",
#   "tqdm",
# ]
# ///

import argparse
import os
import re
import sys
import time
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import m3u8
import requests
from Crypto.Cipher import AES
from playwright.sync_api import sync_playwright
from tqdm import tqdm


# ── Constants ──────────────────────────────────────────────────────────────────

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
M3U8_HEADERS = {
    **REQUEST_HEADERS,
    "Referer": "https://missav.ai/",
    "Origin": "https://missav.ai",
}

_cpu = os.cpu_count() or 4
DEFAULT_WORKERS = min(_cpu * 2, 16)
MAX_RETRIES = 3


# ── Logger ─────────────────────────────────────────────────────────────────────


class Logger:
    """Single-responsibility: write log messages to stdout."""

    def __init__(self, silent: bool = False):
        self._silent = silent

    def log(self, msg: str) -> None:
        if not self._silent:
            tqdm.write(msg)


# ── HttpClient ─────────────────────────────────────────────────────────────────


class HttpClient:
    """Single-responsibility: own and expose HTTP sessions (Playwright + plain requests)."""

    def __init__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self.session = self._build_session()

    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch a page via Playwright, returns HTML or None."""
        ctx = self._browser.new_context(user_agent=REQUEST_HEADERS["User-Agent"])
        try:
            page = ctx.new_page()
            resp = page.goto(url, wait_until="networkidle", timeout=60000)
            if resp and resp.status == 200:
                return page.content()
            return None
        except Exception:
            return None
        finally:
            ctx.close()

    def close(self):
        self._browser.close()
        self._pw.stop()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = requests.packages.urllib3.util.retry.Retry(  # type: ignore[attr-defined]
            total=3,
            backoff_factor=0.5,
            status_forcelist=[403, 429, 500, 502, 503, 504],
        )
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=32,
            pool_maxsize=64,
            max_retries=retry,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session


# ── JsUnpacker ─────────────────────────────────────────────────────────────────


class JsUnpacker:
    """Single-responsibility: decode Dean Edwards packed JavaScript."""

    @staticmethod
    def unpack(script_text: str) -> Optional[str]:
        match = re.search(
            r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'([^']*)'\s*\.split\('\|'\)",
            script_text,
            re.DOTALL,
        )
        if not match:
            return None

        packed = match.group(1)
        base = int(match.group(2))
        count = int(match.group(3))
        keys = match.group(4).split("|")

        def to_base(n: int, b: int) -> str:
            digits = "0123456789abcdefghijklmnopqrstuvwxyz"
            if n == 0:
                return "0"
            s = ""
            while n:
                s = digits[n % b] + s
                n //= b
            return s

        lookup = {
            to_base(i, base): (keys[i] if i < len(keys) and keys[i] else to_base(i, base))
            for i in range(count)
        }
        return re.sub(r"\b(\w+)\b", lambda m: lookup.get(m.group(0), m.group(0)), packed)


# ── PageScraper ────────────────────────────────────────────────────────────────


class PageScraper:
    """Single-responsibility: fetch a MissAV page and extract title + m3u8 URL."""

    def __init__(self, http: HttpClient, logger: Logger):
        self._http = http
        self._log = logger.log

    def scrape(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Return (title, m3u8_url) or (None, None) on failure."""
        url = re.sub(r"(https?://[^/]+)/dm\d+/", r"\1/", url)
        self._log(f"Fetching video info from {url}...")
        html = self._fetch_html(url)
        if html is None:
            return None, None

        title = self._extract_title(html)
        if not title:
            self._log("Could not extract title")
            return None, None
        title = re.sub(r"[^\w\-_\. ]", "", title)
        self._log(f"Title: {title}")

        m3u8_url = self._extract_m3u8(html)
        if not m3u8_url:
            self._log("Could not find m3u8 URL")
            return None, None
        self._log(f"M3U8 URL: {m3u8_url}")

        return title, m3u8_url

    def _fetch_html(self, url: str) -> Optional[str]:
        for attempt in range(MAX_RETRIES):
            html = self._http.fetch_page(url)
            if html is not None:
                return html
            self._log(f"Attempt {attempt + 1}/{MAX_RETRIES} failed")
            if attempt < MAX_RETRIES - 1:
                time.sleep(3)
        self._log("Failed to fetch page after retries")
        return None

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        match = re.search(r'og:title["\s]+content="([^"]+)"', html)
        return match.group(1) if match else None

    @staticmethod
    def _extract_m3u8(html: str) -> Optional[str]:
        for script in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
            if "eval(function" not in script or "m3u8" not in script:
                continue
            unpacked = JsUnpacker.unpack(script)
            if not unpacked:
                continue
            m = re.search(r"source\s*=\s*[\\']*(https?://[^'\\;\s]+\.m3u8)", unpacked)
            if not m:
                m = re.search(r"(https?://[^'\\;\s]+\.m3u8)", unpacked)
            if m:
                return m.group(1)
        return None


# ── EncryptionKey / M3u8Parser ─────────────────────────────────────────────────


@dataclass
class EncryptionKey:
    content: bytes
    iv: Optional[str]


@dataclass
class M3u8Info:
    segments: List[str]
    encryption: Optional[EncryptionKey]


class M3u8Parser:
    """Single-responsibility: fetch and parse an M3U8 playlist into segment URLs."""

    def __init__(self, http: HttpClient, logger: Logger):
        self._http = http
        self._log = logger.log

    def parse(self, m3u8_url: str) -> Optional[M3u8Info]:
        self._log("Fetching M3U8 playlist...")
        try:
            playlist = m3u8.load(m3u8_url, headers=M3U8_HEADERS)

            if playlist.playlists:
                best = max(
                    playlist.playlists,
                    key=lambda p: p.stream_info.bandwidth if p.stream_info else 0,
                )
                variant_url = self._resolve(m3u8_url, best.uri)
                self._log(f"Using variant: {variant_url}")
                playlist = m3u8.load(variant_url, headers=M3U8_HEADERS)
                m3u8_url = variant_url

            encryption = self._extract_key(m3u8_url, playlist)
            segments = self._build_segment_list(m3u8_url, playlist)

            self._log(f"Found {len(segments)} segments")
            return M3u8Info(segments=segments, encryption=encryption)

        except Exception as e:
            self._log(f"Error fetching M3U8: {e}")
            return None

    def _extract_key(self, m3u8_url: str, playlist) -> Optional[EncryptionKey]:
        for key in playlist.keys:
            if key and key.uri:
                key_uri = self._resolve(m3u8_url, key.uri)
                resp = self._http.session.get(key_uri, headers=M3U8_HEADERS, timeout=15)
                if resp.status_code == 200:
                    self._log("Encryption key found")
                    return EncryptionKey(content=resp.content, iv=getattr(key, "iv", None))
        return None

    @staticmethod
    def _build_segment_list(m3u8_url: str, playlist) -> List[str]:
        base = m3u8_url.rsplit("/", 1)[0] + "/"
        result = []
        for seg in playlist.segments:
            uri = seg.uri
            result.append(uri if uri.startswith("http") else base + uri.lstrip("/"))
        return result

    @staticmethod
    def _resolve(m3u8_url: str, uri: str) -> str:
        if uri.startswith("http"):
            return uri
        return m3u8_url.rsplit("/", 1)[0] + "/" + uri.lstrip("/")


# ── SegmentDownloader ──────────────────────────────────────────────────────────


class SegmentDownloader:
    """Single-responsibility: download and decrypt one segment to a temp file."""

    def __init__(self, http: HttpClient, temp_dir: Path, encryption: Optional[EncryptionKey], logger: Logger):
        self._http = http
        self._temp_dir = temp_dir
        self._encryption = encryption
        self._log = logger.log

    def download(self, seq_num: int, url: str) -> bool:
        try:
            resp = self._http.session.get(url, headers=M3U8_HEADERS, timeout=20)
            if resp.status_code != 200:
                self._log(f"Segment {seq_num}: HTTP {resp.status_code}")
                return False

            content = resp.content
            if self._encryption:
                content = self._decrypt(seq_num, content)

            (self._temp_dir / f"seg_{seq_num:06d}.ts").write_bytes(content)
            return True
        except Exception as e:
            self._log(f"Error downloading segment {seq_num}: {e}")
            return False

    def _decrypt(self, seq_num: int, data: bytes) -> bytes:
        assert self._encryption is not None
        enc = self._encryption
        if enc.iv:
            iv_bytes = bytes.fromhex(enc.iv.replace("0x", "").replace("0X", "").zfill(32))
        else:
            iv_bytes = seq_num.to_bytes(16, "big")
        return AES.new(enc.content, AES.MODE_CBC, iv_bytes).decrypt(data)


# ── SegmentMerger ──────────────────────────────────────────────────────────────


class SegmentMerger:
    """Single-responsibility: concatenate ordered temp .ts files into one output file."""

    def __init__(self, output_dir: Path, temp_dir: Path, logger: Logger):
        self._output_dir = output_dir
        self._temp_dir = temp_dir
        self._log = logger.log

    def merge(self, title: str, total: int) -> Optional[Path]:
        output_file = self._output_dir / f"{title}.ts"
        self._log(f"Merging {total} segments to {output_file}...")
        try:
            with open(output_file, "wb") as out:
                for i in range(total):
                    seg = self._temp_dir / f"seg_{i:06d}.ts"
                    if not seg.exists():
                        self._log(f"Segment {i} missing — aborting merge")
                        output_file.unlink(missing_ok=True)
                        return None
                    out.write(seg.read_bytes())
                    seg.unlink()
            try:
                self._temp_dir.rmdir()
            except OSError:
                pass
            return output_file
        except Exception as e:
            self._log(f"Error merging segments: {e}")
            output_file.unlink(missing_ok=True)
            return None


# ── VideoDownloadOrchestrator ──────────────────────────────────────────────────


class VideoDownloadOrchestrator:
    """Coordinates all components to download a MissAV video."""

    def __init__(
        self,
        url: str,
        output_dir: str = "downloads",
        silent: bool = False,
        workers: int = DEFAULT_WORKERS,
    ):
        self._url = url
        self._workers = workers

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        self._logger = Logger(silent)
        self._http = HttpClient()
        self._scraper = PageScraper(self._http, self._logger)
        self._m3u8_parser = M3u8Parser(self._http, self._logger)
        self._output_path = output_path
        self._temp_path = output_path / ".tmp"

    def run(self) -> bool:
        title, m3u8_url = self._scraper.scrape(self._url)
        if not title or not m3u8_url:
            return False

        info = self._m3u8_parser.parse(m3u8_url)
        if not info or not info.segments:
            return False

        self._temp_path.mkdir(parents=True, exist_ok=True)
        downloader = SegmentDownloader(self._http, self._temp_path, info.encryption, self._logger)
        downloaded = self._download_parallel(downloader, info.segments)

        total = len(info.segments)
        self._logger.log(f"Downloaded {downloaded}/{total} segments")
        if downloaded < total:
            return False

        merger = SegmentMerger(self._output_path, self._temp_path, self._logger)
        output_file = merger.merge(title, total)
        if output_file is None:
            return False

        self._http.close()
        self._logger.log(f"Download complete: {output_file}")
        return True

    def _download_parallel(self, downloader: SegmentDownloader, segments: List[str]) -> int:
        total = len(segments)
        self._logger.log(f"Downloading {total} segments with {self._workers} workers...")

        completed = 0

        with tqdm(total=total, unit="seg", desc="Downloading", leave=True) as bar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self._workers) as executor:
                futures = {
                    executor.submit(downloader.download, i, url): i
                    for i, url in enumerate(segments)
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        if future.result():
                            completed += 1
                    except Exception as e:
                        self._logger.log(f"Segment error: {e}")
                    bar.update(1)

        return completed


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="MissAV video downloader")
    parser.add_argument("url", help="MissAV video URL (e.g., https://missav.ai/sone-543)")
    parser.add_argument("-o", "--output", default="downloads", help="Output directory (default: downloads)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress output messages")
    parser.add_argument("-w", "--workers", type=int, default=DEFAULT_WORKERS, help=f"Parallel download workers (default: {DEFAULT_WORKERS})")
    args = parser.parse_args()

    orchestrator = VideoDownloadOrchestrator(args.url, args.output, args.quiet, args.workers)
    sys.exit(0 if orchestrator.run() else 1)


if __name__ == "__main__":
    main()
