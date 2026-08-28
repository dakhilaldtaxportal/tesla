import asyncio
import logging
import re

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardRemove
)

import db
import keyboards as kb
import services
from config import load_settings
from states import AdminStates, VendorStates, RiderStates

logging.basicConfig(level=logging.INFO)
settings = load_settings()

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

app = FastAPI(title="Riders Group Bot")
pool = None
expiry_task = None

def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids

async def get_registered(message: Message):
    return await db.get_user(pool, message.from_user.id)

async def send_main_menu(message: Message, user):
    if not user:
        await message.answer("Your Telegram ID is not registered yet. Please contact the admin.")
        return
    if user["suspended"]:
        await message.answer("⛔ Your account is suspended. Please contact the admin.")
        return
    if user["role"] == "rider":
        await message.answer("Rider panel:", reply_markup=kb.rider_menu())
    elif user["role"] == "vendor":
        await message.answer("Vendor panel:", reply_markup=kb.vendor_menu())
    elif user["role"] == "admin":
        await message.answer("Admin panel:", reply_markup=kb.admin_menu())

@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await db.upsert_user(
            pool, message.from_user.id, "admin",
            message.from_user.full_name, message.from_user.username
        )
    user = await get_registered(message)
    await send_main_menu(message, user)

# ---------------- ADMIN ----------------

@router.message(Command("add_vendor"))
async def add_vendor(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /add_vendor TELEGRAM_ID")
        return
    tid = int(parts[1])
    await db.upsert_user(pool, tid, "vendor")
    await state.set_state(AdminStates.waiting_vendor_location)
    await state.update_data(target_id=tid)
    await message.answer(
        f"Vendor <code>{tid}</code> registered.\nNow send the vendor's fixed location.",
        reply_markup=kb.location_keyboard()
    )

@router.message(AdminStates.waiting_vendor_location, F.location)
async def save_vendor_location(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target_id = data["target_id"]
    row = await db.set_vendor_location(
        pool, target_id, message.location.latitude, message.location.longitude
    )
    await state.clear()
    if row:
        await message.answer(
            f"✅ Vendor <code>{target_id}</code> location saved and fixed.",
            reply_markup=ReplyKeyboardRemove()
        )
        try:
            await bot.send_message(target_id, "✅ You have been registered as a vendor.")
        except Exception:
            pass
    else:
        await message.answer("Could not save vendor location.")

@router.message(Command("add_rider"))
async def add_rider(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /add_rider TELEGRAM_ID")
        return
    tid = int(parts[1])
    await db.upsert_user(pool, tid, "rider")
    await message.answer(f"✅ Rider <code>{tid}</code> registered.")
    try:
        await bot.send_message(
            tid,
            "✅ You have been registered as a rider. Open the bot and press 🟢 Online, then share your current location."
        )
    except Exception:
        pass

@router.message(Command("vendors"))
async def vendors(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = await db.list_users(pool, "vendor")
    if not rows:
        await message.answer("No vendors.")
        return
    lines = ["<b>Vendors</b>"]
    for x in rows:
        status = "SUSPENDED" if x["suspended"] else "ACTIVE"
        loc = "location set" if x["latitude"] is not None else "NO LOCATION"
        lines.append(f"• <code>{x['telegram_id']}</code> — {status} — {loc}")
    await message.answer("\n".join(lines))

@router.message(Command("riders"))
async def riders(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = await db.list_users(pool, "rider")
    if not rows:
        await message.answer("No riders.")
        return
    lines = ["<b>Riders</b>"]
    for x in rows:
        status = "SUSPENDED" if x["suspended"] else "ACTIVE"
        mode = "ONLINE" if x["online"] else "OFFLINE"
        busy = "BUSY" if x["busy"] else "FREE"
        loc = "location set" if x["latitude"] is not None else "NO LOCATION"
        lines.append(f"• <code>{x['telegram_id']}</code> — {status} — {mode} — {busy} — {loc}")
    await message.answer("\n".join(lines))

@router.message(Command("suspend"))
async def suspend(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /suspend TELEGRAM_ID")
        return
    row = await db.admin_set_status(pool, int(parts[1]), True)
    await message.answer("✅ Suspended." if row else "User not found.")

@router.message(Command("unsuspend"))
async def unsuspend(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /unsuspend TELEGRAM_ID")
        return
    row = await db.admin_set_status(pool, int(parts[1]), False)
    await message.answer("✅ Suspension removed." if row else "User not found.")

@router.message(Command("remove"))
async def remove(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /remove TELEGRAM_ID")
        return
    row = await db.remove_user(pool, int(parts[1]))
    await message.answer("✅ Removed." if row else "User not found.")

@router.message(Command("message"))
async def admin_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
        await message.answer("Usage: /message TELEGRAM_ID your text")
        return
    tid, text = int(parts[1]), parts[2]
    try:
        await bot.send_message(tid, f"📩 <b>Admin message</b>\n\n{text}")
        await message.answer("✅ Message sent.")
    except Exception as e:
        await message.answer(f"❌ Could not send: {e}")

@router.message(Command("admin"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>Admin commands</b>\n"
        "/add_vendor ID — register vendor, then send fixed location\n"
        "/add_rider ID — register rider\n"
        "/vendors — list vendors\n"
        "/riders — list riders\n"
        "/suspend ID — suspend\n"
        "/unsuspend ID — unsuspend\n"
        "/remove ID — remove\n"
        "/message ID text — personal inbox message"
    )

# ---------------- RIDER ----------------

@router.message(F.text == "🟢 Online")
async def rider_online(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "rider":
        return await message.answer("You are not registered as a rider.")
    if user["suspended"]:
        return await message.answer("⛔ Your rider account is suspended.")
    if user["latitude"] is None:
        await state.set_state(RiderStates.waiting_location)
        return await message.answer("Please share your current location first.", reply_markup=kb.location_keyboard())
    await db.set_rider_online(pool, message.from_user.id, True)
    await message.answer("🟢 You are ONLINE and can receive delivery requests.", reply_markup=kb.rider_menu())

@router.message(F.text == "🔴 Offline")
async def rider_offline(message: Message):
    user = await get_registered(message)
    if not user or user["role"] != "rider":
        return
    if user["busy"]:
        return await message.answer("You have an active order. Complete or send it to another rider first.")
    await db.set_rider_online(pool, message.from_user.id, False)
    await message.answer("🔴 You are OFFLINE.", reply_markup=kb.rider_menu())

@router.message(F.text == "📍 Update Location")
async def rider_update_location(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "rider":
        return
    await state.set_state(RiderStates.waiting_location)
    await message.answer("Share your current location.", reply_markup=kb.location_keyboard())

@router.message(RiderStates.waiting_location, F.location)
async def rider_location(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "rider":
        await state.clear()
        return
    await db.set_rider_location(
        pool, message.from_user.id,
        message.location.latitude, message.location.longitude
    )
    await state.clear()
    if not user["online"]:
        await db.set_rider_online(pool, message.from_user.id, True)
        await message.answer("📍 Location saved. 🟢 You are now ONLINE.", reply_markup=kb.rider_menu())
    else:
        await message.answer("📍 Location updated.", reply_markup=kb.rider_menu())

@router.message(F.text == "📊 Status")
async def rider_status(message: Message):
    user = await get_registered(message)
    if not user or user["role"] != "rider":
        return
    mode = "ONLINE" if user["online"] else "OFFLINE"
    busy = "BUSY" if user["busy"] else "FREE"
    await message.answer(f"Mode: <b>{mode}</b>\nOrder status: <b>{busy}</b>")

# ---------------- VENDOR ----------------

@router.message(F.text == "🚚 Delivery Request")
async def vendor_delivery(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "vendor":
        return
    if user["suspended"]:
        return await message.answer("⛔ Your vendor account is suspended.")
    if user["latitude"] is None:
        return await message.answer("Your vendor location has not been configured. Contact admin.")
    await state.set_state(VendorStates.waiting_delivery_text)
    await message.answer("Send the delivery details/text now. The bot will find the nearest available rider.")

@router.message(VendorStates.waiting_delivery_text, F.text)
async def vendor_delivery_text(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "vendor":
        await state.clear()
        return
    req = await db.create_request(pool, user["id"], message.text, "normal")
    await state.clear()
    await message.answer(f"📦 Request #{req['id']} created.")
    await services.send_to_next_rider(
        bot, pool, req["id"], settings.claim_timeout_seconds, settings.normal_radius_km
    )

@router.message(F.text == "📢 Broadcast")
async def vendor_broadcast(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "vendor":
        return
    if user["suspended"]:
        return await message.answer("⛔ Your vendor account is suspended.")
    await state.set_state(VendorStates.waiting_broadcast_text)
    await message.answer(
        f"Send broadcast text. It will be shown to eligible online riders within {settings.broadcast_radius_km:g} km."
    )

@router.message(VendorStates.waiting_broadcast_text, F.text)
async def vendor_broadcast_text(message: Message, state: FSMContext):
    user = await get_registered(message)
    if not user or user["role"] != "vendor":
        await state.clear()
        return
    req = await db.create_request(pool, user["id"], message.text, "broadcast")
    await state.clear()
    sent = await services.broadcast_request(bot, pool, req["id"], settings.broadcast_radius_km)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE delivery_requests SET status='unassigned',updated_at=NOW() WHERE id=$1",
            req["id"]
        )
    await message.answer(f"📢 Broadcast #{req['id']} sent to {sent} nearby rider(s).")

# ---------------- CALLBACKS ----------------

@router.callback_query(F.data.startswith("claim:"))
async def claim_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    action, assignment_id = parts[1], int(parts[2])
    await callback.answer()
    user = await db.get_user(pool, callback.from_user.id)
    if not user or user["role"] != "rider":
        return
    if action == "accept":
        result = await db.accept_assignment(pool, assignment_id, callback.from_user.id)
        if not result:
            try:
                await callback.message.edit_text("⏱️ This request is no longer available.")
            except Exception:
                pass
            return
        try:
            await callback.message.edit_text(
                f"✅ <b>Accepted</b>\n\n{result['request_text']}",
                reply_markup=kb.active_order_keyboard(result["request_id"])
            )
        except Exception:
            pass
        try:
            await bot.send_message(
                result["vendor_telegram_id"],
                f"✅ Rider accepted request #{result['request_id']}."
            )
        except Exception:
            pass
    else:
        result = await db.reject_assignment(pool, assignment_id, callback.from_user.id)
        if not result:
            return
        try:
            await callback.message.delete()
        except Exception:
            pass
        await services.reroute_request(
            bot, pool, result["request_id"],
            settings.claim_timeout_seconds, settings.normal_radius_km
        )

@router.callback_query(F.data.startswith("order:"))
async def order_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    action, request_id = parts[1], int(parts[2])
    await callback.answer()
    user = await db.get_user(pool, callback.from_user.id)
    if not user or user["role"] != "rider":
        return
    if action == "complete":
        result = await db.complete_request(pool, request_id, callback.from_user.id)
        if not result:
            return await callback.message.answer("This order is no longer active.")
        try:
            await callback.message.edit_text("✅ Order completed.")
        except Exception:
            pass
        try:
            await bot.send_message(result["vendor_telegram_id"], f"✅ Request #{request_id} completed.")
        except Exception:
            pass
    elif action == "reroute":
        ok = await services.rider_send_to_others(
            bot, pool, request_id, callback.from_user.id,
            settings.claim_timeout_seconds, settings.normal_radius_km
        )
        if ok:
            try:
                await callback.message.edit_text("🔁 Request sent back to the rider queue.")
            except Exception:
                pass
        else:
            await callback.message.answer("This order is no longer active.")

@router.callback_query(F.data.startswith("vendor:cancel:"))
async def vendor_cancel(callback: CallbackQuery):
    request_id = int(callback.data.split(":")[2])
    await callback.answer()
    user = await db.get_user(pool, callback.from_user.id)
    if not user or user["role"] != "vendor":
        return
    row = await db.cancel_request(pool, request_id, callback.from_user.id)
    if row:
        await callback.message.edit_text(f"❌ Request #{request_id} cancelled.")
    else:
        await callback.message.answer("This request cannot be cancelled now.")

@router.callback_query(F.data == "admin:help")
async def admin_help_button(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer()
    await callback.message.answer(
        "Use /admin for the complete admin command list."
    )

@router.callback_query(F.data.startswith("admin:list:"))
async def admin_list_button(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer()
    role = "vendor" if callback.data.endswith("vendor") else "rider"
    rows = await db.list_users(pool, role)
    if not rows:
        return await callback.message.answer("No users.")
    lines = [f"<b>{role.title()}s</b>"]
    for x in rows[:100]:
        status = "SUSPENDED" if x["suspended"] else "ACTIVE"
        mode = ""
        if role == "rider":
            mode = f" — {'ONLINE' if x['online'] else 'OFFLINE'} — {'BUSY' if x['busy'] else 'FREE'}"
        lines.append(f"• <code>{x['telegram_id']}</code> — {status}{mode}")
    await callback.message.answer("\n".join(lines))

# ---------------- GENERAL ----------------

@router.message()
async def unknown_message(message: Message):
    user = await get_registered(message)
    if not user:
        return
    if user["role"] == "admin":
        await message.answer("Use /admin for admin commands.", reply_markup=kb.admin_menu())
    elif user["role"] == "rider":
        await message.answer("Use the rider buttons.", reply_markup=kb.rider_menu())
    elif user["role"] == "vendor":
        await message.answer("Use the vendor buttons.", reply_markup=kb.vendor_menu())

async def expiry_loop():
    while True:
        try:
            await services.process_expired(
                bot, pool, settings.claim_timeout_seconds, settings.normal_radius_km
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("expiry loop failed")
        await asyncio.sleep(5)

@app.on_event("startup")
async def startup():
    global pool, expiry_task
    pool = await db.create_pool(settings.database_url)
    await db.init_db(pool)
    await bot.set_webhook(
        url=f"{settings.webhook_url}/telegram/webhook",
        secret_token=settings.webhook_secret,
        allowed_updates=["message", "callback_query"]
    )
    expiry_task = asyncio.create_task(expiry_loop())
    logging.info("Bot started")

@app.on_event("shutdown")
async def shutdown():
    global expiry_task, pool
    if expiry_task:
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    if pool:
        await pool.close()
    await bot.session.close()

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    # Check expired claims on every incoming update too, which helps after a cold start.
    try:
        await services.process_expired(
            bot, pool, settings.claim_timeout_seconds, settings.normal_radius_km
        )
    except Exception:
        logging.exception("expiry check failed")
    data = await request.json()
    from aiogram.types import Update
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return JSONResponse({"ok": True})
