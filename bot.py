import os
import asyncio
import logging
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

try:
    import newrelic.agent
    newrelic.agent.initialize()
except ImportError:
    newrelic = None

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
    
    total_calories = 0
    item_idx = 0
    for category in menu_data:
        cat_name = category['categoryName'].upper()
        if category.get('categoryName_ru'):
            cat_name += f" ({category['categoryName_ru'].upper()})"
        lines.append(f"<b>━━━ {cat_name} ━━━</b>")
        
        for item in category['items']:
            is_selected = item_idx in selections
            name = item['name'].replace('<', '&lt;').replace('>', '&gt;')
            price = item['price'].replace('<', '&lt;').replace('>', '&gt;')
            cal = item.get('calories')
            
            if is_selected:
                total_calories += int(cal) if isinstance(cal, int) else 0
                prefix = "✅ "
            else:
                prefix = "• "
                
            cal_str = f" | ⚡ {cal} kcal" if cal else ""
            lines.append(f"{prefix}<b>{name}</b>")
            lines.append(f"  💰 {price}{cal_str}")
            item_idx += 1
        lines.append("")
        
    if selections:
        lines.append("<b>📊 NUTRITIONAL SUMMARY</b>")
        lines.append(f"🔥 Total Calories: <b>{total_calories} kcal</b>")
        lines.append("")
        
    lines.append("<i>Click items below to select them and calculate total calories.</i>")
    return "\n".join(lines)

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
        # Use edit_text only if content changed to avoid flicker (though selections always change it)
        try:
            await callback.message.edit_text(text, reply_markup=get_menu_keyboard(date_str, menu_data, user_id), parse_mode="HTML")
        except Exception:
            pass # Message is not modified
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

@dp.message(F.text.regexp(r"\d{2}\.\d{2}"))
@instrument_task
async def process_text_date(message: types.Message):
    await message.answer("Please use the interactive menu to select items and calculate calories.", reply_markup=get_date_keyboard())

async def main():
    print("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
