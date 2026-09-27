# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Build the narrated demo video from real TraceFix footage.

Each segment in narration.json is recorded with headless Chromium (slides, the
recorded run replays at real event timing, the incident report), narrated with
edge-tts, and concatenated with ffmpeg into media/TraceFix_demo.mp4.

Usage: uv run media/make_video.py   (serve ./site on :8765 first)
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

MEDIA = Path(__file__).resolve().parent
BUILD = MEDIA / "build"
SITE_URL = "http://localhost:8765"
VOICE = "en-US-AndrewNeural"
SIZE = {"width": 1280, "height": 720}


def main() -> None:
    """Record, narrate and assemble every segment."""
    segments = json.loads((MEDIA / "narration.json").read_text())
    clips = [build_segment(seg) for seg in segments]
    listing = BUILD / "concat.txt"
    listing.write_text("".join(f"file '{clip.name}'\n" for clip in clips))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
           str(MEDIA / "TraceFix_demo.mp4"))
    print(f"video: {MEDIA / 'TraceFix_demo.mp4'} ({duration(MEDIA / 'TraceFix_demo.mp4'):.1f}s)")


def build_segment(seg: dict) -> Path:
    """Narrate, record and mux one segment; return the clip path."""
    parts = seg.get("parts") or [{"at": 0.3, "text": seg["text"]}]
    audio = [(part["at"], tts(f"{seg['id']}-{i}", part["text"])) for i, part in enumerate(parts)]
    speech_end = max(at + duration(path) for at, path in audio) + 0.8
    length = max(speech_end, visual_length(seg), seg.get("min", 0))
    video = record(seg, length)
    return mux(seg["id"], video, audio, length)


def visual_length(seg: dict) -> float:
    if seg["kind"] != "replay":
        return 0.0
    return 3.8 + seg["length"] / seg["speed"] + 1.8


def tts(name: str, text: str) -> Path:
    out = BUILD / f"{name}.mp3"
    subprocess.run(["uvx", "edge-tts", "--voice", VOICE, "--rate", "+6%", "--text", text,
                    "--write-media", str(out)], check=True, capture_output=True)
    return out


def record(seg: dict, length: float) -> Path:
    """Record the segment's visual with Playwright; return the webm and lead-in."""
    raw_dir = BUILD / f"raw-{seg['id']}"
    raw_dir.mkdir(exist_ok=True)
    for old in raw_dir.glob("*.webm"):
        old.unlink()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=raw_dir,
                                      record_video_size=SIZE)
        page = context.new_page()
        opened = time.time()
        page.goto(url_for(seg))
        page.wait_for_load_state("networkidle")
        lead = time.time() - opened
        play(page, seg, length)
        context.close()
        browser.close()
    video = next(raw_dir.glob("*.webm"))
    (raw_dir / "lead.txt").write_text(f"{lead:.2f}")
    return video


def url_for(seg: dict) -> str:
    if seg["kind"] == "slide":
        return f"{(MEDIA / 'slides.html').as_uri()}?slide={seg['slide']}"
    if seg["kind"] == "replay":
        return f"{SITE_URL}/{seg['url']}?speed={seg['speed']}"
    return f"{SITE_URL}/{seg['url']}"


def play(page: Page, seg: dict, length: float) -> None:
    if seg["kind"] != "report":
        page.wait_for_timeout(length * 1000)
        return
    page.wait_for_timeout(1500)
    height = page.evaluate("document.body.scrollHeight - innerHeight")
    steps = int((length - 3) * 30)
    for i in range(steps):
        page.evaluate(f"window.scrollTo(0, {height * (i + 1) / steps})")
        page.wait_for_timeout(1000 / 30)
    page.wait_for_timeout(1500)


def mux(name: str, video: Path, audio: list[tuple[float, Path]], length: float) -> Path:
    """Trim the lead-in, lay narration at its offsets, encode to H.264/AAC."""
    lead = float((video.parent / "lead.txt").read_text())
    out = BUILD / f"clip-{name}.mp4"
    inputs = ["-ss", f"{lead:.2f}", "-i", str(video)]
    filters = []
    for i, (at, path) in enumerate(audio, start=1):
        inputs += ["-i", str(path)]
        ms = int(at * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},aresample=44100[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(audio) + 1))
    filters.append(f"{mix}amix=inputs={len(audio)}:normalize=0,apad[aout]")
    ffmpeg(*inputs, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
           "-t", f"{length:.2f}", "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
           "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
           "-ac", "2", str(out))
    return out


def duration(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(proc.stdout)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


if __name__ == "__main__":
    main()
