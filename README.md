# Riders Group Telegram Bot

Core features:
- Admin registers vendors/riders by Telegram ID.
- Vendor location is saved as a fixed location.
- Riders use Online/Offline mode and share/update their current location.
- Normal request: nearest free online rider within the normal radius gets the request.
- Rider gets Accept/Reject.
- Default timeout is 120 seconds; timeout/reject moves the request to the next nearest rider.
- After Accept, the rider becomes Busy and gets Send to Others / Complete.
- Send to Others releases the rider and re-queues the request.
- Complete releases the rider.
- Broadcast sends to all online riders within the broadcast radius.
- Admin can list, suspend, unsuspend, deactivate/remove, and message users.

## Render Free limitation

This bot uses a Render Web Service + Telegram webhook. Render Free Web Services spin down after 15 minutes without inbound traffic. The 5-second in-process timeout loop therefore stops while the service sleeps. The webhook also checks expired requests whenever a Telegram update wakes the service.

So the 1–2 minute timeout is best-effort on the Free Web Service, not a hard real-time guarantee after a sleep/cold start. For production, use an always-on service or a Background Worker/queue architecture.

Render Free Postgres is also temporary and currently expires after 30 days, so do not use it for permanent production data.

## Local setup

1. Create the bot with BotFather and copy the token.
2. Create PostgreSQL.
3. Copy `.env.example` to `.env` and fill the values.
4. Install: `pip install -r requirements.txt`
5. Run: `uvicorn main:app --host 0.0.0.0 --port 10000`

Webhook delivery needs a public HTTPS URL. Render provides that automatically.

## Render

Use the included `render.yaml`, or create a Web Service manually.

Build command:
`pip install -r requirements.txt`

Start command:
`uvicorn main:app --host 0.0.0.0 --port $PORT`

Environment variables are listed in `.env.example`.

## Admin commands

`/admin`
`/add_vendor TELEGRAM_ID` then send fixed location
`/add_rider TELEGRAM_ID`
`/vendors`
`/riders`
`/suspend TELEGRAM_ID`
`/unsuspend TELEGRAM_ID`
`/remove TELEGRAM_ID`
`/message TELEGRAM_ID your text`

Remove is implemented as deactivation instead of hard deletion so historical orders remain valid.

## Important Telegram detail

A user must open/start the bot at least once before the bot can reliably send them private messages. Registering a Telegram ID alone is not enough for unsolicited bot messages.

The bot uses the latest location shared by each rider. "Online" does not automatically give the bot continuous GPS data; riders need to share/update their location.

## Files

- main.py — FastAPI webhook and Telegram handlers
- db.py — PostgreSQL schema and queries
- services.py — routing, timeout and broadcast logic
- geo.py — distance calculation
- keyboards.py — Telegram keyboards
- states.py — FSM states
- config.py — environment configuration
- render.yaml — Render deployment blueprint
