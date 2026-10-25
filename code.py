import asyncio
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

from diseno.alerta import (
    build_alert_card,
    create_server_view,
)


# ============================================================
# ALERT ROLE CONFIGURATION
# ============================================================

ALERT_ROLE_ID = 1561702759550689411


# ============================================================
# UTILITIES
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
# SERVER SCANNING
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
            f"[Scan] Found {len(current_ids)} "
            "public servers."
        )

    except IncompleteServerScan as error:
        print(
            f"[Incomplete Scan] {error}. "
            "Previous server states will be preserved."
        )

    except Exception as error:
        print(
            f"[Scan] Unexpected error: {error}"
        )


@scan_servers.before_loop
async def before_scan_servers():
    await bot.wait_until_ready()


# ============================================================
# RIFT AND BOSS ALERTS
# ============================================================

@tasks.loop(seconds=REPORT_SECONDS)
async def send_event_alerts():

    if rift_channel is None and boss_channel is None:
        print(
            "[Discord] No alert channels are available."
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

            # Only alert for servers that are still public.
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

                # Select the appropriate notification channel.
                if event_name == "RIFT":
                    target_channel = rift_channel

                elif event_name == "BOSS":
                    target_channel = boss_channel

                else:
                    print(
                        f"[Alerts] Unknown event: {event_name}"
                    )
                    continue

                if target_channel is None:
                    print(
                        f"[Discord] No channel available "
                        f"for {event_name}."
                    )
                    continue

                # Prevent duplicate alerts for the same cycle.
                if alert_was_sent(
                    job_id,
                    event_name,
                    cycle,
                ):
                    continue

                # Obtain the RoQoL invitation.
                try:
                    invite_url = await get_roqol_invite(
                        bot.http_session,
                        job_id,
                    )

                except Exception as error:
                    print(
                        f"[RoQoL] Failed to generate an "
                        f"invitation for {job_id}: {error}"
                    )
                    continue

                if not invite_url:
                    print(
                        f"[RoQoL] No invitation obtained for "
                        f"{job_id}. Retrying on the next check."
                    )
                    continue

                print(
                    f"[RoQoL] Invitation obtained for "
                    f"{job_id}: {invite_url}"
                )

                # Render the alert card. Discord cannot run CSS, so
                # the whole design (button included) is painted into
                # a PNG that is sent on its own, without an embed.
                try:
                    card = await asyncio.to_thread(
                        build_alert_card,
                        event_name=event_name,
                        server_id=job_id,
                        age_seconds=age_seconds,
                        cycle=cycle,
                        minutes_from_target=event[
                            "minutes_from_target"
                        ],
                        players=(
                            f"{server['playing']}/"
                            f"{server['max']}"
                        ),
                    )

                except Exception as error:
                    print(
                        f"[Card] Could not render {event_name} "
                        f"for {job_id}: {error}"
                    )
                    continue

                try:
                    view = create_server_view(
                        invite_url
                    )

                    # A fresh attachment per alert so several
                    # alerts in the same scan do not collide.
                    file = discord.File(
                        card,
                        filename=(
                            f"asura_{event_name.lower()}.png"
                        ),
                    )

                    # Mention the alert role and send the card.
                    await target_channel.send(
                        content=f"<@&{ALERT_ROLE_ID}>",
                        file=file,
                        view=view,
                        allowed_mentions=discord.AllowedMentions(
                            roles=True
                        ),
                    )

                    # Record the alert only after successful send.
                    mark_alert_sent(
                        job_id,
                        event_name,
                        cycle,
                    )

                    print(
                        f"[Alert] {event_name} sent to "
                        f"#{target_channel.name} | "
                        f"Server: {job_id} | "
                        f"Cycle: {cycle} | "
                        f"Role mentioned: {ALERT_ROLE_ID}"
                    )

                except discord.HTTPException as error:
                    print(
                        f"[Discord] Failed to send "
                        f"{event_name} to its channel: {error}"
                    )

                except Exception as error:
                    print(
                        f"[Alerts] Error processing "
                        f"{event_name} for {job_id}: {error}"
                    )

    except IncompleteServerScan as error:
        print(
            f"[Alerts] Incomplete server scan: {error}"
        )

    except Exception as error:
        print(
            f"[Alerts] Unexpected error: {error}"
        )


@send_event_alerts.before_loop
async def before_send_event_alerts():
    await bot.wait_until_ready()


# ============================================================
# COMMAND: !test_age
# ============================================================

@bot.command(name="test_age")
async def test_age(ctx, job_id: str):

    message = await ctx.send(
        "Checking the server's first detection on RoValra..."
    )

    age_seconds = await rovalra.fetch_server_age(
        bot.http_session,
        job_id,
    )

    if age_seconds is None:
        await message.edit(
            content=(
                "Could not retrieve a valid server age "
                "from RoValra.\n"
                "An HTTP 429 rate limit may have occurred, "
                "or first_seen may be missing. "
                "Check the console for details."
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
            f"(Cycle #{event['cycle']})"
            for event in events
        )
    else:
        event_text = (
            "No events found within the "
            f"±{EVENT_WINDOW_MINUTES}-minute window."
        )

    await message.edit(
        content=(
            f"**Server:** `{job_id}`\n"
            f"**Time since first detected by RoValra:** "
            f"{format_age(age_seconds)}\n\n"
            f"**Estimated upcoming events:**\n"
            f"{event_text}\n\n"
            "⚠️ RoValra's first_seen data does not confirm "
            "the actual Roblox server creation time or "
            "the real event start time."
        )
    )


# ============================================================
# COMMAND: !tracker_status
# ============================================================

@bot.command(name="tracker_status")
async def tracker_status(ctx):

    active, known_ages = get_server_counts()

    embed = discord.Embed(
        title="📡 ASURA Tracker Status",
        color=discord.Color.blurple(),
        timestamp=utc_now(),
    )

    embed.add_field(
        name="Registered Active Servers",
        value=str(active),
        inline=True,
    )

    embed.add_field(
        name="Servers with Recorded Age",
        value=str(known_ages),
        inline=True,
    )

    embed.add_field(
        name="Alert Window",
        value=f"±{EVENT_WINDOW_MINUTES} minutes",
        inline=True,
    )

    embed.add_field(
        name="RIFT Cycle",
        value=f"{RIFT_INTERVAL_MINUTES} min",
        inline=True,
    )

    embed.add_field(
        name="BOSS Cycle",
        value=f"{BOSS_INTERVAL_MINUTES} min",
        inline=True,
    )

    embed.add_field(
        name="Maximum Server Age",
        value=f"{MAX_SERVER_AGE_HOURS} hours",
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
            f"Paused due to rate limiting "
            f"({remaining}s remaining)"
        )
    else:
        rovalra_status = "No active global pause"

    embed.add_field(
        name="RoValra Status",
        value=rovalra_status,
        inline=False,
    )

    embed.set_footer(
        text=(
            "RoValra's first_seen data does not guarantee "
            "the actual server age or confirm event appearance."
        )
    )

    await ctx.send(embed=embed)


# ============================================================
# BOT STARTUP
# ============================================================

@bot.event
async def on_ready():
    global rift_channel, boss_channel

    print(f"Connected as {bot.user}")

    # Load the RIFT notification channel.
    try:
        rift_channel = bot.get_channel(
            RIFT_CHANNEL_ID
        )

        if rift_channel is None:
            rift_channel = await bot.fetch_channel(
                RIFT_CHANNEL_ID
            )

        print(
            f"[Discord] RIFT channel: "
            f"#{rift_channel.name}"
        )

    except discord.HTTPException as error:
        rift_channel = None
        print(
            f"[Discord] Could not access the RIFT channel: "
            f"{error}"
        )

    # Load the BOSS notification channel.
    try:
        boss_channel = bot.get_channel(
            BOSS_CHANNEL_ID
        )

        if boss_channel is None:
            boss_channel = await bot.fetch_channel(
                BOSS_CHANNEL_ID
            )

        print(
            f"[Discord] BOSS channel: "
            f"#{boss_channel.name}"
        )

    except discord.HTTPException as error:
        boss_channel = None
        print(
            f"[Discord] Could not access the BOSS channel: "
            f"{error}"
        )

    if rift_channel is None and boss_channel is None:
        print(
            "[Discord] Neither notification channel could be "
            "loaded. Check the channel IDs and bot permissions."
        )

    if not scan_servers.is_running():
        scan_servers.start()

    if not send_event_alerts.is_running():
        send_event_alerts.start()

    print("ASURA Tracker started.")
    print(f"Server scan interval: {SCAN_SECONDS} seconds.")
    print(
        f"Alert check interval: {REPORT_SECONDS} seconds."
    )
    print("Server age source: RoValra first_seen.")
    print(
        f"RIFT cycle: {RIFT_INTERVAL_MINUTES} min | "
        f"BOSS cycle: {BOSS_INTERVAL_MINUTES} min"
    )
    print(f"Alert role ID: {ALERT_ROLE_ID}")


# ============================================================
# RUN BOT
# ============================================================

init_db()
bot.run(DISCORD_TOKEN)