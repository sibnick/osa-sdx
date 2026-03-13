#!/usr/bin/env python3
import asyncio
import json
import argparse
import datetime
import re
try:
    import newrelic.agent
except ImportError:
    newrelic = None
from playwright.async_api import async_playwright
from deep_translator import GoogleTranslator

def instrument_task(func):
    if newrelic:
        return newrelic.agent.background_task()(func)
    return func

@instrument_task
async def get_sodexo_menu(url: str, headless: bool, target_date_str: str = None, fetch_calories: bool = True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            print("Fetching menu from Everyday by Sodexo...")
            await page.goto(url, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector('h3.category-header, #onetrust-accept-btn-handler', timeout=15000)
            except Exception:
                pass

            banner_btn = await page.query_selector('#onetrust-accept-btn-handler')
            if banner_btn:
                await banner_btn.click()
                await asyncio.sleep(1)
                
            if target_date_str:
                print(f"Navigating to date: {target_date_str}")
                current_year = datetime.datetime.now().year
                try:
                    target_date = datetime.datetime.strptime(f"{target_date_str}.{current_year}", "%d.%m.%Y")
                    target_kw = target_date.isocalendar()[1]
                    
                    try:
                        await page.wait_for_selector('mat-select', timeout=10000)
                        await asyncio.sleep(1)
                    except Exception:
                        pass
                    
                    select_locators = page.locator('mat-select')
                    count = await select_locators.count()
                    target_select = None
                    for i in range(count):
                        text = await select_locators.nth(i).inner_text()
                        if "CW:" in text or "KW:" in text:
                            target_select = select_locators.nth(i)
                            break
                            
                    if target_select:
                        await target_select.click()
                        await page.wait_for_selector('mat-option')
                        options = page.locator('mat-option')
                        opt_count = await options.count()
                        for i in range(opt_count):
                            opt_text = await options.nth(i).inner_text()
                            if str(target_kw) in opt_text:
                                await options.nth(i).click()
                                break
                        await asyncio.sleep(2)
                    
                    tabs = page.locator('.mdc-tab')
                    count = await tabs.count()
                    for i in range(count):
                        text = await tabs.nth(i).inner_text()
                        if target_date_str in text:
                            await tabs.nth(i).click()
                            break
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"Warning: Failed to navigate to {target_date_str}. Exception: {e}")

            print("Waiting for menu data to render...")
            try:
                await page.wait_for_selector('app-category', timeout=10000)
            except Exception:
                print("Warning: Could not find menu categories.")

            # Extract basic info first
            menu_data = await page.evaluate('''() => {
                const categories = Array.from(document.querySelectorAll('app-category'));
                return categories.map(cat => {
                    const categoryName = cat.querySelector('h3.category-header')?.textContent.trim() || 'Unknown';
                    const items = Array.from(cat.querySelectorAll('.product-wrapper')).map(row => {
                        const button = row.querySelector('.name-column button');
                        const name = button ? button.textContent.trim() : 'Unknown Dish';
                        const price = row.querySelector('.price-column .price')?.textContent.replace(/\\s+/g, ' ').trim() || 'N/A';
                        return { name, price, hasDetails: !!button };
                    });
                    return { categoryName, items };
                });
            }''')

            if fetch_calories:
                print("Extracting calories for each item (this may take a moment)...")
                all_product_wrappers = page.locator('.product-wrapper')
                wrapper_count = await all_product_wrappers.count()
                
                # Create a map for easy lookup
                item_index = 0
                for category in menu_data:
                    for item in category['items']:
                        if item['hasDetails'] and item_index < wrapper_count:
                            try:
                                # Click the item
                                print(f"  Fetching details for: {item['name']}")
                                btn = all_product_wrappers.nth(item_index).locator('button').first
                                await btn.scroll_into_view_if_needed()
                                
                                # Navigation-based detail view
                                await btn.click()
                                
                                # Wait for product page to load (URL contains /product/)
                                try:
                                    await page.wait_for_url(re.compile(r'.*/product/.*'), timeout=10000)
                                except:
                                    print(f"    Warning: Page did not navigate for {item['name']}")
                                    raise Exception("Navigation timeout")

                                # Find nutritional tab on the new page
                                nutri_tab_selector = '.mdc-tab:has-text("NÄHRWERTE"), .mdc-tab:has-text("NUTRITIONAL INFORMATION")'
                                await page.wait_for_selector(nutri_tab_selector, timeout=5000)
                                await page.click(nutri_tab_selector)
                                
                                # Extract calories from the table
                                kcal_cell = page.locator('table.push-bottom tr:has-text("kcal") td, table tr:has-text("Brennwert") td').last
                                await kcal_cell.wait_for(state="visible", timeout=5000)
                                kcal_text = await kcal_cell.inner_text()
                                
                                # Clean up: 385 kJ 93 kcal -> 93
                                # We look specifically for the number preceding 'kcal'
                                match = re.search(r'(\d+)\s*kcal', kcal_text)
                                if match:
                                    item['calories'] = int(match.group(1))
                                else:
                                    item['calories'] = kcal_text.strip()
                                
                                # Go back to the menu
                                await page.go_back(wait_until="domcontentloaded")
                                # Wait for the menu to be ready again
                                await page.wait_for_selector('.product-wrapper', timeout=10000)
                                # Re-locate wrappers as DOM might have refreshed
                                all_product_wrappers = page.locator('.product-wrapper')
                                await asyncio.sleep(0.3)
                            except Exception as e:
                                print(f"    Error fetching calories for {item['name']}: {e}")
                                item['calories'] = None
                                # Try to get back to menu if stuck
                                if "/product/" in page.url:
                                    await page.go_back()
                                    await page.wait_for_selector('.product-wrapper', timeout=10000)
                                    all_product_wrappers = page.locator('.product-wrapper')
                                await asyncio.sleep(0.5)
                        item_index += 1

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
            return menu_data
        finally:
            await browser.close()

def format_menu(menu_data, telegram=False):
    if not menu_data:
        return "No menu data found."
        
    if telegram:
        lines = []
        lines.append("<b>🍽 SODEXO MENU - BERLIN OSA</b>\n")
        for category in menu_data:
            cat_name = category['categoryName'].upper()
            if category.get('categoryName_ru'):
                cat_name += f" ({category['categoryName_ru'].upper()})"
            lines.append(f"<b>━━━ {cat_name} ━━━</b>")
            
            if not category['items']:
                lines.append("  <i>(No items)</i>")
            else:
                for item in category['items']:
                    name = item['name'].replace('<', '&lt;').replace('>', '&gt;')
                    price = item['price'].replace('<', '&lt;').replace('>', '&gt;')
                    name_ru = item.get('name_ru', '').replace('<', '&lt;').replace('>', '&gt;')
                    cal = item.get('calories', '')
                    
                    cal_str = f" | ⚡ {cal} kcal" if cal else ""
                    lines.append(f"• <b>{name}</b>")
                    if name_ru:
                        lines.append(f"  └ <i>{name_ru}</i>")
                    lines.append(f"  💰 {price}{cal_str}")
            lines.append("")
        return "\n".join(lines)
    
    # Text format
    lines = []
    lines.append("=" * 60)
    lines.append("SODEXO MENU - BERLIN OSA".center(60))
    lines.append("=" * 60)
    lines.append("")
    for category in menu_data:
        cat_name = category['categoryName'].upper()
        if category.get('categoryName_ru'):
            cat_name += f" ({category['categoryName_ru'].upper()})"
        lines.append(cat_name)
        for item in category['items']:
            cal = item.get('calories', '')
            cal_str = f" ({cal} kcal)" if cal else ""
            lines.append(f"  {item['name']:<45} | {item['price']}{cal_str}")
        lines.append("")
    return "\n".join(lines)

DEFAULT_URL = "https://de.everyday.sodexo.com/menu/Deutsche%20Bank%20Berlin%20OSA/Speiseplan%20Deutsche%20Bank"

def main():
    parser = argparse.ArgumentParser(description="Terminal app to print Sodexo Everyday Menu")
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--date', type=str, help="DD.MM", default=None)
    parser.add_argument('--telegram', action='store_true')
    parser.add_argument('--no-calories', action='store_false', dest='calories')
    args = parser.parse_args()

    try:
        menu_data = asyncio.run(get_sodexo_menu(DEFAULT_URL, headless=not args.debug, target_date_str=args.date, fetch_calories=args.calories))
        print(format_menu(menu_data, telegram=args.telegram))
    except Exception as e:
        print(f"Error fetching menu: {e}")

if __name__ == "__main__":
    main()
