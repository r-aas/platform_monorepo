#!/usr/bin/env python3
"""YouTube Ingest Service — extract playlist metadata + transcripts.

Runs on Mac host. n8n (in k3d) calls this for YouTube ETL pipeline.

Endpoints:
    POST /extract       — Extract videos from playlist(s)
    POST /transcript    — Get transcript for a single video
    POST /batch         — Full pipeline: extract + transcripts for all videos
    GET  /health        — Health check
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("yt-ingest")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COOKIES_FILE = os.getenv("YT_COOKIES_FILE", str(Path.home() / ".config" / "yt-dlp" / "cookies.txt"))
CACHE_DIR = Path(os.getenv("YT_CACHE_DIR", str(Path.home() / ".cache" / "yt-ingest")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
YT_DLP_BIN = os.getenv("YT_DLP_BIN", "yt-dlp")

# Default playlists to ingest
DEFAULT_PLAYLISTS = [
    "https://www.youtube.com/playlist?list=WL",  # Watch Later
    "https://www.youtube.com/playlist?list=LL",  # Liked Videos
]

app = FastAPI(title="YouTube Ingest", version="0.1.0")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ExtractRequest(BaseModel):
    playlist_urls: list[str] | None = None
    max_videos: int = 50
    use_cookies: bool = True


class TranscriptRequest(BaseModel):
    video_id: str
    languages: list[str] = ["en"]


class BatchRequest(BaseModel):
    playlist_urls: list[str] | None = None
    max_videos: int = 50
    use_cookies: bool = True
    languages: list[str] = ["en"]
    skip_existing: bool = True


class VideoMeta(BaseModel):
    video_id: str
    title: str
    channel: str
    channel_id: str | None = None
    published_at: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    description: str | None = None
    tags: list[str] = []
    url: str
    playlist: str | None = None
    thumbnail: str | None = None


class VideoWithTranscript(BaseModel):
    meta: VideoMeta
    transcript: str | None = None
    transcript_language: str | None = None
    transcript_error: str | None = None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _run_ytdlp(args: list[str], use_cookies: bool = True) -> str:
    cmd = [YT_DLP_BIN]
    if use_cookies and Path(COOKIES_FILE).exists():
        cmd.extend(["--cookies", COOKIES_FILE])
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log.warning("yt-dlp stderr: %s", result.stderr[:500])
    return result.stdout


def extract_playlist(url: str, max_videos: int = 50, use_cookies: bool = True) -> list[VideoMeta]:
    """Extract video metadata from a YouTube playlist."""
    output = _run_ytdlp(
        [
            "--flat-playlist",
            "--dump-json",
            "--playlist-end", str(max_videos),
            "--no-warnings",
            url,
        ],
        use_cookies=use_cookies,
    )

    videos = []
    playlist_name = _playlist_name(url)
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        vid = data.get("id") or data.get("url", "")
        if not vid:
            continue

        videos.append(
            VideoMeta(
                video_id=vid,
                title=data.get("title", "Unknown"),
                channel=data.get("channel", data.get("uploader", "Unknown")),
                channel_id=data.get("channel_id"),
                published_at=data.get("upload_date"),
                duration_seconds=data.get("duration"),
                view_count=data.get("view_count"),
                description=(data.get("description") or "")[:500],
                tags=data.get("tags", [])[:10] if data.get("tags") else [],
                url=f"https://www.youtube.com/watch?v={vid}",
                playlist=playlist_name,
                thumbnail=data.get("thumbnail"),
            )
        )

    return videos


def _playlist_name(url: str) -> str:
    if "list=WL" in url:
        return "Watch Later"
    if "list=LL" in url:
        return "Liked Videos"
    match = re.search(r"list=([^&]+)", url)
    return match.group(1) if match else "Unknown"


def get_transcript(video_id: str, languages: list[str] | None = None) -> tuple[str | None, str | None, str | None]:
    """Get transcript for a video. Returns (text, language, error)."""
    langs = languages or ["en"]

    # Check cache first
    cache_key = hashlib.md5(f"{video_id}:{','.join(langs)}".encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.txt"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        return cached.get("text"), cached.get("language"), None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=langs)

        text = " ".join(snippet.text for snippet in transcript.snippets)
        language = transcript.language

        # Cache it
        cache_file.write_text(json.dumps({"text": text, "language": language}))

        return text, language, None

    except Exception as e:
        error_msg = str(e)[:200]
        # Try auto-generated captions
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            # Find any available transcript
            for t in transcript_list:
                try:
                    transcript = ytt_api.fetch(video_id, languages=[t.language])
                    text = " ".join(snippet.text for snippet in transcript.snippets)
                    cache_file.write_text(json.dumps({"text": text, "language": t.language}))
                    return text, t.language, None
                except Exception:
                    continue
        except Exception:
            pass

        return None, None, error_msg


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/extract")
async def extract(req: ExtractRequest) -> list[VideoMeta]:
    urls = req.playlist_urls or DEFAULT_PLAYLISTS
    all_videos: list[VideoMeta] = []
    for url in urls:
        try:
            videos = extract_playlist(url, max_videos=req.max_videos, use_cookies=req.use_cookies)
            all_videos.extend(videos)
        except Exception as e:
            log.error("Failed to extract %s: %s", url, e)
    return all_videos


@app.post("/transcript")
async def transcript(req: TranscriptRequest) -> dict:
    text, language, error = get_transcript(req.video_id, req.languages)
    return {
        "video_id": req.video_id,
        "transcript": text,
        "language": language,
        "error": error,
        "has_transcript": text is not None,
    }


@app.post("/batch")
async def batch_extract(req: BatchRequest) -> dict:
    """Full pipeline: extract playlists + fetch transcripts for all videos."""
    urls = req.playlist_urls or DEFAULT_PLAYLISTS

    # Stage 1: Extract metadata
    all_videos: list[VideoMeta] = []
    for url in urls:
        try:
            videos = extract_playlist(url, max_videos=req.max_videos, use_cookies=req.use_cookies)
            all_videos.extend(videos)
        except Exception as e:
            log.error("Failed to extract %s: %s", url, e)

    # Deduplicate by video_id
    seen = set()
    unique_videos = []
    for v in all_videos:
        if v.video_id not in seen:
            seen.add(v.video_id)
            unique_videos.append(v)

    # Stage 2: Fetch transcripts
    results: list[VideoWithTranscript] = []
    for video in unique_videos:
        text, language, error = get_transcript(video.video_id, req.languages)
        results.append(
            VideoWithTranscript(
                meta=video,
                transcript=text,
                transcript_language=language,
                transcript_error=error,
            )
        )

    with_transcript = sum(1 for r in results if r.transcript)
    return {
        "total_videos": len(results),
        "with_transcript": with_transcript,
        "without_transcript": len(results) - with_transcript,
        "playlists": urls,
        "extracted_at": datetime.utcnow().isoformat(),
        "videos": [r.model_dump() for r in results],
    }


@app.get("/health")
async def health():
    ytdlp_ok = False
    try:
        result = subprocess.run([YT_DLP_BIN, "--version"], capture_output=True, text=True, timeout=5)
        ytdlp_ok = result.returncode == 0
        ytdlp_version = result.stdout.strip() if ytdlp_ok else None
    except Exception:
        ytdlp_version = None

    cookies_exist = Path(COOKIES_FILE).exists()

    return {
        "status": "ok" if ytdlp_ok else "degraded",
        "yt_dlp_available": ytdlp_ok,
        "yt_dlp_version": ytdlp_version,
        "cookies_file": COOKIES_FILE,
        "cookies_available": cookies_exist,
        "cache_dir": str(CACHE_DIR),
        "default_playlists": DEFAULT_PLAYLISTS,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7778)
