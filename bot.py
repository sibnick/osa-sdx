import os
import asyncio
import logging
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from menu_app import get_sodexo_menu, format_menu, DEFAULT_URL

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    logging.warning("TELEGRAM_BOT_TOKEN not found in environment variables!")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Simple in-memory cache: { "DD.MM": "Formatted Menu String" }
menu_cache = {}

def get_date_keyboard():
    builder = InlineKeyboardBuilder()
    now = datetime.datetime.now()
    
    # Show next 5 working days (excluding weekends)
    days_added = 0
    delta = 0
    while days_added < 5:
        target_date = now + datetime.timedelta(days=delta)
        # weekday() returns 0 for Monday, 5 for Saturday, 6 for Sunday
        if target_date.weekday() < 5:
            date_str = target_date.strftime("%d.%m")
            day_name = target_date.strftime("%A")
            builder.button(text=f"{day_name} ({date_str})", callback_data=f"menu_{date_str}")
            days_added += 1
        delta += 1
    
    builder.adjust(1)
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Welcome! I am the Sodexo Menu Bot for the Berlin office.\n"
        "Click the button below to see the menu for a specific date.",
        reply_markup=get_date_keyboard()
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer("Select a date:", reply_markup=get_date_keyboard())

@dp.callback_query(F.data.startswith("menu_"))
async def process_menu_callback(callback: types.CallbackQuery):
    date_str = callback.data.split("_")[1]
    
    # Check cache first
    if date_str in menu_cache:
        logging.info(f"Cache hit for {date_str}")
        await callback.answer()
        header = f"🗓 <b>MENU FOR {date_str} (Cached)</b>\n\n"
        await callback.message.edit_text(header + menu_cache[date_str], parse_mode="HTML")
        await callback.message.answer("Select another date?", reply_markup=get_date_keyboard())
        return

    await callback.answer(f"Fetching menu for {date_str}...")
    await callback.message.edit_text(f"⏳ Fetching Sodexo menu for {date_str}, please wait...")
    
    try:
        menu_data = await get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=date_str)
        formatted = format_menu(menu_data, telegram=True)
        menu_cache[date_str] = formatted # Store in cache
        
        header = f"🗓 <b>MENU FOR {date_str}</b>\n\n"
        await callback.message.edit_text(header + formatted, parse_mode="HTML")
        await callback.message.answer("Check another date?", reply_markup=get_date_keyboard())
    except Exception as e:
        logging.error(f"Error in callback: {e}")
        await callback.message.edit_text(f"❌ Error fetching menu: {e}")

@dp.message(F.text.regexp(r"\d{2}\.\d{2}"))
async def process_text_date(message: types.Message):
    date_str = message.text.strip()
    
    # Check cache first
    if date_str in menu_cache:
        logging.info(f"Cache hit for {date_str}")
        header = f"🗓 <b>MENU FOR {date_str} (Cached)</b>\n\n"
        await message.answer(header + menu_cache[date_str], parse_mode="HTML")
        await message.answer("Select another date:", reply_markup=get_date_keyboard())
        return

    status_msg = await message.answer(f"⏳ Fetching Sodexo menu for {date_str}, please wait...")
    
    try:
        menu_data = await get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=date_str)
        formatted = format_menu(menu_data, telegram=True)
        menu_cache[date_str] = formatted # Store in cache
        
        header = f"🗓 <b>MENU FOR {date_str}</b>\n\n"
        await status_msg.edit_text(header + formatted, parse_mode="HTML")
        await message.answer("Select another date:", reply_markup=get_date_keyboard())
    except Exception as e:
        logging.error(f"Error in text handler: {e}")
        await status_msg.edit_text(f"❌ Error fetching menu: {e}")

@dp.message()
async def echo_all(message: types.Message):
    await message.answer(
        "I didn't recognize that command. Please use /menu to select a date or send a date in DD.MM format (e.g., 05.03).",
        reply_markup=get_date_keyboard()
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
