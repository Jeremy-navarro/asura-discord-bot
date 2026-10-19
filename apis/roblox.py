
import asyncio
import aiohttp

from configuracion.config import (
    PLACE_ID,
    ROBLOX_SERVERS_API,
    ROQOL_INVITE_API,
    ROQOL_AUTHORIZATION,
)


class IncompleteServerScan(Exception):
    """El escaneo de Roblox no pudo completarse."""


async def get_roqol_invite(
    session,
    job_id: str,
    place_id: int = PLACE_ID,
) -> str | None:
    """Solicita una invitación corta de RoQoL."""

    params = {
        "placeId": place_id,
        "jobId": job_id,
    }

    headers = {
        "Accept": "application/json",
        "Origin": "https://www.roblox.com",
        "Referer": "https://www.roblox.com/",
        "x-locale": "en",
    }

    if ROQOL_AUTHORIZATION:
        headers["authorization"] = ROQOL_AUTHORIZATION
    else:
        print(
            "[RoQoL] Falta ROQOL_AUTHORIZATION en el archivo .env."
        )
        return None

    try:
        async with session.get(
            ROQOL_INVITE_API,
            params=params,
            headers=headers,
        ) as response:
            body = await response.text()

            if response.status != 200:
                print(
                    f"[RoQoL] HTTP {response.status} "
                    f"para {job_id}: {body[:200]}"
                )
                return None

            try:
                data = await response.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                print("[RoQoL] Respuesta JSON no válida.")
                return None

            if isinstance(data, dict):
                candidate = (
                    data.get("Invite")
                    or data.get("invite")
                    or data.get("url")
                    or data.get("inviteUrl")
                    or data.get("invite_url")
                    or data.get("link")
                )
            elif isinstance(data, str):
                candidate = data
            else:
                candidate = None

            if not isinstance(candidate, str):
                print(
                    f"[RoQoL] La respuesta no contiene una invitación: "
                    f"{job_id}"
                )
                return None

            candidate = candidate.strip()

            if (
                candidate.startswith("https://roqol.io/i/")
                and len(candidate) > len("https://roqol.io/i/")
                and not any(char.isspace() for char in candidate)
            ):
                print(
                    f"[RoQoL] Invitación obtenida para {job_id}."
                )
                return candidate

            print(
                f"[RoQoL] El enlace recibido no es válido para {job_id}."
            )
            return None

    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f"[RoQoL] Error de conexión: {error}")
        return None


def join_server_url(
    job_id: str,
    place_id: int = PLACE_ID,
) -> str:
    """Construye el enlace directo de Roblox como alternativa."""

    return (
        "https://www.roblox.com/games/start"
        f"?placeId={place_id}&gameInstanceId={job_id}"
    )


async def fetch_servers(session):
    """Obtiene todas las páginas de servidores públicos de Roblox."""

    found = {}
    cursor = None
    seen_cursors = set()

    while True:
        params = {
            "sortOrder": "Asc",
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        try:
            async with session.get(
                ROBLOX_SERVERS_API,
                params=params,
            ) as response:
                if response.status == 429:
                    raise IncompleteServerScan(
                        "Roblox respondió HTTP 429."
                    )

                response.raise_for_status()
                data = await response.json()

        except IncompleteServerScan:
            raise
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
        ) as error:
            raise IncompleteServerScan(
                f"Falló la consulta a Roblox: {error}"
            ) from error

        if not isinstance(data, dict):
            raise IncompleteServerScan(
                "Respuesta inesperada de Roblox."
            )

        for server in data.get("data", []):
            job_id = server.get("id")

            if not job_id:
                continue

            found[job_id] = {
                "playing": server.get("playing", 0),
                "max": server.get("maxPlayers", 0),
            }

        next_cursor = data.get("nextPageCursor")

        if not next_cursor:
            break

        if next_cursor in seen_cursors:
            raise IncompleteServerScan(
                "Roblox devolvió un cursor repetido."
            )

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return found
