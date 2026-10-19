
import sqlite3
from datetime import datetime, timezone

from configuracion.config import DATABASE


def utc_now():
    return datetime.now(timezone.utc)


def to_iso(dt=None):
    return (dt or utc_now()).isoformat()


def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                job_id TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'tracked',
                server_hours REAL NOT NULL DEFAULT 0,
                server_age_seconds REAL,
                server_age_checked_at TEXT
            )
        """)

        columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(servers)"
            ).fetchall()
        }

        migrations = {
            "server_age_seconds": """
                ALTER TABLE servers
                ADD COLUMN server_age_seconds REAL
            """,
            "server_age_checked_at": """
                ALTER TABLE servers
                ADD COLUMN server_age_checked_at TEXT
            """,
            "server_hours": """
                ALTER TABLE servers
                ADD COLUMN server_hours REAL
                NOT NULL DEFAULT 0
            """,
        }

        for name, sql in migrations.items():
            if name not in columns:
                db.execute(sql)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS sent_alerts (
                job_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                cycle_number INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (
                    job_id,
                    event_name,
                    cycle_number
                )
            )
        """)


def get_tracked_servers():
    with sqlite3.connect(DATABASE) as db:
        db.row_factory = sqlite3.Row

        rows = db.execute("""
            SELECT *
            FROM servers
            WHERE status = 'tracked'
        """).fetchall()

    return {
        row["job_id"]: dict(row)
        for row in rows
    }


def upsert_active_servers(servers, now=None):
    now = now or to_iso()

    with sqlite3.connect(DATABASE) as db:
        for job_id in servers:
            db.execute("""
                INSERT INTO servers (
                    job_id,
                    first_seen,
                    last_seen,
                    status,
                    server_hours
                )
                VALUES (?, ?, ?, 'tracked', 0)

                ON CONFLICT(job_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    status = 'tracked'
            """, (job_id, now, now))


def mark_inactive(active_ids):
    active_ids = set(active_ids)

    with sqlite3.connect(DATABASE) as db:
        rows = db.execute("""
            SELECT job_id
            FROM servers
            WHERE status = 'tracked'
        """).fetchall()

        for (job_id,) in rows:
            if job_id not in active_ids:
                db.execute("""
                    UPDATE servers
                    SET status = 'inactive'
                    WHERE job_id = ?
                """, (job_id,))


def save_real_server_age(job_id, age_seconds, checked_at=None):
    checked_at = checked_at or to_iso()

    with sqlite3.connect(DATABASE) as db:
        db.execute("""
            UPDATE servers
            SET server_age_seconds = ?,
                server_age_checked_at = ?,
                server_hours = ?
            WHERE job_id = ?
        """, (
            age_seconds,
            checked_at,
            age_seconds / 3600,
            job_id
        ))


def alert_was_sent(job_id, event_name, cycle_number):
    with sqlite3.connect(DATABASE) as db:
        row = db.execute("""
            SELECT 1
            FROM sent_alerts
            WHERE job_id = ?
              AND event_name = ?
              AND cycle_number = ?
        """, (
            job_id,
            event_name,
            cycle_number
        )).fetchone()

    return row is not None


def mark_alert_sent(job_id, event_name, cycle_number):
    with sqlite3.connect(DATABASE) as db:
        db.execute("""
            INSERT OR IGNORE INTO sent_alerts (
                job_id,
                event_name,
                cycle_number,
                sent_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            job_id,
            event_name,
            cycle_number,
            to_iso()
        ))


def get_server_counts():
    with sqlite3.connect(DATABASE) as db:
        active = db.execute("""
            SELECT COUNT(*)
            FROM servers
            WHERE status = 'tracked'
        """).fetchone()[0]

        known_ages = db.execute("""
            SELECT COUNT(*)
            FROM servers
            WHERE status = 'tracked'
              AND server_age_seconds IS NOT NULL
        """).fetchone()[0]

    return active, known_ages
