import aiohttp
import discord

from datetime import datetime, timezone
from discord.ext import commands, tasks

from configuracion.config import (
    DISCORD_TOKEN,
    RIFT_CHANNEL_ID,
    BOSS_CHANNEL_ID,
    SCAN_SECONDS,
    REPORT_SECONDS,
    MAX_SERVER_AGE_HOURS,
    EVENT_WINDOW_MINUTES,
    RIFT_INTERVAL_MINUTES,
    BOSS_INTERVAL_MINUTES,
    HTTP_TIMEOUT_SECONDS,
)

from configuracion.database import (
    init_db,
    to_iso,
    upsert_active_servers,
    mark_inactive,
    get_tracked_servers,
    save_real_server_age,
    alert_was_sent,
    mark_alert_sent,
    get_server_counts,
)

from apis.roblox import (
    fetch_servers,
    get_roqol_invite,
    IncompleteServerScan,
)

from apis.rovalra import (
    RoValraClient,
    format_age,
    get_current_age_seconds,
)

from apis.events import (
    get_nearby_events,
    event_time_description,
)


# ============================================================
# CONFIGURACIÓN DE MENCIONES
# ============================================================

# ID del rol que recibirá las notificaciones RIFT y BOSS.
ALERT_ROLE_ID = 1559554951057776690


# ============================================================
# UTILIDADES
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


# ============================================================
# BOT
# ============================================================

class ASURATrackerBot(commands.Bot):

    async def setup_hook(self):
        timeout = aiohttp.ClientTimeout(
            total=HTTP_TIMEOUT_SECONDS
        )

        self.http_session = aiohttp.ClientSession(
            timeout=timeout
        )

    async def close(self):
        session = getattr(
            self,
            "http_session",
            None,
        )

        if session and not session.closed:
            await session.close()

        await super().close()


intents = discord.Intents.default()
intents.message_content = True

bot = ASURATrackerBot(
    command_prefix="!",
    intents=intents,
)

rovalra = RoValraClient()

rift_channel = None
boss_channel = None


# ============================================================
# BOTÓN PARA UNIRSE AL SERVIDOR
# ============================================================

def create_server_view(
    invite_url: str,
) -> discord.ui.View:
    """
    Crea un botón que utiliza exclusivamente la invitación
    corta generada por RoQoL.
    """

    if not invite_url.startswith("https://roqol.io/i/"):
        raise ValueError(
            "La invitación no es una URL válida de RoQoL."
        )

    view = discord.ui.View(timeout=None)

    button = discord.ui.Button(
        label="🎮 Unirse al servidor",
        style=discord.ButtonStyle.link,
        url=invite_url,
    )

    view.add_item(button)

    return view


# ============================================================
# ESCANEO DE SERVIDORES
# ============================================================

@tasks.loop(seconds=SCAN_SECONDS)
async def scan_servers():
    try:
        current = await fetch_servers(
            bot.http_session
        )

        current_ids = set(current.keys())

        upsert_active_servers(
            current_ids,
            to_iso(),
        )

        mark_inactive(current_ids)

        await rovalra.refresh_server_ages(
            bot.http_session
        )

        print(
            f"[Escaneo] {len(current_ids)} servidores "
            "públicos encontrados."
        )

    except IncompleteServerScan as error:
        print(
            f"[Escaneo incompleto] {error}. "
            "Se conservan los estados anteriores."
        )

    except Exception as error:
        print(
            f"[Escaneo] Error inesperado: {error}"
        )


@scan_servers.before_loop
async def before_scan_servers():
    await bot.wait_until_ready()


# ============================================================
# ALERTAS DE RIFT Y BOSS
# ============================================================

@tasks.loop(seconds=REPORT_SECONDS)
async def send_event_alerts():
    if rift_channel is None and boss_channel is None:
        print(
            "[Discord] No hay canales de alertas disponibles."
        )
        return

    try:
        current = await fetch_servers(
            bot.http_session
        )

        current_ids = set(current.keys())

        upsert_active_servers(
            current_ids,
            to_iso(),
        )

        tracked = get_tracked_servers()

        for job_id, info in tracked.items():

            # Solo alertar si el servidor sigue público.
            if job_id not in current_ids:
                continue

            age_seconds = get_current_age_seconds(info)

            if age_seconds is None:
                continue

            if age_seconds > MAX_SERVER_AGE_HOURS * 3600:
                continue

            server = current[job_id]

            events = get_nearby_events(
                age_seconds
            )

            for event in events:
                event_name = event["name"]
                cycle = event["cycle"]

                # Seleccionar el canal correspondiente.
                if event_name == "RIFT":
                    target_channel = rift_channel

                elif event_name == "BOSS":
                    target_channel = boss_channel

                else:
                    print(
                        f"[Alertas] Evento desconocido: "
                        f"{event_name}"
                    )
                    continue

                if target_channel is None:
                    print(
                        f"[Discord] No hay canal disponible "
                        f"para {event_name}."
                    )
                    continue

                # Evitar duplicados del mismo ciclo.
                if alert_was_sent(
                    job_id,
                    event_name,
                    cycle,
                ):
                    continue

                # Obtener la invitación ANTES de enviar.
                try:
                    invite_url = await get_roqol_invite(
                        bot.http_session,
                        job_id,
                    )

                except Exception as error:
                    print(
                        f"[RoQoL] Error generando invitación "
                        f"para {job_id}: {error}"
                    )
                    continue

                # Sin invitación de RoQoL no se publica
                # un botón alternativo potencialmente impreciso.
                if not invite_url:
                    print(
                        f"[RoQoL] No se obtuvo invitación "
                        f"para {job_id}. "
                        f"Se reintentará en la siguiente revisión."
                    )
                    continue

                print(
                    f"[RoQoL] Invitación obtenida para "
                    f"{job_id}: {invite_url}"
                )

                embed = discord.Embed(
                    title=f"⚔️ ASURA — {event_name} próximo",
                    description=(
                        f"**Servidor:** `{job_id}`\n"
                        f"**Desde primera detección de RoValra:** "
                        f"{format_age(age_seconds)}\n"
                        f"**Evento estimado:** {event_name}\n"
                        f"**Ciclo:** #{cycle}\n"
                        f"**Tiempo estimado:** "
                        f"{event_time_description(event)}\n"
                        f"**Jugadores:** "
                        f"{server['playing']}/{server['max']}"
                    ),
                    color=(
                        discord.Color.red()
                        if event_name == "RIFT"
                        else discord.Color.gold()
                    ),
                    timestamp=utc_now(),
                )

                embed.set_footer(
                    text=(
                        "Antigüedad basada en first_seen de "
                        "RoValra. No confirma la aparición "
                        "real del evento."
                    )
                )

                try:
                    view = create_server_view(
                        invite_url
                    )

                    # Mencionar al rol en cada alerta.
                    await target_channel.send(
                        content=f"<@&{ALERT_ROLE_ID}>",
                        embed=embed,
                        view=view,
                        allowed_mentions=discord.AllowedMentions(
                            roles=True
                        ),
                    )

                    # Registrar el envío solo si Discord
                    # confirma que el mensaje se publicó.
                    mark_alert_sent(
                        job_id,
                        event_name,
                        cycle,
                    )

                    print(
                        f"[Alerta] {event_name} enviada a "
                        f"#{target_channel.name} | "
                        f"servidor {job_id} | "
                        f"ciclo {cycle} | "
                        f"rol mencionado: {ALERT_ROLE_ID}"
                    )

                except discord.HTTPException as error:
                    print(
                        f"[Discord] No se pudo enviar "
                        f"{event_name} a su canal: {error}"
                    )

                except Exception as error:
                    print(
                        f"[Alertas] Error procesando "
                        f"{event_name} para {job_id}: {error}"
                    )

    except IncompleteServerScan as error:
        print(
            f"[Alertas] Escaneo incompleto: {error}"
        )

    except Exception as error:
        print(
            f"[Alertas] Error inesperado: {error}"
        )


@send_event_alerts.before_loop
async def before_send_event_alerts():
    await bot.wait_until_ready()


# ============================================================
# COMANDO: !probar_edad
# ============================================================

@bot.command(name="probar_edad")
async def probar_edad(ctx, job_id: str):

    message = await ctx.send(
        "Consultando la primera detección del servidor "
        "en RoValra..."
    )

    age_seconds = await rovalra.fetch_server_age(
        bot.http_session,
        job_id,
    )

    if age_seconds is None:
        await message.edit(
            content=(
                "No se pudo obtener una antigüedad válida "
                "desde RoValra.\n"
                "Puede haber un límite HTTP 429 o faltar "
                "first_seen. Revisa la consola."
            )
        )
        return

    now = to_iso()

    upsert_active_servers(
        [job_id],
        now,
    )

    save_real_server_age(
        job_id,
        age_seconds,
        now,
    )

    events = get_nearby_events(
        age_seconds
    )

    if events:
        event_text = "\n".join(
            f"- **{event['name']}**: "
            f"{event_time_description(event)} "
            f"(ciclo #{event['cycle']})"
            for event in events
        )
    else:
        event_text = (
            "No hay eventos dentro de la ventana "
            f"de ±{EVENT_WINDOW_MINUTES} minutos."
        )

    await message.edit(
        content=(
            f"**Servidor:** `{job_id}`\n"
            f"**Tiempo desde primera detección de RoValra:** "
            f"{format_age(age_seconds)}\n\n"
            f"**Eventos cercanos estimados:**\n"
            f"{event_text}\n\n"
            "⚠️ first_seen de RoValra no confirma la hora "
            "real de inicio del servidor de Roblox."
        )
    )


# ============================================================
# COMANDO: !estado_tracker
# ============================================================

@bot.command(name="estado_tracker")
async def estado_tracker(ctx):

    active, known_ages = get_server_counts()

    embed = discord.Embed(
        title="📡 Estado del tracker ASURA",
        color=discord.Color.blurple(),
        timestamp=utc_now(),
    )

    embed.add_field(
        name="Servidores activos registrados",
        value=str(active),
        inline=True,
    )

    embed.add_field(
        name="Con detección registrada",
        value=str(known_ages),
        inline=True,
    )

    embed.add_field(
        name="Ventana de alerta",
        value=f"±{EVENT_WINDOW_MINUTES} minutos",
        inline=True,
    )

    embed.add_field(
        name="Ciclo RIFT",
        value=f"{RIFT_INTERVAL_MINUTES} min",
        inline=True,
    )

    embed.add_field(
        name="Ciclo BOSS",
        value=f"{BOSS_INTERVAL_MINUTES} min",
        inline=True,
    )

    embed.add_field(
        name="Tiempo máximo considerado",
        value=f"{MAX_SERVER_AGE_HOURS} horas",
        inline=True,
    )

    if rovalra.is_paused():
        remaining = max(
            0,
            int(
                (
                    rovalra.rate_limited_until
                    - utc_now()
                ).total_seconds()
            )
        )

        rovalra_status = (
            f"En pausa por rate limit "
            f"({remaining}s restantes)"
        )
    else:
        rovalra_status = "Sin pausa global activa"

    embed.add_field(
        name="RoValra",
        value=rovalra_status,
        inline=False,
    )

    embed.set_footer(
        text=(
            "first_seen de RoValra no garantiza la edad "
            "real ni confirma la aparición del evento."
        )
    )

    await ctx.send(embed=embed)


# ============================================================
# INICIO DEL BOT
# ============================================================

@bot.event
async def on_ready():
    global rift_channel, boss_channel

    print(f"Conectado como {bot.user}")

    # Cargar canal RIFT.
    try:
        rift_channel = bot.get_channel(
            RIFT_CHANNEL_ID
        )

        if rift_channel is None:
            rift_channel = await bot.fetch_channel(
                RIFT_CHANNEL_ID
            )

        print(
            f"[Discord] Canal RIFT: "
            f"#{rift_channel.name}"
        )

    except discord.HTTPException as error:
        rift_channel = None
        print(
            f"[Discord] No se pudo acceder al canal RIFT: "
            f"{error}"
        )

    # Cargar canal BOSS.
    try:
        boss_channel = bot.get_channel(
            BOSS_CHANNEL_ID
        )

        if boss_channel is None:
            boss_channel = await bot.fetch_channel(
                BOSS_CHANNEL_ID
            )

        print(
            f"[Discord] Canal BOSS: "
            f"#{boss_channel.name}"
        )

    except discord.HTTPException as error:
        boss_channel = None
        print(
            f"[Discord] No se pudo acceder al canal BOSS: "
            f"{error}"
        )

    if rift_channel is None and boss_channel is None:
        print(
            "[Discord] No se pudo cargar ninguno de los "
            "canales de alertas. Revisa los IDs y permisos."
        )

    if not scan_servers.is_running():
        scan_servers.start()

    if not send_event_alerts.is_running():
        send_event_alerts.start()

    print("Tracker ASURA iniciado.")
    print(f"Escaneo cada {SCAN_SECONDS} segundos.")
    print(
        f"Revisión de alertas cada {REPORT_SECONDS} segundos."
    )
    print("Fuente de antigüedad: RoValra first_seen.")
    print(
        f"Ciclo RIFT: {RIFT_INTERVAL_MINUTES} min | "
        f"Ciclo BOSS: {BOSS_INTERVAL_MINUTES} min"
    )
    print(f"Rol de alertas: {ALERT_ROLE_ID}")


# ============================================================
# EJECUCIÓN
# ============================================================

init_db()
bot.run(DISCORD_TOKEN)