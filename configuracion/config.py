
import os
from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

BOSS_CHANNEL_ID = 1561558218751217664
RIFT_CHANNEL_ID = 1561212435744948368
ALERT_ROLE_ID = 1561702759550689411

# Juego ASURA
PLACE_ID = 13358463560

# Frecuencia de tareas
SCAN_SECONDS = 30
REPORT_SECONDS = 60

# Antigüedad y eventos
MAX_SERVER_AGE_HOURS = 48
EVENT_WINDOW_MINUTES = 5

RIFT_INTERVAL_MINUTES = 90
BOSS_INTERVAL_MINUTES = 120

# RoValra
AGE_REFRESH_SECONDS = 1800
MAX_AGE_CHECKS_PER_SCAN = 1
HTTP_TIMEOUT_SECONDS = 20
ROVALRA_RETRY_SECONDS = 900

ROVALRA_BASE_URL = "https://apis.rovalra.com"
ROVALRA_PROCESS_URL = f"{ROVALRA_BASE_URL}/process_servers"
ROVALRA_DETAILS_URL = f"{ROVALRA_BASE_URL}/v1/server_details"

# RoQoL
ROQOL_INVITE_API = "https://roqol.io/api/servers/invite"
ROQOL_AUTHORIZATION = os.getenv("ROQOL_AUTHORIZATION", "").strip()

# Roblox
ROBLOX_SERVERS_API = (
    f"https://games.roblox.com/v1/games/"
    f"{PLACE_ID}/servers/Public"
)

# Base de datos existente
DATABASE = "asura_servers.db"

if not DISCORD_TOKEN or not CHANNEL_ID:
    raise RuntimeError(
        "Configura DISCORD_TOKEN y CHANNEL_ID en tu archivo .env"
    )
