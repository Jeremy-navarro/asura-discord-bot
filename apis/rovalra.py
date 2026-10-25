
import asyncio
import json

import aiohttp

from datetime import datetime, timezone, timedelta

from configuracion.config import (
    PLACE_ID,
    ROVALRA_PROCESS_URL,
    ROVALRA_DETAILS_URL,
    ROVALRA_RETRY_SECONDS,
    MAX_SERVER_AGE_HOURS,
    AGE_REFRESH_SECONDS,
    MAX_AGE_CHECKS_PER_SCAN,
)

from configuracion.database import (
    get_tracked_servers,
    save_real_server_age,
    to_iso,
)


def utc_now():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except (ValueError, TypeError, AttributeError):
        return None


def format_age(seconds):
    total_minutes = max(0, int(seconds // 60))

    total_hours, minutes = divmod(total_minutes, 60)
    days, hours = divmod(total_hours, 24)

    if days:
        return f"{days}d {hours}h {minutes:02d}min"

    if hours:
        return f"{hours}h {minutes:02d}min"

    return f"{minutes} min"


def format_age_compact(seconds):
    """Short age used by the rendered event card."""

    total_minutes = max(0, int(seconds // 60))

    total_hours, minutes = divmod(total_minutes, 60)
    days, hours = divmod(total_hours, 24)

    if days:
        return f"{days}d{hours:02d}h"

    if hours:
        return f"{hours}h{minutes:02d}m"

    return f"{minutes}m"


def age_is_stale(info):
    checked_at = parse_datetime(
        info.get("server_age_checked_at")
    )

    if checked_at is None:
        return True

    return (
        utc_now() - checked_at
    ).total_seconds() >= AGE_REFRESH_SECONDS


def get_current_age_seconds(info):
    age = info.get("server_age_seconds")

    checked_at = parse_datetime(
        info.get("server_age_checked_at")
    )

    if age is None or checked_at is None:
        return None

    elapsed = max(
        0,
        (utc_now() - checked_at).total_seconds()
    )

    return float(age) + elapsed


class RoValraClient:

    def __init__(self):
        self.rate_limited_until = None
        self.retry_after = {}

    def is_paused(self):
        return (
            self.rate_limited_until is not None
            and utc_now() < self.rate_limited_until
        )

    def register_429(self, response, job_id):
        retry_after = response.headers.get("Retry-After")

        try:
            wait_seconds = (
                float(retry_after)
                if retry_after
                else ROVALRA_RETRY_SECONDS
            )
        except (TypeError, ValueError):
            wait_seconds = ROVALRA_RETRY_SECONDS

        wait_seconds = max(
            wait_seconds,
            ROVALRA_RETRY_SECONDS
        )

        until = utc_now() + timedelta(
            seconds=wait_seconds
        )

        self.rate_limited_until = until
        self.retry_after[job_id] = until

        print(
            f"[RoValra] HTTP 429. Consultas pausadas "
            f"durante {wait_seconds:.0f} segundos."
        )

    async def fetch_server_age(self, session, job_id):
        now = utc_now()

        if self.is_paused():
            remaining = (
                self.rate_limited_until - now
            ).total_seconds()

            print(
                f"[RoValra] Consultas pausadas. "
                f"Quedan {remaining:.0f}s."
            )
            return None

        retry_at = self.retry_after.get(job_id)

        if retry_at is not None and now < retry_at:
            print(
                f"[RoValra] Se aplaza {job_id} "
                f"hasta {retry_at.isoformat()}."
            )
            return None

        try:
            payload = {
                "place_id": PLACE_ID,
                "server_ids": [job_id],
            }

            # Registrar el servidor en RoValra.
            async with session.post(
                ROVALRA_PROCESS_URL,
                json=payload
            ) as response:

                body = await response.text()

                print(
                    f"[RoValra registro] {job_id}: "
                    f"HTTP {response.status}; {body[:300]}"
                )

                if response.status == 429:
                    self.register_429(response, job_id)
                    return None

                if not 200 <= response.status < 300:
                    self.retry_after[job_id] = (
                        utc_now()
                        + timedelta(
                            seconds=ROVALRA_RETRY_SECONDS
                        )
                    )
                    return None

            # Consultar los detalles del servidor.
            async with session.get(
                ROVALRA_DETAILS_URL,
                params={
                    "place_id": PLACE_ID,
                    "server_ids": job_id,
                }
            ) as response:

                body = await response.text()

                print(
                    f"[RoValra detalles] {job_id}: "
                    f"HTTP {response.status}; {body[:500]}"
                )

                if response.status == 429:
                    self.register_429(response, job_id)
                    return None

                if response.status != 200:
                    self.retry_after[job_id] = (
                        utc_now()
                        + timedelta(
                            seconds=ROVALRA_RETRY_SECONDS
                        )
                    )
                    return None

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                print("[RoValra] Respuesta JSON inválida.")
                return None

            if not isinstance(data, dict):
                return None

            servers = data.get("servers", [])

            if not isinstance(servers, list):
                return None

            server = next(
                (
                    item
                    for item in servers
                    if isinstance(item, dict)
                    and item.get("server_id") == job_id
                ),
                None
            )

            if server is None:
                print(
                    f"[RoValra] Aún no hay detalles "
                    f"para {job_id}."
                )

                self.retry_after[job_id] = (
                    utc_now()
                    + timedelta(
                        seconds=ROVALRA_RETRY_SECONDS
                    )
                )
                return None

            first_seen = parse_datetime(
                server.get("first_seen")
            )

            if first_seen is None:
                print(
                    f"[RoValra] first_seen ausente "
                    f"o inválido para {job_id}."
                )
                return None

            age_seconds = (
                utc_now() - first_seen
            ).total_seconds()

            if not (
                0 <= age_seconds
                <= MAX_SERVER_AGE_HOURS * 3600
            ):
                print(
                    "[RoValra] first_seen está fuera "
                    "del rango configurado."
                )
                return None

            self.retry_after.pop(job_id, None)

            print(
                f"[RoValra] {job_id}: "
                f"first_seen={first_seen.isoformat()}; "
                f"tiempo desde detección="
                f"{format_age(age_seconds)}"
            )

            return age_seconds

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError
        ) as error:

            print(
                f"[RoValra] Error consultando "
                f"{job_id}: {error}"
            )

            self.retry_after[job_id] = (
                utc_now()
                + timedelta(
                    seconds=ROVALRA_RETRY_SECONDS
                )
            )

            return None

        except Exception as error:
            print(
                f"[RoValra] Error inesperado "
                f"para {job_id}: {error}"
            )
            return None

    async def refresh_server_ages(self, session):
        if self.is_paused():
            return

        tracked = get_tracked_servers()

        eligible = [
            (job_id, info)
            for job_id, info in tracked.items()
            if age_is_stale(info)
            and (
                job_id not in self.retry_after
                or utc_now() >= self.retry_after[job_id]
            )
        ]

        eligible.sort(
            key=lambda item: (
                item[1].get("server_age_checked_at") is not None,
                item[1].get("server_age_checked_at") or "",
            )
        )

        selected = eligible[:MAX_AGE_CHECKS_PER_SCAN]

        for job_id, _info in selected:
            if self.is_paused():
                break

            age_seconds = await self.fetch_server_age(
                session,
                job_id
            )

            if age_seconds is not None:
                save_real_server_age(
                    job_id,
                    age_seconds,
                    to_iso()
                )
