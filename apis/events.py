from configuracion.config import (
    EVENT_WINDOW_MINUTES,
    RIFT_INTERVAL_MINUTES,
    BOSS_INTERVAL_MINUTES,
    MAX_SERVER_AGE_HOURS,
)


EVENTS = (
    ("RIFT", RIFT_INTERVAL_MINUTES),
    ("BOSS", BOSS_INTERVAL_MINUTES),
)


def get_nearby_events(age_seconds):
    age_minutes = age_seconds / 60

    if age_minutes < 0:
        return []

    if age_minutes > MAX_SERVER_AGE_HOURS * 60:
        return []

    candidates = []

    for event_name, interval in EVENTS:
        nearest_cycle = round(
            age_minutes / interval
        )

        if nearest_cycle < 1:
            continue

        target_minutes = nearest_cycle * interval
        difference = age_minutes - target_minutes

        if abs(difference) <= EVENT_WINDOW_MINUTES:
            candidates.append({
                "name": event_name,
                "cycle": nearest_cycle,
                "target_minutes": target_minutes,
                "minutes_from_target": difference,
            })

    return candidates


def event_time_description(event):
    difference = event["minutes_from_target"]

    if difference < 0:
        return (
            f"approximately "
            f"{abs(difference):.1f} min remaining"
        )

    if difference > 0:
        return (
            f"scheduled time passed "
            f"{difference:.1f} min ago"
        )

    return "at the scheduled time"