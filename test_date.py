import asyncio
import datetime
from playwright.async_api import async_playwright

async def test_date(target_date_str="04.03"):
    # Parse target date
    current_year = datetime.datetime.now().year
    target_date = datetime.datetime.strptime(f"{target_date_str}.{current_year}", "%d.%m.%Y")
    target_kw = target_date.isocalendar()[1]
    
    print(f"Target: {target_date_str}, Year: {current_year}, KW/CW: {target_kw}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Loading page...")
        await page.goto("https://de.everyday.sodexo.com/menu/Deutsche%20Bank%20Berlin%20OSA/Speiseplan%20Deutsche%20Bank", wait_until="domcontentloaded")
        
        try:
            await page.wait_for_selector('mat-select', timeout=15000)
            await asyncio.sleep(2)
        except Exception:
            pass
            
        print("Finding CW/KW select...")
        # Find the select that contains CW or KW
        select_locators = page.locator('mat-select')
        count = await select_locators.count()
        target_select = None
        for i in range(count):
            text = await select_locators.nth(i).inner_text()
            if "CW:" in text or "KW:" in text:
                target_select = select_locators.nth(i)
                break
                
        if target_select:
            print("Clicking select...")
            await target_select.click()
            await page.wait_for_selector('mat-option')
            await asyncio.sleep(1)
            
            # Click the option for the target KW
            options = page.locator('mat-option')
            opt_count = await options.count()
            found_kw = False
            for i in range(opt_count):
                opt_text = await options.nth(i).inner_text()
                if str(target_kw) in opt_text:
                    print(f"Selecting option: {opt_text}")
                    await options.nth(i).click()
                    found_kw = True
                    break
            
            if not found_kw:
                print(f"Could not find KW/CW {target_kw} in the dropdown.")
                # Maybe click away to close it
                await page.mouse.click(0, 0)
        else:
            print("Could not find the CW/KW dropdown.")
            
        await asyncio.sleep(2)
        
        print("Finding day tab...")
        tabs = page.locator('.mdc-tab')
        count = await tabs.count()
        found_tab = False
        for i in range(count):
            text = await tabs.nth(i).inner_text()
            if target_date_str in text:
                print(f"Clicking tab: {text}")
                await tabs.nth(i).click()
                found_tab = True
                break
                
        if not found_tab:
            print(f"Could not find tab for date {target_date_str}")
        
        await asyncio.sleep(2)
        
        # Verify the current selected tab
        active_tab = await page.locator('.mdc-tab--active').inner_text()
        print(f"Active tab is now: {active_tab}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_date("04.03"))
