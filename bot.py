import discord
from discord.ext import tasks
import os
import asyncio
import datetime

TOKEN = os.getenv("DISCORD_TOKEN")

# ROLLEN-IDS
USER_NEED_HELP_ROLE_ID = 1514285810889916426  # User / Bürger braucht Hilfe
TEAM_ROLE_ID = 1515119690219786250            # Support-Teammitglied

# KANÄLE
WARTERAUM_ID = 1512120421007495248            # Nur hier wird die Wartezeit gemessen!
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
last_state_hash = ""  # Für das intelligente Caching


def get_channel_status(channel: discord.VoiceChannel) -> str:
    """Ermittelt den Status eines einzelnen Support-Kanals anhand der Rollen."""
    has_team = any(any(r.id == TEAM_ROLE_ID for r in m.roles) for m in channel.members)
    has_user = any(any(r.id == USER_NEED_HELP_ROLE_ID for r in m.roles) for m in channel.members)
    
    if has_team and has_user:
        return "🔴 Besetzt (Bürger drin)"
    elif has_team:
        return "🟢 Frei (Teamler drin)"
    else:
        return "⚪ Unbesetzt (Niemand drin)"


def calculate_warteraum_wait_time(guild: discord.Guild) -> str:
    """Berechnet die durchschnittliche Wartezeit NUR für den Warteraum."""
    warteraum = guild.get_channel(WARTERAUM_ID)
    if not warteraum or not warteraum.members:
        return "0 Minuten"
    
    now = datetime.datetime.now(datetime.timezone.utc)
    total_wait_seconds = 0
    count = 0
    
    for member in warteraum.members:
        # Wir messen nur Bürger im Warteraum
        if any(r.id == USER_NEED_HELP_ROLE_ID for r in member.roles):
            join_time = None
            if member.voice:
                if hasattr(member.voice, 'requested_to_speak_at') and member.voice.requested_to_speak_at:
                    join_time = member.voice.requested_to_speak_at
            
            # Fallback für normale Voice-Channels: 
            # Wenn kein genauer Timestamp existiert, rechnen wir mit 2 Minuten pro wartendem User.
            if not join_time:
                join_time = now - datetime.timedelta(minutes=2)
                
            wait_duration = (now - join_time).total_seconds()
            total_wait_seconds += max(0, wait_duration)
            count += 1
            
    if count == 0:
        return "0 Minuten"
        
    avg_minutes = (total_wait_seconds / count) / 60
    return f"{round(avg_minutes, 1)} Minuten"


def build_embed(guild: discord.Guild, lines: list, any_team_online: bool) -> discord.Embed:
    if any_team_online:
        ampel = "🟢 ONLINE — Support-Team ist im Dienst"
        color = discord.Color.green()
    else:
        ampel = "🔴 OFFLINE — Zurzeit kein Supporter im Dienst"
        color = discord.Color.red()

    # Berechne Werte für den Warteraum
    avg_wait = calculate_warteraum_wait_time(guild)
    warteraum = guild.get_channel(WARTERAUM_ID)
    warteraum_count = len(warteraum.members) if warteraum else 0

    embed = discord.Embed(
        title="🎙️ BRP Support-Verfügbarkeit",
        description="\n".join(lines),
        color=color,
    )
    embed.add_field(name="Team-Status", value=ampel, inline=False)
    embed.add_field(name="⏳ Warteraum Wartezeit", value=avg_wait, inline=True)
    embed.add_field(name="👥 User im Warteraum", value=f"{warteraum_count} User", inline=True)

    embed.set_footer(text="Auto-Update aktiv (Änderungsprüfung)")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    return embed


@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user} (ID: {bot.user.id})")
    await find_or_create_panel()
    update_panel.start()


async def find_or_create_panel():
    global panel_message, last_state_hash

    text_channel = bot.get_channel(PANEL_TEXT_CHANNEL_ID)
    if text_channel is None:
        print(f"FEHLER: Text-Kanal {PANEL_TEXT_CHANNEL_ID} nicht gefunden.")
        return

    guild = text_channel.guild
    lines = []
    any_team_online = False
    state_str = ""

    for ch_id in VOICE_CHANNEL_IDS:
        channel = guild.get_channel(ch_id)
        if channel is None:
            lines.append(f"⚠️ Kanal `{ch_id}` nicht gefunden")
            continue
        
        status = get_channel_status(channel)
        lines.append(f"**{channel.name}** — {status}")
        state_str += f"{ch_id}:{status}|"
        
        # Ein Teamler ist im Dienst, wenn ein Kanal "Frei" (Teamler drin) oder "Besetzt" (Teamler + Bürger) ist
        if "🟢 Frei" in status or "🔴 Besetzt" in status:
            any_team_online = True

    warteraum = guild.get_channel(WARTERAUM_ID)
    state_str += f"w:{len(warteraum.members) if warteraum else 0}"
    last_state_hash = state_str

    async for msg in text_channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            embed = msg.embeds[0]
            if embed.title and "Support-Verfügbarkeit" in embed.title:
                panel_message = msg
                print(f"Vorhandene Panel-Nachricht gefunden (ID: {msg.id}), wird initial editiert.")
                try:
                    embed_obj = build_embed(guild, lines, any_team_online)
                    await panel_message.edit(embed=embed_obj)
                except discord.HTTPException:
                    print("⚠️ Altes Panel wird von Discord reguliert. Cooldown läuft...")
                return

    embed_obj = build_embed(guild, lines, any_team_online)
    panel_message = await text_channel.send(embed=embed_obj)
    print(f"Neue Panel-Nachricht erstellt (ID: {panel_message.id}).")


@tasks.loop(seconds=15)
async def update_panel():
    global panel_message, last_state_hash

    if panel_message is None:
        return

    try:
        guild = panel_message.guild
        lines = []
        any_team_online = False
        state_str = ""

        for ch_id in VOICE_CHANNEL_IDS:
            channel = guild.get_channel(ch_id)
            if channel is None:
                lines.append(f"⚠️ Kanal `{ch_id}` nicht gefunden")
                continue

            status = get_channel_status(channel)
            lines.append(f"**{channel.name}** — {status}")
            state_str += f"{ch_id}:{status}|"

            if "🟢 Frei" in status or "🔴 Besetzt" in status:
                any_team_online = True

        warteraum = guild.get_channel(WARTERAUM_ID)
        warteraum_count = len(warteraum.members) if warteraum else 0
        state_str += f"w:{warteraum_count}"

        # INTELLIGENTES CACHING: Nur editieren, wenn sich optisch wirklich etwas geändert hat!
        if state_str == last_state_hash:
            return

        embed = build_embed(guild, lines, any_team_online)
        await panel_message.edit(embed=embed)
        last_state_hash = state_str
        print("📝 Panel aktualisiert (Statusänderung registriert).")
        
    except discord.NotFound:
        panel_message = None
        await find_or_create_panel()
    except discord.HTTPException as e:
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
