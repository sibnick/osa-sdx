import os
try:
    import newrelic.agent
    # Initialize agent
    newrelic.agent.initialize()
    # Explicitly enable log forwarding if not set via environment
    settings = newrelic.agent.global_settings()
    if settings.license_key:
        print(f"✅ New Relic Agent initialized for app: {settings.app_name}")
    else:
        print("⚠️ New Relic Agent initialized but NO LICENSE KEY found.")
except ImportError:
    newrelic = None
    print("❌ New Relic library not found.")

import asyncio
import logging
import datetime
import re

def parse_value(val):
    if not val: return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).strip()
    
    # Remove everything except digits, dots, and commas
    s = re.sub(r'[^\d.,]', '', s)
    if not s: return 0.0
    
    # German format: 1.234,56
    # English format: 1,234.56
    
    if '.' in s and ',' in s:
        if s.rfind('.') < s.rfind(','): # German
            s = s.replace('.', '').replace(',', '.')
        else: # English
            s = s.replace(',', '')
    elif ',' in s:
        # If it's something like "1,230" it's ambiguous.
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) == 3:
            # Check if it's likely a decimal (German) or thousand (English)
            # Most nutrients (except kJ) are < 100.
            try:
                val_if_decimal = float(s.replace(',', '.'))
                if val_if_decimal < 100:
                    s = s.replace(',', '.')
                else:
                    s = s.replace(',', '')
            except:
                s = s.replace(',', '.')
        else:
            s = s.replace(',', '.')
    elif '.' in s:
        # If it's something like "1.230" it's ambiguous.
        parts = s.split('.')
        if len(parts) == 2 and len(parts[1]) == 3:
            try:
                val_as_is = float(s)
                if val_as_is > 100: # Likely German thousand 1.230
                    s = s.replace('.', '')
                else: # Likely English decimal 1.230
                    pass
            except:
                pass
    
    try:
        return float(s)
    except:
        return 0.0

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from menu_app import get_sodexo_menu, format_menu, DEFAULT_URL, instrument_task

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    logging.warning("TELEGRAM_BOT_TOKEN not found in environment variables!")

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()

if newrelic:
    from newrelic.agent import NewRelicContextFormatter
    handler.setFormatter(NewRelicContextFormatter())

logger.addHandler(handler)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Caches
menu_cache = {} # { "DD.MM": [menu_data_objects] }
# user_selections: { user_id: { "DD.MM": [selected_item_indices] } }
user_selections = {}

async def pre_load_menus():
    logging.info("Starting background menu pre-load for the next 7 days...")
    now = datetime.datetime.now()
    for i in range(7):
        target_date = now + datetime.timedelta(days=i)
        if target_date.weekday() >= 5: # Skip weekends
            continue
            
        date_str = target_date.strftime("%d.%m")
        if date_str not in menu_cache:
            logging.info(f"Pre-loading menu for {date_str}...")
            try:
                # Use background_task instrumentation if available
                menu_data = await get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=date_str, fetch_calories=True)
                menu_cache[date_str] = menu_data
                logging.info(f"Successfully pre-loaded {date_str}")
                await asyncio.sleep(2) # Be nice to the server
            except Exception as e:
                logging.error(f"Failed to pre-load {date_str}: {e}")
    logging.info("Background menu pre-load finished.")

def get_date_keyboard():
    builder = InlineKeyboardBuilder()
    now = datetime.datetime.now()
    days_added = 0
    delta = 0
    while days_added < 5:
        target_date = now + datetime.timedelta(days=delta)
        if target_date.weekday() < 5:
            date_str = target_date.strftime("%d.%m")
            day_name = target_date.strftime("%A")
            builder.button(text=f"📅 {day_name} ({date_str})", callback_data=f"menu_{date_str}")
            days_added += 1
        delta += 1
    builder.adjust(1)
    return builder.as_markup()

def get_menu_keyboard(date_str, menu_data, user_id):
    builder = InlineKeyboardBuilder()
    selections = user_selections.get(user_id, {}).get(date_str, [])
    
    item_idx = 0
    for category in menu_data:
        for item in category['items']:
            is_selected = item_idx in selections
            check = "✅ " if is_selected else ""
            cal = item.get('calories')
            cal_str = f" ({cal} kcal)" if cal else ""
            
            # Shorten name for button
            btn_text = f"{check}{item['name'][:30]}{cal_str}"
            builder.button(text=btn_text, callback_data=f"select_{date_str}_{item_idx}")
            item_idx += 1
            
    builder.button(text="🔄 Refresh / Clear", callback_data=f"clear_{date_str}")
    builder.button(text="⬅️ Back to Dates", callback_data="back_to_dates")
    builder.adjust(1)
    return builder.as_markup()

def format_menu_with_total(date_str, menu_data, user_id):
    selections = user_selections.get(user_id, {}).get(date_str, [])
    
    lines = []
    lines.append(f"🗓 <b>SODEXO MENU - {date_str}</b>\n")
    
    totals = {'kcal': 0, 'fat': 0.0, 'protein': 0.0, 'carbs': 0.0, 'salt': 0.0}
    item_idx = 0
    for category in menu_data:
        cat_name = category['categoryName'].upper()
        if category.get('categoryName_ru'):
            cat_name += f" ({category['categoryName_ru'].upper()})"
        lines.append(f"<b>{cat_name}</b>")
        
        for item in category['items']:
            is_selected = item_idx in selections
            name = item['name'].replace('<', '&lt;').replace('>', '&gt;')
            price = item['price'].replace('<', '&lt;').replace('>', '&gt;')
            cal = item.get('calories')
            nutri = item.get('nutrients', {})
            
            if is_selected:
                totals['kcal'] += int(cal) if isinstance(cal, (int, str, float)) and str(cal).replace('.0','').isdigit() else 0
                totals['fat'] += parse_value(nutri.get('fat'))
                totals['protein'] += parse_value(nutri.get('protein'))
                totals['carbs'] += parse_value(nutri.get('carbs'))
                totals['salt'] += parse_value(nutri.get('salt'))
                prefix = "✅ "
            else:
                prefix = "• "
                
            cal_str = f" | ⚡ {cal} kcal" if cal else ""
            lines.append(f"{prefix}<b>{name}</b>")
            
            nutri_list = []
            if nutri.get('fat'): nutri_list.append(f"🥩 Fat: {nutri['fat']}")
            if nutri.get('carbs'): nutri_list.append(f"🍞 Carbs: {nutri['carbs']}")
            if nutri.get('protein'): nutri_list.append(f"💪 Protein: {nutri['protein']}")
            if nutri.get('salt'): nutri_list.append(f"🧂 Salt: {nutri['salt']}")
            
            lines.append(f"  💰 {price}{cal_str}")
            if nutri_list:
                lines.append(f"  <i>{' | '.join(nutri_list)}</i>")
            item_idx += 1
        lines.append("")
        
    if selections:
        lines.append("<b>📊 NUTRITIONAL SUMMARY</b>")
        lines.append(f"🔥 Calories: <b>{totals['kcal']} kcal</b>")
        lines.append(f"🥩 Fat: <b>{totals['fat']:.1f}g</b> | 🍞 Carbs: <b>{totals['carbs']:.1f}g</b>")
        lines.append(f"💪 Protein: <b>{totals['protein']:.1f}g</b> | 🧂 Salt: <b>{totals['salt']:.1f}g</b>")
        lines.append("")
        
    lines.append("<i>Click items below to select them and calculate total nutrients.</i>")
    return "\n".join(lines)

@dp.callback_query(F.data == "back_to_dates")
async def process_back_to_dates(callback: types.CallbackQuery):
    await callback.message.edit_text("📅 Select a date:", reply_markup=get_date_keyboard())

@dp.callback_query(F.data.startswith("menu_"))
@instrument_task
async def process_menu_callback(callback: types.CallbackQuery):
    date_str = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    if date_str in menu_cache:
        menu_data = menu_cache[date_str]
        text = format_menu_with_total(date_str, menu_data, user_id)
        await callback.message.edit_text(text, reply_markup=get_menu_keyboard(date_str, menu_data, user_id), parse_mode="HTML")
        return

    await callback.answer(f"Fetching menu for {date_str}...")
    await callback.message.edit_text(f"⏳ <b>Fetching menu for {date_str}...</b>\n<i>This includes extracting calorie data for each item.</i>", parse_mode="HTML")
    
    try:
        menu_data = await get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=date_str, fetch_calories=True)
        menu_cache[date_str] = menu_data
        
        text = format_menu_with_total(date_str, menu_data, user_id)
        await callback.message.edit_text(text, reply_markup=get_menu_keyboard(date_str, menu_data, user_id), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Error: {e}")
        await callback.message.edit_text(f"❌ <b>Error fetching menu:</b>\n{e}", parse_mode="HTML")

@dp.callback_query(F.data.startswith("select_"))
@instrument_task
async def process_item_selection(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    date_str = parts[1]
    item_idx = int(parts[2])
    user_id = callback.from_user.id
    
    if user_id not in user_selections:
        user_selections[user_id] = {}
    if date_str not in user_selections[user_id]:
        user_selections[user_id][date_str] = []
        
    selections = user_selections[user_id][date_str]
    if item_idx in selections:
        selections.remove(item_idx)
    else:
        selections.append(item_idx)
        
    menu_data = menu_cache.get(date_str)
    if menu_data:
        text = format_menu_with_total(date_str, menu_data, user_id)
        try:
            await callback.message.edit_text(text, reply_markup=get_menu_keyboard(date_str, menu_data, user_id), parse_mode="HTML")
        except Exception:
            pass 
    await callback.answer()

@dp.callback_query(F.data.startswith("clear_"))
async def process_clear_selections(callback: types.CallbackQuery):
    date_str = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    if user_id in user_selections and date_str in user_selections[user_id]:
        user_selections[user_id][date_str] = []
        
    menu_data = menu_cache.get(date_str)
    if menu_data:
        text = format_menu_with_total(date_str, menu_data, user_id)
        await callback.message.edit_text(text, reply_markup=get_menu_keyboard(date_str, menu_data, user_id), parse_mode="HTML")
    await callback.answer("Selections cleared.")

@dp.message(Command("start"))
@instrument_task
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Welcome to Sodexo Berlin Menu Bot!</b>\n\n"
        "I can help you check the daily menu and calculate calories.\n"
        "Please select a date to begin:",
        reply_markup=get_date_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("menu"))
@instrument_task
async def cmd_menu(message: types.Message):
    await message.answer("📅 Select a date:", reply_markup=get_date_keyboard())

@dp.message(F.text.regexp(r"\d{2}\.\d{2}"))
@instrument_task
async def process_text_date(message: types.Message):
    await message.answer("Please use the interactive menu to select items and calculate calories.", reply_markup=get_date_keyboard())

async def main():
    print("Bot is starting...")
    
    # Run once at startup in background to fill cache
    asyncio.create_task(pre_load_menus())
    
    # Setup scheduler for daily updates
    scheduler = AsyncIOScheduler()
    scheduler.add_job(pre_load_menus, CronTrigger(hour=6, minute=0))
    scheduler.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
