"""Render the README banner and architecture diagram from the HTML in this folder.

    python docs/diagrams/render.py      # requires playwright + Pillow

Each page lays out one `#frame` element; it is captured on a transparent
background at 2x so the images stay sharp on high-DPI screens. The banner is
mostly gradient and photo, so it is stored as WebP (a PNG would be ~1.3 MB).
Set CHROMIUM_PATH to use an existing Chromium instead of `playwright install`.
"""

import asyncio
import io
import os
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
OUT = HERE.parent / "images"
# page -> (themes to render (None: the page has a single look), output format)
PAGES = {
    "architecture": (("light", "dark"), "png"),
    "banner": ((None,), "webp"),
}


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = await browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
        for name, (themes, fmt) in PAGES.items():
            for theme in themes:
                out = OUT / (f"{name}-{theme}.{fmt}" if theme else f"{name}.{fmt}")
                await page.goto(f"{(HERE / f'{name}.html').as_uri()}?theme={theme or 'light'}")
                await page.wait_for_load_state("networkidle")
                png = await page.locator("#frame").screenshot(omit_background=True)
                if fmt == "webp":
                    Image.open(io.BytesIO(png)).save(out, "WEBP", quality=92, method=6)
                else:
                    out.write_bytes(png)
                print("wrote", out)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
