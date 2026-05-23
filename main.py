import discord
from discord import app_commands
from discord.ext import tasks
import requests
import json
import os
import re
from datetime import datetime

# ---------------- CONFIG ----------------

TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("BIBLE_API_KEY")

BIBLE_ID = "78a9f6124f344018-01"
SETTINGS_FILE = "settings.json"
VERSES_FILE = "verses.json"

# ---------------- SAFETY CHECKS ----------------

if not TOKEN:
    raise Exception("Missing DISCORD_TOKEN")

if not API_KEY:
    raise Exception("Missing BIBLE_API_KEY")

# ---------------- BOT SETUP ----------------

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---------------- FILE INIT ----------------

def ensure_files():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            f.write("{}")

ensure_files()

# ---------------- STORAGE ----------------

def load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except:
        return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_verses():
    if not os.path.exists(VERSES_FILE):
        raise Exception("verses.json missing")
    with open(VERSES_FILE, "r") as f:
        return json.load(f)

VERSES = None

# ---------------- DAILY LOGIC ----------------

def get_day_index():
    return datetime.now().timetuple().tm_yday

def get_daily_ref():
    global VERSES
    if VERSES is None:
        VERSES = load_verses()

    return VERSES[get_day_index() % len(VERSES)]

# ---------------- CLEAN ----------------

def clean_html(text):
    return re.sub(r"<.*?>", "", text).strip()

# ---------------- FORMAT ----------------

BOOK_NAMES = {
    "GEN": "Genesis","EXO": "Exodus","LEV": "Leviticus","NUM": "Numbers",
    "DEU": "Deuteronomy","PSA": "Psalms","PRO": "Proverbs","ISA": "Isaiah",
    "JER": "Jeremiah","MAT": "Matthew","MRK": "Mark","LUK": "Luke",
    "JHN": "John","ROM": "Romans"
}

def format_reference(ref):
    book, chapter, verse = ref.split(".")
    return f"{BOOK_NAMES.get(book, book)} {chapter}:{verse}"

# ---------------- API ----------------

def fetch_verse(ref):
    try:
        url = f"https://rest.api.bible/v1/bibles/{BIBLE_ID}/verses/{ref}?content-type=text"
        headers = {"api-key": API_KEY}

        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()

        return clean_html(r.json()["data"]["content"])

    except Exception as e:
        print("API error:", e)
        return f"Verse unavailable ({ref})"

# ---------------- MESSAGE ----------------

def make_message(ref, text):
    return (
        f"# 📖 Verse of the Day\n\n"
        f"{text}\n\n"
        f"### {format_reference(ref)} • NIV"
    )

# ---------------- COMMANDS ----------------

@tree.command(name="verse", description="Get today's Bible verse")
async def verse(interaction: discord.Interaction):
    await interaction.response.defer()

    ref = get_daily_ref()
    text = fetch_verse(ref)

    await interaction.followup.send(make_message(ref, text))

# ---------------- SET CHANNEL ----------------

@tree.command(name="setchannel", description="Set daily verse channel")
async def setchannel(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    data = load_settings()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["channel"] = str(interaction.channel.id)

    save_settings(data)

    await interaction.response.send_message("✅ Channel set")

# ---------------- SET TIME ----------------

@tree.command(name="settime", description="Set daily verse time")
async def settime(interaction: discord.Interaction, hour: int, minute: int):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return await interaction.response.send_message("❌ Invalid time", ephemeral=True)

    data = load_settings()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})
    data[gid]["hour"] = hour
    data[gid]["minute"] = minute

    save_settings(data)

    await interaction.response.send_message(f"✅ Time set {hour:02}:{minute:02}")

# ---------------- DAILY LOOP ----------------

last_sent = None

@tasks.loop(minutes=1)
async def daily_verse():

    global last_sent
    now = datetime.now()

    if last_sent == (now.day, now.hour, now.minute):
        return

    data = load_settings()

    for guild_id, cfg in data.items():

        try:
            if not cfg.get("channel"):
                continue

            if now.hour != cfg.get("hour", 0) or now.minute != cfg.get("minute", 0):
                continue

            channel = client.get_channel(int(cfg["channel"]))
            if not channel:
                continue

            ref = get_daily_ref()
            text = fetch_verse(ref)

            msg = make_message(ref, text)

            # ---------------- FIXED PING ----------------
            await channel.send(f"@everyone\n\n{msg}")

            last_sent = (now.day, now.hour, now.minute)

        except Exception as e:
            print("Loop error:", e)

# ---------------- READY ----------------

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    await tree.sync()
    daily_verse.start()
    print("Bot ready")

# ---------------- RUN ----------------

client.run(TOKEN)
