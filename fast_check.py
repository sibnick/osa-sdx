#!/usr/bin/env python3
import asyncio
import sys
import datetime
from menu_app import get_sodexo_menu, format_menu, DEFAULT_URL

async def fast_check(target_date=None):
    """
    Quickly fetch and display the Sodexo menu for a specific date (default: today)
    including a total calorie count for all items.
    """
    if not target_date:
        target_date = datetime.datetime.now().strftime("%d.%m")
    
    print(f"--- Fast Check: Sodexo Menu for {target_date} ---")
    try:
        # Fetch menu data with calories enabled
        menu_data = await get_sodexo_menu(DEFAULT_URL, headless=True, target_date_str=target_date, fetch_calories=True)
        
        # Print the formatted menu
        print(format_menu(menu_data, telegram=False))
        
        # Calculate total calories
        total_calories = 0
        items_with_calories = 0
        
        for category in menu_data:
            for item in category['items']:
                cal = item.get('calories')
                if isinstance(cal, int):
                    total_calories += cal
                    items_with_calories += 1
                elif isinstance(cal, str) and cal.isdigit():
                    total_calories += int(cal)
                    items_with_calories += 1

        print("-" * 60)
        print(f"📊 SUMMARY FOR {target_date}:")
        print(f"🔥 Total items with calorie data: {items_with_calories}")
        print(f"🍛 Total calories for ALL items: {total_calories} kcal")
        print("-" * 60)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(fast_check(date_arg))
