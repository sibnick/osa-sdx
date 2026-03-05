import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://de.everyday.sodexo.com/menu/Deutsche%20Bank%20Berlin%20OSA/Speiseplan%20Deutsche%20Bank", wait_until="domcontentloaded")
        
        try:
            await page.wait_for_selector('.mdc-tab, mat-select', timeout=15000)
            await asyncio.sleep(2)
        except Exception:
            pass
            
        tabs = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('.mdc-tab')).map(tab => tab.textContent.trim());
        }''')
        print("TABS:", tabs)
        
        selects = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('mat-select')).map(s => s.textContent.trim());
        }''')
        print("SELECTS:", selects)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
