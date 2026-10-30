"""Alert card shared by the tracker and the test script."""

import discord

from apis.rovalra import format_age_compact

from diseno.card import (
    PRIMARY,
    SECONDARY,
    render_event_card,
)


EVENT_COLORS = {
    "RIFT": ((0, 242, 234), (168, 85, 247)),
    "BOSS": ((168, 85, 247), (0, 242, 234)),
}

DISCLAIMER = "Event timing is estimated and not guaranteed."


def create_server_view(invite_url):
    """Link button sent under the card."""

    if (
        not invite_url.startswith("https://")
        or any(char.isspace() for char in invite_url)
    ):
        raise ValueError(
            "The invitation is not a valid https link."
        )

    view = discord.ui.View(timeout=None)

    view.add_item(
        discord.ui.Button(
            label="JOIN_SERVER  ▸  UNIRSE AL SERVIDOR",
            emoji="🎮",
            style=discord.ButtonStyle.link,
            url=invite_url,
        )
    )

    return view


def time_stat(minutes_from_target):
    """Translate the event offset into a label/value pair."""

    if abs(minutes_from_target) < 0.5:
        return "WINDOW", "NOW"

    if minutes_from_target < 0:
        return "NEXT IN", f"{abs(minutes_from_target):.0f}m"

    return "PASSED", f"{minutes_from_target:.0f}m"


def build_alert_card(
    event_name,
    server_id,
    age_seconds,
    cycle,
    minutes_from_target,
    players,
    primary=None,
    secondary=None,
    monochrome_logo=False,
):
    """Render the PNG sent with a RIFT/BOSS alert."""

    event_name = event_name.upper()

    default_primary, default_secondary = EVENT_COLORS.get(
        event_name,
        (PRIMARY, SECONDARY),
    )

    time_label, time_value = time_stat(minutes_from_target)

    return render_event_card(
        title=f"{event_name} ALERT",
        subtitle=f"SERVER {server_id}",
        stats=(
            ("AGE", format_age_compact(age_seconds)),
            ("CYCLE", f"#{cycle}"),
            (time_label, time_value),
            ("PLAYERS", players),
        ),
        primary=primary or default_primary,
        secondary=secondary or default_secondary,
        monochrome_logo=monochrome_logo,
        footer=DISCLAIMER,
    )
