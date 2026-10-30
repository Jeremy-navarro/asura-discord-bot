"""Envia una alerta de prueba sin arrancar el tracker.

Uso:
    python probar_alerta.py
    python probar_alerta.py BOSS
    python probar_alerta.py RIFT --solo-imagen
    python probar_alerta.py RIFT --canal 1234567890 --sin-mencion

El script genera la misma tarjeta que envia el bot y la manda al
canal del evento (o al que indiques con --canal).
"""

import argparse
import asyncio
import tempfile

from datetime import datetime
from pathlib import Path

import discord

from configuracion.config import (
    ALERT_ROLE_ID,
    BOSS_CHANNEL_ID,
    DISCORD_TOKEN,
    RIFT_CHANNEL_ID,
)

from diseno.alerta import (
    build_alert_card,
    create_server_view,
)

from apis.roblox import join_server_url


CHANNELS = {
    "RIFT": RIFT_CHANNEL_ID,
    "BOSS": BOSS_CHANNEL_ID,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Envia una alerta de prueba del tracker ASURA.",
    )

    parser.add_argument(
        "evento",
        nargs="?",
        default="RIFT",
        type=str.upper,
        choices=("RIFT", "BOSS"),
        help="Tipo de alerta (por defecto RIFT).",
    )

    parser.add_argument(
        "--canal",
        type=int,
        help="ID del canal destino (por defecto el del evento).",
    )

    parser.add_argument(
        "--rol",
        type=int,
        default=ALERT_ROLE_ID,
        help="ID del rol a mencionar. Usa 0 para no mencionar.",
    )

    parser.add_argument(
        "--servidor",
        default="1234-5678",
        help="ID de servidor que aparece en la tarjeta.",
    )

    parser.add_argument(
        "--edad-minutos",
        type=float,
        default=134,
        help="Antiguedad del servidor en minutos.",
    )

    parser.add_argument(
        "--ciclo",
        type=int,
        default=7,
        help="Numero de ciclo a mostrar.",
    )

    parser.add_argument(
        "--faltan-minutos",
        type=float,
        default=-12,
        help=(
            "Minutos hasta el evento. Negativo = todavia no ocurre, "
            "positivo = ya paso."
        ),
    )

    parser.add_argument(
        "--jugadores",
        default="18/50",
        help="Texto de jugadores, por ejemplo 18/50.",
    )

    parser.add_argument(
        "--invitacion",
        default=None,
        help=(
            "URL del boton. Por defecto se genera el enlace "
            "directo de Roblox para --servidor."
        ),
    )

    parser.add_argument(
        "--sin-mencion",
        action="store_true",
        help="No menciona ningun rol.",
    )

    parser.add_argument(
        "--solo-imagen",
        action="store_true",
        help="Solo guarda el PNG, sin conectarse a Discord.",
    )

    return parser.parse_args()


def render(args):
    return build_alert_card(
        event_name=args.evento,
        server_id=args.servidor,
        age_seconds=args.edad_minutos * 60,
        cycle=args.ciclo,
        minutes_from_target=args.faltan_minutos,
        players=args.jugadores,
    )


def save(card, evento):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    path = (
        Path(tempfile.gettempdir())
        / f"asura_alerta_{evento.lower()}_{stamp}.png"
    )

    path.write_bytes(card.getvalue())

    return path


async def enviar(card, args, canal):
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        try:
            channel = await client.fetch_channel(canal)

            role_id = 0 if args.sin_mencion else args.rol

            await channel.send(
                content=f"<@&{role_id}>" if role_id else None,
                file=discord.File(
                    card,
                    filename=f"asura_{args.evento.lower()}.png",
                ),
                view=create_server_view(args.invitacion),
                allowed_mentions=discord.AllowedMentions(
                    roles=bool(role_id)
                ),
            )

            print(
                f"Alerta enviada a #{channel.name} "
                f"({channel.id})."
            )

        except discord.Forbidden:
            print(
                "El bot no puede escribir en ese canal. "
                "Revisa el ID y los permisos."
            )

        except discord.NotFound:
            print("El canal no existe o el bot no lo puede ver.")

        except discord.HTTPException as error:
            print(f"Discord rechazo el mensaje: {error}")

        except Exception as error:
            print(f"Error inesperado: {error}")

        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)


def main():
    args = parse_args()

    if not args.invitacion:
        args.invitacion = join_server_url(args.servidor)

    canal = args.canal or CHANNELS[args.evento]

    card = render(args)

    if args.solo_imagen:
        print(f"Tarjeta guardada en: {save(card, args.evento)}")
        return

    if not DISCORD_TOKEN:
        print("Falta DISCORD_TOKEN en el archivo .env.")
        return

    print(
        f"Enviando alerta {args.evento} al canal {canal} "
        f"({len(card.getvalue()) // 1024} KB)..."
    )

    try:
        asyncio.run(enviar(card, args, canal))

    except discord.LoginFailure:
        print("El token de Discord no es valido.")

    except KeyboardInterrupt:
        print("Cancelado.")


if __name__ == "__main__":
    main()
