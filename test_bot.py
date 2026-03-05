import pytest
from unittest.mock import AsyncMock, patch
from menu_app import format_menu

def test_format_menu_empty():
    assert format_menu([], telegram=True) == "No menu data found."
    assert format_menu([], telegram=False) == "No menu data found."

def test_format_menu_content():
    menu_data = [
        {
            "categoryName": "Main Dish",
            "categoryName_ru": "Основное блюдо",
            "items": [
                {"name": "Pasta", "name_ru": "Паста", "price": "5.00 €"}
            ]
        }
    ]
    
    formatted_tg = format_menu(menu_data, telegram=True)
    assert "Main Dish" in formatted_tg
    assert "ОСНОВНОЕ БЛЮДО" in formatted_tg
    assert "Pasta" in formatted_tg
    assert "Паста" in formatted_tg
    assert "5.00 €" in formatted_tg

    formatted_cli = format_menu(menu_data, telegram=False)
    assert "Main Dish" in formatted_cli
    assert "Pasta" in formatted_cli

@pytest.mark.asyncio
async def test_bot_start_command():
    from bot import cmd_start
    message = AsyncMock()
    await cmd_start(message)
    message.answer.assert_called_once()
    args, kwargs = message.answer.call_args
    assert "Welcome" in args[0]
    assert "reply_markup" in kwargs

@pytest.mark.asyncio
async def test_bot_menu_command():
    from bot import cmd_menu
    message = AsyncMock()
    await cmd_menu(message)
    message.answer.assert_called_once()
    args, kwargs = message.answer.call_args
    assert "Select a date" in args[0]
    assert "reply_markup" in kwargs
