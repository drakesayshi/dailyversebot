import discord
from discord import app_commands
from discord.ext import tasks
import requests
import json
import os
import re
import random
from datetime import datetime

# ---------------- CONFIG ----------------

TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("BIBLE_API_KEY")

BIBLE_ID = "78a9f6124f344018-01"
SETTINGS_FILE = "settings.json"
VERSES_FILE = "verses.json"

# ---------------- SAFETY ----------------

if not TOKEN:
    raise Exception("Missing DISCORD_TOKEN")

if not API_KEY:
    raise Exception("Missing BIBLE_API_KEY")

# ---------------- BOT ----------------

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---------------- GLOBAL STATE ----------------

DAY_OVERRIDE = None

# ---------------- FILE INIT ----------------

def ensure_files():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            f.write("{}")

    if not os.path.exists(VERSES_FILE):
        raise Exception("verses.json missing")

ensure_files()

# ---------------- SETTINGS ----------------

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

# ---------------- VERSES + SHUFFLE SYSTEM ----------------

VERSES = None
SHUFFLED_VERSES = None
SHUFFLE_DAY = None

def load_verses():
    with open(VERSES_FILE, "r") as f:
        return json.load(f)

def get_day_index():
    global DAY_OVERRIDE
    if DAY_OVERRIDE is not None:
        return DAY_OVERRIDE
    return datetime.now().timetuple().tm_yday

def get_shuffled_verses():
    global VERSES, SHUFFLED_VERSES, SHUFFLE_DAY

    if VERSES is None:
        VERSES = load_verses()

    today_year = datetime.now().year

    # reshuffle once per year
    if SHUFFLED_VERSES is None or SHUFFLE_DAY != today_year:
        SHUFFLED_VERSES = VERSES[:]
        random.shuffle(SHUFFLED_VERSES)
        SHUFFLE_DAY = today_year

    return SHUFFLED_VERSES

def get_daily_ref():
    verses = get_shuffled_verses()
    day = get_day_index()
    return verses[day % len(verses)]

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

# ---------------- SETTINGS ----------------

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

@tree.command(name="setpingrole", description="Set ping role")
async def setpingrole(interaction: discord.Interaction, role: discord.Role):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    data = load_settings()
    gid = str(interaction.guild.id)

    data.setdefault(gid, {})

    # ALWAYS store raw ID (int, not string)
    data[gid]["ping_role"] = role.id

    save_settings(data)

    await interaction.response.send_message(f"✅ Ping role set: {role.mention}")

# ---------------- DAY CONTROL ----------------

@tree.command(name="setday", description="Override verse day (testing)")
async def setday(interaction: discord.Interaction, day: int):

    global DAY_OVERRIDE

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    DAY_OVERRIDE = day
    await interaction.response.send_message(f"✅ Day override set to {day}")

@tree.command(name="resetday", description="Reset day override")
async def resetday(interaction: discord.Interaction):

    global DAY_OVERRIDE

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    DAY_OVERRIDE = None
    await interaction.response.send_message("✅ Day reset")

# ---------------- LOOP ----------------

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

            ping = f"<@&{cfg['ping_role']}>\n\n" if cfg.get("ping_role") else ""

            await channel.send(ping + msg)

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
