from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)

def rider_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Online"), KeyboardButton(text="🔴 Offline")],
            [KeyboardButton(text="📍 Update Location"), KeyboardButton(text="📊 Status")],
        ],
        resize_keyboard=True
    )

def location_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Share Current Location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def vendor_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚚 Delivery Request")],
            [KeyboardButton(text="📢 Broadcast")],
        ],
        resize_keyboard=True
    )

def claim_keyboard(assignment_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Accept", callback_data=f"claim:accept:{assignment_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"claim:reject:{assignment_id}"),
        ]
    ])

def active_order_keyboard(request_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔁 Send to Others", callback_data=f"order:reroute:{request_id}"),
            InlineKeyboardButton(text="✅ Complete", callback_data=f"order:complete:{request_id}"),
        ]
    ])

def vendor_cancel_keyboard(request_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Request", callback_data=f"vendor:cancel:{request_id}")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Vendors", callback_data="admin:list:vendor"),
         InlineKeyboardButton(text="🏍 Riders", callback_data="admin:list:rider")],
        [InlineKeyboardButton(text="ℹ️ Help", callback_data="admin:help")],
    ])
