#!/usr/bin/env python3
import asyncio
import sys
import datetime
from menu_app import get_sodexo_menu, format_menu, DEFAULT_URL

async def fast_check(target_date=None):
    """
    Quickly fetch and display the Sodexo menu for a specific date (default: today).
    """
    if not target_date:
        target_date = datetime.datetime.now().strftime("%d.%m")
    
    print(f"--- Fast Check: Sodexo Menu for {target_date} ---")
    try:
        # Headless mode is faster and cleaner for CLI
        menu_data = await get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=target_date)
        print(format_menu(menu_data, telegram=False))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(fast_check(date_arg))
