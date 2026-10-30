import asyncio
import aiohttp

from urllib.parse import urlencode

from configuracion.config import (
    INVITE_BASE_URL,
    PLACE_ID,
    ROBLOX_SERVERS_API,
)


class IncompleteServerScan(Exception):
    """El escaneo de Roblox no pudo completarse."""


# ============================================================
# GENERATE SERVER JOIN LINK
# ============================================================

def join_server_url(
    job_id: str,
    place_id: int = PLACE_ID,
) -> str:
    """
    Genera un enlace para entrar a un servidor específico.

    Utiliza Netlify si INVITE_BASE_URL está configurado.
    Conserva el JobId original durante la generación.
    """

    job_id = str(job_id or "").strip()

    if not job_id:
        raise ValueError("Job ID vacío.")

    if (
        "/" in job_id
        or "\\" in job_id
        or any(char.isspace() for char in job_id)
    ):
        raise ValueError(
            f"Job ID inválido: {job_id!r}"
        )

    if INVITE_BASE_URL:

        url = f"{INVITE_BASE_URL}/{job_id}"

        print("\n[JOIN SYSTEM]")
        print(f"PLACE ID: {place_id}")
        print(f"EXPECTED JOB ID: {job_id}")
        print(f"GENERATED URL: {url}")

        return url

    # Official Roblox launcher fallback.
    params = urlencode({
        "placeId": place_id,
        "gameInstanceId": job_id,
    })

    url = (
        "https://www.roblox.com/games/start?"
        f"{params}"
    )

    print("\n[JOIN SYSTEM]")
    print(f"PLACE ID: {place_id}")
    print(f"EXPECTED JOB ID: {job_id}")
    print(f"GENERATED URL: {url}")

    return url


# ============================================================
# FETCH PUBLIC ROBLOX SERVERS
# ============================================================

async def fetch_servers(session):
    """
    Obtiene todas las páginas de servidores públicos
    de Roblox y conserva sus JobId originales.
    """

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

        servers = data.get("data", [])

        if not isinstance(servers, list):
            raise IncompleteServerScan(
                "Lista de servidores inválida."
            )

        for server in servers:

            if not isinstance(server, dict):
                continue

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

    print(
        f"[Roblox] Public servers detected: {len(found)}"
    )

    return found