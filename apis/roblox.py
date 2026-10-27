
import asyncio
import aiohttp

from configuracion.config import (
    PLACE_ID,
    ROBLOX_SERVERS_API,
    ROQOL_INVITE_API,
    ROQOL_AUTHORIZATION,
    HTTP_TIMEOUT_SECONDS,
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
            "[RoQoL] Falta ROQOL_AUTHORIZATION "
            "en la configuración."
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
                data = await response.json(
                    content_type=None
                )
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
                    "[RoQoL] La respuesta no contiene "
                    f"una invitación: {job_id}"
                )
                return None

            candidate = candidate.strip()
            prefix = "https://roqol.io/i/"

            if (
                candidate.startswith(prefix)
                and len(candidate) > len(prefix)
                and not any(char.isspace() for char in candidate)
            ):
                print(
                    f"[RoQoL] Invitación obtenida para {job_id}."
                )
                return candidate

            print(
                f"[RoQoL] El enlace recibido no es válido "
                f"para {job_id}."
            )
            return None

    except asyncio.TimeoutError:
        print(
            f"[RoQoL] Timeout al solicitar invitación "
            f"para {job_id}."
        )
        return None

    except aiohttp.ClientError as error:
        print(
            f"[RoQoL] Error de conexión: "
            f"{type(error).__name__}: {error!r}"
        )
        return None


def join_server_url(
    job_id: str,
    place_id: int = PLACE_ID,
) -> str:
    """Construye un enlace directo al servidor de Roblox."""

    return (
        "https://www.roblox.com/games/start"
        f"?placeId={place_id}&gameInstanceId={job_id}"
    )


async def fetch_servers(session):
    """Obtiene todas las páginas de servidores públicos."""

    found = {}
    cursor = None
    seen_cursors = set()
    page_number = 0

    while True:
        page_number += 1

        params = {
            "sortOrder": "Asc",
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        try:
            print(
                f"[Roblox] Consultando página {page_number}..."
            )

            async with session.get(
                ROBLOX_SERVERS_API,
                params=params,
            ) as response:

                if response.status != 200:
                    body = (await response.text())[:300]

                    raise IncompleteServerScan(
                        f"Roblox HTTP {response.status} "
                        f"en página {page_number}: "
                        f"{body or 'respuesta vacía'}"
                    )

                data = await response.json(
                    content_type=None
                )

        except IncompleteServerScan:
            raise

        except asyncio.TimeoutError as error:
            raise IncompleteServerScan(
                f"Timeout en página {page_number}; "
                f"límite configurado: "
                f"{HTTP_TIMEOUT_SECONDS} segundos."
            ) from error

        except (aiohttp.ClientError, ValueError) as error:
            raise IncompleteServerScan(
                f"{type(error).__name__} en página "
                f"{page_number}: {error!r}"
            ) from error

        if not isinstance(data, dict):
            raise IncompleteServerScan(
                f"Respuesta inesperada en página {page_number}."
            )

        servers = data.get("data")

        if not isinstance(servers, list):
            raise IncompleteServerScan(
                f"Falta la lista de servidores en "
                f"página {page_number}."
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

        print(
            f"[Roblox] Página {page_number}: "
            f"{len(servers)} servidores; "
            f"{len(found)} acumulados."
        )

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
        f"[Roblox] Escaneo completado: "
        f"{len(found)} servidores en "
        f"{page_number} páginas."
    )

    return found
