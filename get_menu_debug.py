import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()

            url = "https://de.everyday.sodexo.com/menu/Deutsche%20Bank%20Berlin%20OSA/Speiseplan%20Deutsche%20Bank"
            await page.goto(url)
            # Wait for the main app to load and some likely menu content
            try:
                await page.wait_for_selector('h2', timeout=15000)
                await asyncio.sleep(5)
            except Exception:
                pass
            
            with open("dom_dump.html", "w") as f:
                f.write(await page.content())
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
