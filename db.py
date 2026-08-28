import asyncpg
from datetime import datetime, timezone
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','vendor','rider')),
    name TEXT,
    username TEXT,
    phone TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    suspended BOOLEAN NOT NULL DEFAULT FALSE,
    online BOOLEAN NOT NULL DEFAULT FALSE,
    busy BOOLEAN NOT NULL DEFAULT FALSE,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS delivery_requests (
    id BIGSERIAL PRIMARY KEY,
    vendor_id BIGINT NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('normal','broadcast')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','accepted','completed','cancelled','unassigned')),
    accepted_rider_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assignments (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES delivery_requests(id) ON DELETE CASCADE,
    rider_id BIGINT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('pending','accepted','rejected','expired','rerouted','completed')),
    telegram_message_id BIGINT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(request_id, rider_id)
);

CREATE INDEX IF NOT EXISTS idx_users_riders
    ON users(role, active, suspended, online, busy);

CREATE INDEX IF NOT EXISTS idx_assignments_expiry
    ON assignments(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_assignments_request
    ON assignments(request_id, status);
"""

async def create_pool(database_url: str):
    return await asyncpg.create_pool(database_url, min_size=1, max_size=5)

async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)

async def upsert_user(pool, telegram_id: int, role: str, name: str = None, username: str = None):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (telegram_id, role, name, username)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (telegram_id)
            DO UPDATE SET name=COALESCE(EXCLUDED.name, users.name),
                          username=COALESCE(EXCLUDED.username, users.username),
                          updated_at=NOW()
            """,
            telegram_id, role, name, username
        )

async def get_user(pool, telegram_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)

async def set_vendor_location(pool, telegram_id: int, lat: float, lon: float):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE users SET latitude=$2, longitude=$3, updated_at=NOW()
            WHERE telegram_id=$1 AND role='vendor'
            RETURNING *
            """, telegram_id, lat, lon
        )

async def set_rider_location(pool, telegram_id: int, lat: float, lon: float):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE users SET latitude=$2, longitude=$3, updated_at=NOW()
            WHERE telegram_id=$1 AND role='rider'
            RETURNING *
            """, telegram_id, lat, lon
        )

async def set_rider_online(pool, telegram_id: int, online: bool):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE users SET online=$2, updated_at=NOW()
            WHERE telegram_id=$1 AND role='rider'
            RETURNING *
            """, telegram_id, online
        )

async def set_rider_busy(pool, telegram_id: int, busy: bool):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE users SET busy=$2, updated_at=NOW()
            WHERE telegram_id=$1 AND role='rider'
            RETURNING *
            """, telegram_id, busy
        )

async def list_users(pool, role: str):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM users WHERE role=$1 ORDER BY created_at DESC", role
        )

async def admin_set_status(pool, telegram_id: int, suspended: bool):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE users SET suspended=$2, updated_at=NOW()
            WHERE telegram_id=$1 AND role IN ('vendor','rider')
            RETURNING *
            """, telegram_id, suspended
        )

async def remove_user(pool, telegram_id: int):
    # Deactivate instead of hard-delete so historical order records stay valid.
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE users
            SET active=FALSE, online=FALSE, busy=FALSE, updated_at=NOW()
            WHERE telegram_id=$1 AND role IN ('vendor','rider')
            RETURNING *
            """, telegram_id
        )

async def create_request(pool, vendor_db_id: int, text: str, kind: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO delivery_requests (vendor_id,text,kind)
            VALUES ($1,$2,$3)
            RETURNING *
            """, vendor_db_id, text, kind
        )

async def get_request(pool, request_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT r.*, v.telegram_id AS vendor_telegram_id,
                   v.latitude AS vendor_latitude, v.longitude AS vendor_longitude
            FROM delivery_requests r
            JOIN users v ON v.id=r.vendor_id
            WHERE r.id=$1
            """, request_id
        )

async def eligible_riders(pool, exclude_ids=None):
    exclude_ids = exclude_ids or []
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT * FROM users
            WHERE role='rider'
              AND active=TRUE
              AND suspended=FALSE
              AND online=TRUE
              AND busy=FALSE
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
              AND telegram_id <> ALL($1::BIGINT[])
            """,
            exclude_ids
        )

async def tried_rider_ids(pool, request_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT rider_id FROM assignments WHERE request_id=$1", request_id
        )
        return [r["rider_id"] for r in rows]

async def create_assignment(pool, request_id: int, rider_db_id: int, expires_at: datetime):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO assignments(request_id,rider_id,status,expires_at)
            VALUES($1,$2,'pending',$3)
            ON CONFLICT(request_id,rider_id) DO NOTHING
            RETURNING *
            """, request_id, rider_db_id, expires_at
        )

async def set_assignment_message(pool, assignment_id: int, message_id: int):
    async with pool.acquire() as conn:
        return await conn.execute(
            "UPDATE assignments SET telegram_message_id=$2,updated_at=NOW() WHERE id=$1",
            assignment_id, message_id
        )

async def get_assignment(pool, assignment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT a.*, r.text AS request_text, r.kind AS request_kind,
                   r.status AS request_status, r.vendor_id,
                   u.telegram_id AS rider_telegram_id,
                   v.telegram_id AS vendor_telegram_id
            FROM assignments a
            JOIN delivery_requests r ON r.id=a.request_id
            JOIN users u ON u.id=a.rider_id
            JOIN users v ON v.id=r.vendor_id
            WHERE a.id=$1
            """, assignment_id
        )

async def accept_assignment(pool, assignment_id: int, rider_telegram_id: int):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT a.*, r.status AS request_status, r.accepted_rider_id,
                       u.id AS rider_db_id, u.busy
                FROM assignments a
                JOIN delivery_requests r ON r.id=a.request_id
                JOIN users u ON u.id=a.rider_id
                WHERE a.id=$1 AND u.telegram_id=$2
                FOR UPDATE OF a, r, u
                """, assignment_id, rider_telegram_id
            )
            if not row or row["status"] != "pending" or row["request_status"] != "open":
                return None
            if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
                await conn.execute(
                    "UPDATE assignments SET status='expired',updated_at=NOW() WHERE id=$1",
                    assignment_id
                )
                return None
            await conn.execute(
                "UPDATE assignments SET status='accepted',updated_at=NOW() WHERE id=$1",
                assignment_id
            )
            await conn.execute(
                """
                UPDATE delivery_requests
                SET status='accepted', accepted_rider_id=$2, updated_at=NOW()
                WHERE id=$1
                """, row["request_id"], row["rider_db_id"]
            )
            await conn.execute(
                "UPDATE users SET busy=TRUE, updated_at=NOW() WHERE id=$1",
                row["rider_db_id"]
            )
            await conn.execute(
                """
                UPDATE assignments
                SET status='rerouted',updated_at=NOW()
                WHERE request_id=$1 AND status='pending' AND id<>$2
                """, row["request_id"], assignment_id
            )
            return await conn.fetchrow(
                """
                SELECT a.*, r.text AS request_text,
                       r.vendor_id, v.telegram_id AS vendor_telegram_id,
                       u.telegram_id AS rider_telegram_id
                FROM assignments a
                JOIN delivery_requests r ON r.id=a.request_id
                JOIN users u ON u.id=a.rider_id
                JOIN users v ON v.id=r.vendor_id
                WHERE a.id=$1
                """, assignment_id
            )

async def reject_assignment(pool, assignment_id: int, rider_telegram_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE assignments a SET status='rejected',updated_at=NOW()
            FROM users u
            WHERE a.id=$1 AND a.rider_id=u.id AND u.telegram_id=$2
              AND a.status='pending'
            RETURNING a.*
            """, assignment_id, rider_telegram_id
        )
        return row

async def mark_assignment_expired(pool, assignment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE assignments SET status='expired',updated_at=NOW()
            WHERE id=$1 AND status='pending'
            RETURNING *
            """, assignment_id
        )

async def pending_expired_assignments(pool):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT a.*, r.status AS request_status
            FROM assignments a
            JOIN delivery_requests r ON r.id=a.request_id
            WHERE a.status='pending'
              AND a.expires_at IS NOT NULL
              AND a.expires_at <= NOW()
              AND r.status='open'
            ORDER BY a.expires_at
            """
        )

async def complete_request(pool, request_id: int, rider_telegram_id: int):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT r.*, u.id AS rider_db_id
                FROM delivery_requests r
                JOIN users u ON u.telegram_id=$2
                WHERE r.id=$1 AND r.status='accepted'
                  AND r.accepted_rider_id=u.id
                FOR UPDATE OF r,u
                """, request_id, rider_telegram_id
            )
            if not row:
                return None
            await conn.execute(
                "UPDATE delivery_requests SET status='completed',updated_at=NOW() WHERE id=$1",
                request_id
            )
            await conn.execute(
                """
                UPDATE assignments SET status='completed',updated_at=NOW()
                WHERE request_id=$1 AND status='accepted'
                """, request_id
            )
            await conn.execute(
                "UPDATE users SET busy=FALSE,updated_at=NOW() WHERE id=$1",
                row["rider_db_id"]
            )
            return row

async def cancel_request(pool, request_id: int, vendor_telegram_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            UPDATE delivery_requests r
            SET status='cancelled',updated_at=NOW()
            FROM users v
            WHERE r.id=$1 AND r.vendor_id=v.id
              AND v.telegram_id=$2 AND r.status='open'
            RETURNING r.*
            """, request_id, vendor_telegram_id
        )

async def get_open_request_for_rider(pool, rider_telegram_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT r.*, a.id AS assignment_id
            FROM delivery_requests r
            JOIN assignments a ON a.request_id=r.id
            JOIN users u ON u.id=a.rider_id
            WHERE u.telegram_id=$1
              AND a.status='accepted'
              AND r.status='accepted'
            ORDER BY r.updated_at DESC
            LIMIT 1
            """, rider_telegram_id
        )

async def broadcast_riders(pool):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT * FROM users
            WHERE role='rider'
              AND active=TRUE
              AND suspended=FALSE
              AND online=TRUE
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
            """
        )
