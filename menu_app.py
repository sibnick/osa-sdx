#!/usr/bin/env python3
import asyncio
import json
import argparse
import datetime
from playwright.async_api import async_playwright
from deep_translator import GoogleTranslator

async def get_sodexo_menu(url: str, headless: bool, target_date_str: str = None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        print("Fetching menu from Everyday by Sodexo...")
        # Load the page and wait until network is mostly idle
        await page.goto(url, wait_until="domcontentloaded")

        try:
            # Wait for either the cookie banner to appear or the menu to load
            await page.wait_for_selector('h3.category-header, #onetrust-accept-btn-handler', timeout=15000)
        except Exception:
            pass

        # Try to accept cookies if the button is there
        banner_btn = await page.query_selector('#onetrust-accept-btn-handler')
        if banner_btn:
            await banner_btn.click()
            await asyncio.sleep(1)
            
        if target_date_str:
            print(f"Navigating to date: {target_date_str}")
            # Figure out target KW
            current_year = datetime.datetime.now().year
            try:
                target_date = datetime.datetime.strptime(f"{target_date_str}.{current_year}", "%d.%m.%Y")
                target_kw = target_date.isocalendar()[1]
                
                # Wait for the navigation bar to loaded
                try:
                    await page.wait_for_selector('mat-select', timeout=15000)
                    await asyncio.sleep(2) # Give it time to populate
                except Exception:
                    pass
                
                # Find the CW/KW dropdown
                select_locators = page.locator('mat-select')
                count = await select_locators.count()
                target_select = None
                for i in range(count):
                    text = await select_locators.nth(i).inner_text()
                    if "CW:" in text or "KW:" in text:
                        target_select = select_locators.nth(i)
                        break
                        
                if target_select:
                    print("Found CW dropdown, opening...")
                    await target_select.click()
                    await page.wait_for_selector('mat-option')
                    await asyncio.sleep(1)
                    
                    options = page.locator('mat-option')
                    opt_count = await options.count()
                    clicked = False
                    for i in range(opt_count):
                        opt_text = await options.nth(i).inner_text()
                        if str(target_kw) in opt_text:
                            print(f"Selecting CW/KW: {opt_text}")
                            await options.nth(i).click()
                            clicked = True
                            break
                    if not clicked:
                        print("Target KW not found in dropdown.")
                        await page.mouse.click(0, 0)
                    await asyncio.sleep(2)
                
                # Click the tab for the target day
                print("Looking for day tab...")
                tabs = page.locator('.mdc-tab')
                count = await tabs.count()
                clicked = False
                for i in range(count):
                    text = await tabs.nth(i).inner_text()
                    if target_date_str in text:
                        print(f"Clicking day tab: {text.strip()}")
                        await tabs.nth(i).click()
                        clicked = True
                        break
                if not clicked:
                    print("Target day tab not found.")
                await asyncio.sleep(2)
                
                # Verify active tab
                try:
                    active_tab = await page.locator('.mdc-tab--active').inner_text()
                    print(f"Currently active tab is: {active_tab.strip().split()[-1]}")
                except Exception:
                    pass
            except Exception as e:
                print(f"Warning: Failed to navigate to {target_date_str}. Exception: {e}")

        # Wait for actual menu categories to ensure Firestore data is rendered
        print("Waiting for menu data to render...")
        try:
            await page.wait_for_selector('h3.category-header', timeout=15000)
            await asyncio.sleep(2) # Give it a bit more time for prices to render
        except Exception:
            print("Warning: Could not find menu categories. The menu might be empty today or still loading.")

        menu_data = await page.evaluate('''() => {
            const categories = Array.from(document.querySelectorAll('app-category'));
            return categories.map(cat => {
                const categoryName = cat.querySelector('h3.category-header')?.textContent.trim() || 'Unknown Category';
                const items = Array.from(cat.querySelectorAll('.product-wrapper')).map(row => {
                    const nameEl = row.querySelector('.name-column button span, .name-column span.pre-wrap');
                    const name = nameEl ? nameEl.textContent.trim() : 'Unknown Dish';
                    
                    const priceEl = row.querySelector('.price-column .price');
                    const price = priceEl ? priceEl.textContent.replace(/\\s+/g, ' ').trim() : 'N/A';
                    
                    return { name, price };
                });
                return { categoryName, items };
            });
        }''')

        print("Translating menu to Russian...")
        translator = GoogleTranslator(source='auto', target='ru')
        for category in menu_data:
            if category['categoryName']:
                try:
                    category['categoryName_ru'] = translator.translate(category['categoryName'])
                except Exception:
                    category['categoryName_ru'] = ""
            for item in category['items']:
                if item['name']:
                    try:
                        item['name_ru'] = translator.translate(item['name'])
                    except Exception:
                        item['name_ru'] = ""

        await browser.close()
        return menu_data

def format_menu(menu_data, telegram=False):
    if not menu_data:
        return "No menu data found."
        
    if telegram:
        lines = []
        lines.append("<b>🍽 SODEXO MENU - DEUTSCHE BANK BERLIN OSA</b>\n")
        for category in menu_data:
            cat_name = category['categoryName'].upper()
            if category.get('categoryName_ru'):
                cat_name += f" ({category['categoryName_ru'].upper()})"
            lines.append(f"<b>--- {cat_name} ---</b>")
            
            if not category['items']:
                lines.append("  <i>(No items)</i>")
            else:
                for item in category['items']:
                    # Escape HTML tags
                    name = item['name'].replace('<', '&lt;').replace('>', '&gt;')
                    price = item['price'].replace('<', '&lt;').replace('>', '&gt;')
                    name_ru = item.get('name_ru', '').replace('<', '&lt;').replace('>', '&gt;')
                    
                    lines.append(f"• {name} | <i>{price}</i>")
                    if name_ru:
                        lines.append(f"  └ <i>{name_ru}</i>")
            lines.append("")
        return "\n".join(lines)
    
    lines = []
    lines.append("=" * 60)
    lines.append("SODEXO MENU - DEUTSCHE BANK BERLIN OSA".center(60))
    lines.append("=" * 60)
    lines.append("")

    for category in menu_data:
        cat_name = category['categoryName'].upper()
        if category.get('categoryName_ru'):
            cat_name += f" ({category['categoryName_ru'].upper()})"
        lines.append(f"--- {cat_name} ---")
        
        if not category['items']:
            lines.append("  (No items)")
        else:
            for item in category['items']:
                name = item['name']
                price = item['price']
                name_ru = item.get('name_ru', '')
                
                # Wrap name if too long
                if len(name) > 45:
                    name = name[:42] + "..."
                if name_ru and len(name_ru) > 45:
                    name_ru = name_ru[:42] + "..."
                    
                lines.append(f"  {name:<45} | {price}")
                if name_ru:
                    lines.append(f"  {name_ru:<45} |")
        lines.append("")
    
    return "\n".join(lines)

DEFAULT_URL = "https://de.everyday.sodexo.com/menu/Deutsche%20Bank%20Berlin%20OSA/Speiseplan%20Deutsche%20Bank"

def main():
    parser = argparse.ArgumentParser(description="Terminal app to print Sodexo Everyday Menu")
    parser.add_argument('--debug', action='store_true', help="Run browser in non-headless mode for debugging")
    parser.add_argument('--date', type=str, help="Specific date to check in DD.MM format (e.g. 04.03)", default=None)
    parser.add_argument('--telegram', action='store_true', help="Format output for Telegram (HTML mode)")
    args = parser.parse_args()

    try:
        menu_data = asyncio.run(get_sodexo_menu(DEFAULT_URL, headless=not args.debug, target_date_str=args.date))
        print(format_menu(menu_data, telegram=args.telegram))
    except Exception as e:
        print(f"Error fetching menu: {e}")

if __name__ == "__main__":
    main()
