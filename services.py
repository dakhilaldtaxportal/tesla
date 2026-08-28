from datetime import datetime, timedelta, timezone
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from geo import distance_km
import db
from keyboards import claim_keyboard

async def choose_nearest_rider(pool, request_id: int, radius_km: float):
    req = await db.get_request(pool, request_id)
    if not req or req["status"] != "open":
        return None
    tried_db_ids = await db.tried_rider_ids(pool, request_id)
    riders = await db.eligible_riders(pool, exclude_ids=tried_db_ids)
    candidates = []
    for rider in riders:
        d = distance_km(
            req["vendor_latitude"], req["vendor_longitude"],
            rider["latitude"], rider["longitude"]
        )
        if d <= radius_km:
            candidates.append((d, rider))
    candidates.sort(key=lambda x: x[0])
    return candidates[0] if candidates else None

async def send_to_next_rider(bot: Bot, pool, request_id: int, timeout_seconds: int, radius_km: float):
    picked = await choose_nearest_rider(pool, request_id, radius_km)
    if not picked:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE delivery_requests SET status='unassigned',updated_at=NOW() WHERE id=$1 AND status='open'",
                request_id
            )
        req = await db.get_request(pool, request_id)
        if req:
            try:
                await bot.send_message(
                    req["vendor_telegram_id"],
                    "⚠️ No available online rider was found within the normal radius."
                )
            except Exception:
                pass
        return None

    distance, rider = picked
    expires = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    assignment = await db.create_assignment(pool, request_id, rider["id"], expires)
    if not assignment:
        return await send_to_next_rider(bot, pool, request_id, timeout_seconds, radius_km)

    req = await db.get_request(pool, request_id)
    text = (
        "🚚 <b>New Delivery Request</b>\n\n"
        f"{req['text']}\n\n"
        f"📍 Distance: <b>{distance:.2f} km</b>\n"
        f"⏳ You have <b>{timeout_seconds} seconds</b> to accept.\n"
        "If you do not respond, the request will move to the next rider."
    )
    try:
        msg = await bot.send_message(
            rider["telegram_id"], text,
            reply_markup=claim_keyboard(assignment["id"]),
            parse_mode="HTML"
        )
        await db.set_assignment_message(pool, assignment["id"], msg.message_id)
    except Exception:
        await db.mark_assignment_expired(pool, assignment["id"])
        return await send_to_next_rider(bot, pool, request_id, timeout_seconds, radius_km)

    try:
        await bot.send_message(
            req["vendor_telegram_id"],
            f"📨 Request #{request_id} sent to the nearest rider ({distance:.2f} km away)."
        )
    except Exception:
        pass
    return assignment

async def reroute_request(bot: Bot, pool, request_id: int, timeout_seconds: int, radius_km: float):
    req = await db.get_request(pool, request_id)
    if not req or req["status"] != "open":
        return None
    return await send_to_next_rider(bot, pool, request_id, timeout_seconds, radius_km)

async def process_expired(bot: Bot, pool, timeout_seconds: int, radius_km: float):
    expired = await db.pending_expired_assignments(pool)
    for assignment in expired:
        changed = await db.mark_assignment_expired(pool, assignment["id"])
        if not changed:
            continue
        try:
            await bot.delete_message(assignment["rider_telegram_id"], assignment["telegram_message_id"])
        except Exception:
            pass
        await reroute_request(bot, pool, assignment["request_id"], timeout_seconds, radius_km)

async def broadcast_request(bot: Bot, pool, request_id: int, radius_km: float):
    req = await db.get_request(pool, request_id)
    if not req:
        return 0
    riders = await db.broadcast_riders(pool)
    sent = 0
    for rider in riders:
        d = distance_km(
            req["vendor_latitude"], req["vendor_longitude"],
            rider["latitude"], rider["longitude"]
        )
        if d <= radius_km:
            try:
                await bot.send_message(
                    rider["telegram_id"],
                    "📢 <b>Broadcast Delivery</b>\n\n"
                    f"{req['text']}\n\n"
                    f"📍 Distance: <b>{d:.2f} km</b>\n"
                    "This is a broadcast. Contact the vendor through your normal process.",
                    parse_mode="HTML"
                )
                sent += 1
            except Exception:
                pass
    return sent

async def rider_send_to_others(bot: Bot, pool, request_id: int, rider_telegram_id: int, timeout_seconds: int, radius_km: float):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT r.*, a.id AS assignment_id, u.id AS rider_db_id
            FROM delivery_requests r
            JOIN assignments a ON a.request_id=r.id AND a.status='accepted'
            JOIN users u ON u.id=r.accepted_rider_id
            WHERE r.id=$1 AND u.telegram_id=$2 AND r.status='accepted'
            """, request_id, rider_telegram_id
        )
        if not row:
            return False
        await conn.execute(
            "UPDATE assignments SET status='rerouted',updated_at=NOW() WHERE id=$1",
            row["assignment_id"]
        )
        await conn.execute(
            "UPDATE delivery_requests SET status='open',accepted_rider_id=NULL,updated_at=NOW() WHERE id=$1",
            request_id
        )
        await conn.execute(
            "UPDATE users SET busy=FALSE,updated_at=NOW() WHERE id=$1",
            row["rider_db_id"]
        )
    await reroute_request(bot, pool, request_id, timeout_seconds, radius_km)
    return True
