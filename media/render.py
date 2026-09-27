# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render the slide deck (PDF + PNGs) and the cover image with headless Chromium.

Usage: uv run media/render.py
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

MEDIA = Path(__file__).resolve().parent
BUILD = MEDIA / "build"
SLIDES = 9
VIEWPORT = {"width": 1280, "height": 720}


def main() -> None:
    """Write media/TraceFix_slides.pdf, media/cover.png and build/slide-N.png."""
    BUILD.mkdir(exist_ok=True)
    deck = (MEDIA / "slides.html").as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        for n in range(1, SLIDES + 1):
            page.goto(f"{deck}?slide={n}")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=BUILD / f"slide-{n}.png")
        page.goto((MEDIA / "cover.html").as_uri())
        page.wait_for_load_state("networkidle")
        page.screenshot(path=MEDIA / "cover.png")
        page.goto(deck)
        page.wait_for_load_state("networkidle")
        page.pdf(
            path=MEDIA / "TraceFix_slides.pdf",
            width="1280px",
            height="720px",
            print_background=True,
        )
        browser.close()
    print("rendered slides, cover and PDF")


if __name__ == "__main__":
    main()
