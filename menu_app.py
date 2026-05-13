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
                viewport={'width': 1600, 'height': 1200},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()

            print("Fetching menu from Everyday by Sodexo...")
            await page.goto(url, wait_until="load", timeout=60000)

            try:
                await page.wait_for_selector('#onetrust-accept-btn-handler', timeout=5000)
                await page.click('#onetrust-accept-btn-handler')
            except: pass
                
            if target_date_str:
                print(f"Navigating to date: {target_date_str}")
                current_year = datetime.datetime.now().year
                try:
                    target_date = datetime.datetime.strptime(f"{target_date_str}.{current_year}", "%d.%m.%Y")
                    target_kw = target_date.isocalendar()[1]
                    
                    # 1. Selection of week (CW/KW)
                    print(f"  Target week: CW {target_kw}")
                    try:
                        await page.wait_for_selector('mat-select', timeout=10000)
                        
                        # Find the correct mat-select using JS to be robust
                        success = await page.evaluate('''(kw) => {
                            const selects = Array.from(document.querySelectorAll('mat-select'));
                            const target = selects.find(s => s.textContent.includes('CW') || s.textContent.includes('KW'));
                            if (target) {
                                target.click();
                                return true;
                            }
                            return false;
                        }''', target_kw)
                        
                        if success:
                            await page.wait_for_selector('mat-option', timeout=5000)
                            # Find the correct option
                            opt_success = await page.evaluate('''(kw) => {
                                const options = Array.from(document.querySelectorAll('mat-option'));
                                const target = options.find(o => o.textContent.includes(kw.toString()));
                                if (target) {
                                    target.click();
                                    return true;
                                }
                                return false;
                            }''', target_kw)
                            if opt_success:
                                print(f"  Selected week CW {target_kw}")
                                await asyncio.sleep(3) # Wait for page to refresh
                    except Exception as e:
                        print(f"  Warning: Week selection failed: {e}")

                    # 2. Selection of day tab
                    await page.wait_for_selector('.mdc-tab', timeout=15000)
                    tabs = page.locator('.mdc-tab')
                    count = await tabs.count()
                    found_tab = False
                    for i in range(count):
                        text = await tabs.nth(i).inner_text()
                        if target_date_str in text:
                            await tabs.nth(i).click()
                            print(f"  Selected day tab {target_date_str}")
                            await asyncio.sleep(2)
                            found_tab = True
                            break
                    
                    if not found_tab:
                        print(f"  Warning: Tab for {target_date_str} not found.")
                        
                except Exception as e:
                    print(f"Warning: Navigation error: {e}")

            # Ensure data is loaded
            await page.wait_for_selector('app-category', timeout=20000)
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(1)
            await page.evaluate('window.scrollTo(0, 0)')

            # Extract basic info
            menu_data = await page.evaluate('''() => {
                const cats = Array.from(document.querySelectorAll('app-category')).filter(el => el.offsetParent !== null);
                return cats.map(cat => {
                    const categoryName = cat.querySelector('h3.category-header')?.textContent.trim() || 'Unknown';
                    const items = Array.from(cat.querySelectorAll('.product-wrapper')).map(row => {
                        const button = row.querySelector('.name-column button');
                        return { 
                            name: button ? button.textContent.trim() : 'Unknown Dish',
                            price: row.querySelector('.price-column .price')?.textContent.replace(/\\s+/g, ' ').trim() || 'N/A',
                            hasDetails: !!button
                        };
                    });
                    return { categoryName, items };
                });
            }''')

            if fetch_calories:
                flat_items = []
                for cat in menu_data:
                    for it in cat['items']:
                        if it['hasDetails']:
                            flat_items.append(it)
                
                print(f"Extracting calories for {len(flat_items)} items...")
                
                for i in range(len(flat_items)):
                    try:
                        await page.wait_for_selector('.product-wrapper button', timeout=15000)
                        buttons = page.locator('.product-wrapper button')
                        btn = buttons.nth(i)
                        
                        btn_text = await btn.inner_text()
                        name_snip = btn_text.split('\n')[0].strip()
                        print(f"  [{i+1}/{len(flat_items)}] Fetching details for: {name_snip}...")
                        
                        await btn.click(force=True)
                        await page.wait_for_url(re.compile(r'.*/product/.*'), timeout=15000)
                        
                        # Nutritional Tab
                        try:
                            nutri_selector = '.mdc-tab:has-text("NÄHRWERTE"), .mdc-tab:has-text("Nährwerte"), .mdc-tab:has-text("NUTRITIONAL")'
                            await page.wait_for_selector(nutri_selector, timeout=7000)
                            await page.click(nutri_selector, force=True)
                            await asyncio.sleep(1)
                        except: pass
                        
                        nutrients_raw = await page.evaluate('''() => {
                            const rows = Array.from(document.querySelectorAll('table tr'));
                            const data = {};
                            let lastLabel = '';
                            rows.forEach(row => {
                                const cells = Array.from(row.querySelectorAll('td'));
                                if (cells.length >= 2) {
                                    let label = cells[0].textContent.trim().toLowerCase();
                                    if (!label && lastLabel) label = lastLabel;
                                    else if (label) lastLabel = label;
                                    if (label) {
                                        data[label] = (data[label] || '') + ' ' + cells[cells.length - 1].textContent.trim();
                                    }
                                }
                            });
                            return data;
                        }''')
                        
                        item = flat_items[i]
                        item['nutrients'] = {}
                        for label, val in nutrients_raw.items():
                            if any(x in label for x in ['kcal', 'brennwert', 'energy', 'energie']):
                                m = re.search(r'([\d.,]+)\s*kcal', val.lower())
                                if m: 
                                    item['calories'] = int(m.group(1).replace('.','').replace(',',''))
                                    item['nutrients']['energy_kcal'] = val
                                m_kj = re.search(r'([\d.,]+)\s*kj', val.lower())
                                if m_kj: item['nutrients']['energy_kj'] = val
                            elif any(x in label for x in ['fett', 'fat']):
                                if 'gesätt' not in label and 'saturates' not in label: item['nutrients']['fat'] = val
                            elif any(x in label for x in ['eiweiß', 'protein']): item['nutrients']['protein'] = val
                            elif any(x in label for x in ['kohlenhydrate', 'carbohydrate']):
                                if 'zucker' not in label and 'sugars' not in label: item['nutrients']['carbs'] = val
                            elif any(x in label for x in ['salz', 'salt']): item['nutrients']['salt'] = val
                        
                        back_btn = page.locator('app-back-button button')
                        if await back_btn.count() > 0:
                            await back_btn.click()
                        else:
                            await page.go_back(wait_until="load")
                        
                        await page.wait_for_selector('app-category', timeout=15000)
                        await asyncio.sleep(1)
                    except Exception as e:
                        print(f"    Error processing item {i+1}: {e}")
                        if "/product/" in page.url:
                            await page.goto(url)
                            # Re-select week/day...
                            try:
                                await page.evaluate('(kw) => { ... }', target_kw) # simplified for re-run
                            except: pass
                        await asyncio.sleep(1)

            translator = GoogleTranslator(source='auto', target='ru')
            for category in menu_data:
                if category['categoryName']:
                    try: category['categoryName_ru'] = translator.translate(category['categoryName'])
                    except: category['categoryName_ru'] = ""
                for item in category['items']:
                    if item['name']:
                        try: item['name_ru'] = translator.translate(item['name'])
                        except: item['name_ru'] = ""
            return menu_data
        finally:
            await browser.close()

def format_menu(menu_data, telegram=False):
    if not menu_data: return "No menu data found."
    lines = []
    lines.append("<b>🍽 SODEXO MENU - BERLIN OSA</b>\n")
    for category in menu_data:
        cat_name = category['categoryName'].upper()
        if category.get('categoryName_ru'): cat_name += f" ({category['categoryName_ru'].upper()})"
        lines.append(f"<b>━━━ {cat_name} ━━━</b>")
        for item in category['items']:
            name = item['name'].replace('<', '&lt;').replace('>', '&gt;')
            cal = item.get('calories', '')
            cal_str = f" | ⚡ {cal} kcal" if cal else ""
            lines.append(f"• <b>{name}</b>{cal_str}")
            if item.get('name_ru'): lines.append(f"  └ <i>{item['name_ru']}</i>")
            n = item.get('nutrients', {})
            nutri_list = []
            if n.get('fat'): nutri_list.append(f"🥩 Fat: {n['fat']}")
            if n.get('carbs'): nutri_list.append(f"🍞 Carbs: {n['carbs']}")
            if n.get('protein'): nutri_list.append(f"💪 Protein: {n['protein']}")
            if n.get('salt'): nutri_list.append(f"🧂 Salt: {n['salt']}")
            lines.append(f"  💰 {item['price']}")
            if nutri_list: lines.append(f"  <i>{' | '.join(nutri_list)}</i>")
        lines.append("")
    return "\n".join(lines)

DEFAULT_URL = "https://de.everyday.sodexo.com/menu/Deutsche%20Bank%20Berlin%20OSA/Speiseplan%20Deutsche%20Bank"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, default=None)
    parser.add_argument('--no-calories', action='store_false', dest='calories', default=True)
    parser.add_argument('--telegram', action='store_true')
    args = parser.parse_args()
    try:
        menu_data = asyncio.run(get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=args.date, fetch_calories=args.calories))
        print(format_menu(menu_data, telegram=args.telegram))
    except Exception as e: print(f"Error: {e}")

if __name__ == "__main__":
    main()
