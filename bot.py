import discord
from discord.ext import tasks
import os
import asyncio
import datetime

TOKEN = os.getenv("DISCORD_TOKEN")

ROLE_ID = 1514285810889916426

VOICE_CHANNEL_IDS = [
    1512122067099844678,
    1512122115732668566,
    1512122153158316222,
    1512122189598687283,
    1514319861243707564,
]

PANEL_TEXT_CHANNEL_ID = 1520166885650333798

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.guilds = True

bot = discord.Client(intents=intents)

panel_message: discord.Message | None = None

# INTELLIGENTES CACHING: Speichert den letzten Zustand der Belegung
last_occupied_state = None


def check_channel_occupied(channel: discord.VoiceChannel, role_id: int) -> bool:
    for member in channel.members:
        if any(r.id == role_id for r in member.roles):
            return True
    return False


def build_embed(guild: discord.Guild, occupied_list: list, free_list: list, lines: list) -> discord.Embed:
    total = len([ch_id for ch_id in VOICE_CHANNEL_IDS if guild.get_channel(ch_id) is not None])
    num_occupied = len(occupied_list)

    if num_occupied == 0:
        ampel = "🟢 GRÜN — Alle Kanäle frei"
        color = discord.Color.green()
    elif num_occupied == total:
        ampel = "🔴 ROT — Alle Kanäle besetzt"
        color = discord.Color.red()
    else:
        ampel = "🟡 GELB — Teilweise besetzt"
        color = discord.Color.yellow()

    embed = discord.Embed(
        title="🎙️ Sprachkanal-Status",
        description="\n".join(lines),
        color=color,
    )
    embed.add_field(name="Gesamt-Status", value=ampel, inline=False)
    embed.add_field(
        name="Auslastung",
        value=f"{num_occupied} / {total} Kanäle belegt",
        inline=False,
    )
    embed.set_footer(text="Auto-Update aktiv")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    return embed


@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user} (ID: {bot.user.id})")
    await find_or_create_panel()
    update_panel.start()


async def find_or_create_panel():
    global panel_message, last_occupied_state

    text_channel = bot.get_channel(PANEL_TEXT_CHANNEL_ID)
    if text_channel is None:
        print(f"FEHLER: Text-Kanal {PANEL_TEXT_CHANNEL_ID} nicht gefunden.")
        return

    # Zustand ermitteln für den ersten Start
    guild = text_channel.guild
    occupied = []
    free = []
    lines = []
    
    for ch_id in VOICE_CHANNEL_IDS:
        channel = guild.get_channel(ch_id)
        if channel is None:
            lines.append(f"⚠️ Kanal `{ch_id}` nicht gefunden")
            continue
        is_occupied = check_channel_occupied(channel, ROLE_ID)
        status = "🔴 Belegt" if is_occupied else "🟢 Frei"
        lines.append(f"**{channel.name}** — {status}")
        if is_occupied:
            occupied.append(ch_id)
        else:
            free.append(ch_id)
            
    last_occupied_state = sorted(occupied)

    # Nach alter Nachricht suchen
    async for msg in text_channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            embed = msg.embeds[0]
            if embed.title and "Sprachkanal-Status" in embed.title:
                panel_message = msg
                print(f"Vorhandene Panel-Nachricht gefunden (ID: {msg.id}), wird initial editiert.")
                try:
                    # Einmalig beim Start updaten, falls blockiert fängt es der Try-Block ab
                    embed_obj = build_embed(guild, occupied, free, lines)
                    await panel_message.edit(embed=embed_obj)
                except discord.HTTPException:
                    print("⚠️ Altes Panel temporär von Discord rate-limited. Warte auf Freigabe...")
                return

    embed_obj = build_embed(guild, occupied, free, lines)
    panel_message = await text_channel.send(embed=embed_obj)
    print(f"Neue Panel-Nachricht erstellt (ID: {panel_message.id}).")


# Intervall auf 15 Sekunden erhöht gegen Rate-Limits
@tasks.loop(seconds=15)
async def update_panel():
    global panel_message, last_occupied_state

    if panel_message is None:
        return

    try:
        guild = panel_message.guild
        occupied = []
        free = []
        lines = []

        # Aktuelle Belegung prüfen
        for ch_id in VOICE_CHANNEL_IDS:
            channel = guild.get_channel(ch_id)
            if channel is None:
                lines.append(f"⚠️ Kanal `{ch_id}` nicht gefunden")
                continue

            is_occupied = check_channel_occupied(channel, ROLE_ID)
            status = "🔴 Belegt" if is_occupied else "🟢 Frei"
            lines.append(f"**{channel.name}** — {status}")

            if is_occupied:
                occupied.append(ch_id)
            else:
                free.append(ch_id)

        current_occupied_state = sorted(occupied)

        # INTELLIGENTES CACHING: Nur editieren, wenn sich die Liste der belegten Kanäle geändert hat!
        if current_occupied_state == last_occupied_state:
            return

        embed = build_embed(guild, occupied, free, lines)
        await panel_message.edit(embed=embed)
        last_occupied_state = current_occupied_state
        print("📝 Panel aktualisiert (Belegungsänderung erkannt).")
        
    except discord.NotFound:
        print("Panel-Nachricht wurde gelöscht. Erstelle neue...")
        panel_message = None
        await find_or_create_panel()
    except discord.HTTPException as e:
        # Falls es ein 429 ist, fängt der Bot es hier ab ohne das Log vollzuspammen
        if e.status == 429:
            pass
        else:
            print(f"HTTP-Fehler beim Editieren: {e}")
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")


@update_panel.before_loop
async def before_update_panel():
    await bot.wait_until_ready()


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN Umgebungsvariable ist nicht gesetzt!")
    bot.run(TOKEN)
