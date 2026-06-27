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
WARTERAUM_ID = 1512120421007495248            
VOICE_CHANNEL_IDS = [
    1512122067099844678,
    1512122115732668566,
    1512122153158316222,
    1512122189598687283,
    1514319861243707564,
]

PANEL_TEXT_CHANNEL_ID = 1520166885650333798

intents = discord.Intents.all() 
bot = discord.Client(intents=intents)

panel_message: discord.Message | None = None
last_state_hash = ""  

# LIVE-SPEICHER & HISTORIE
warteraum_join_times = {}
recent_wait_times = []  # Speichert die Sekunden der letzten X Support-Fälle
GLOBAL_AVERAGE_TEXT = "0 Sek."  # Behält den letzten Wert im Speicher


def get_channel_status(channel: discord.VoiceChannel) -> str:
    """Ermittelt den Status eines einzelnen Support-Kanals anhand der Rollen."""
    has_team = False
    has_user = False

    for member in channel.members:
        member_roles = [r.id for r in member.roles]
        if TEAM_ROLE_ID in member_roles:
            has_team = True
        if USER_NEED_HELP_ROLE_ID in member_roles:
            has_user = True
    
    if has_team and has_user:
        return "🔴 Besetzt (Bürger drin)"
    elif has_team:
        return "🟢 Frei (Teamler drin)"
    elif has_user:
        return "🔴 Besetzt (Bürger drin)"  
    else:
        return "⚪ Unbesetzt (Niemand drin)"


def update_average_wait_time(guild: discord.Guild):
    """Berechnet die durchschnittliche Wartezeit und hält sie im Speicher."""
    global GLOBAL_AVERAGE_TEXT
    
    warteraum = guild.get_channel(WARTERAUM_ID)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Fall A: Es befinden sich aktuell User im Warteraum -> Nutze Live-Daten
    if warteraum and any(USER_NEED_HELP_ROLE_ID in [r.id for r in m.roles] for m in warteraum.members):
        total_wait_seconds = 0
        count = 0
        for member in warteraum.members:
            if USER_NEED_HELP_ROLE_ID in [r.id for r in member.roles]:
                join_time = warteraum_join_times.get(member.id, now)
                total_wait_seconds += max(0, (now - join_time).total_seconds())
                count += 1
        avg_seconds = total_wait_seconds / count

    # Fall B: Warteraum ist leer -> Nutze den Durchschnitt der letzten abgeholten User
    elif recent_wait_times:
        avg_seconds = sum(recent_wait_times) / len(recent_wait_times)
    else:
        GLOBAL_AVERAGE_TEXT = "0 Sek."
        return

    # Text formatieren
    if avg_seconds < 60:
        GLOBAL_AVERAGE_TEXT = f"{int(avg_seconds)} Sek."
    else:
        mins = int(avg_seconds // 60)
        secs = int(avg_seconds % 60)
        GLOBAL_AVERAGE_TEXT = f"{mins} Min. {secs} Sek."


def build_embed(guild: discord.Guild, lines: list, any_team_online: bool) -> discord.Embed:
    if any_team_online:
        ampel = "🟢 ONLINE — Support-Team ist im Dienst"
        color = discord.Color.green()
    else:
        ampel = "🔴 OFFLINE — Zurzeit kein Supporter im Dienst"
        color = discord.Color.red()

    # Holt den gespeicherten/aktuellen Durchschnittstext
    update_average_wait_time(guild)
    warteraum = guild.get_channel(WARTERAUM_ID)
    warteraum_count = len(warteraum.members) if warteraum else 0

    embed = discord.Embed(
        title="🎙️ BRP Support-Verfügbarkeit",
        description="\n".join(lines),
        color=color,
    )
    embed.add_field(name="Team-Status", value=ampel, inline=False)
    embed.add_field(name="⏳ Warteraum Wartezeit (Ø)", value=GLOBAL_AVERAGE_TEXT, inline=True)
    embed.add_field(name="👥 User im Warteraum", value=f"{warteraum_count} User", inline=True)

    embed.set_footer(text="Auto-Update aktiv (Sekundengenaue Messung)")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    return embed


@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user} (ID: {bot.user.id})")
    
    text_channel = bot.get_channel(PANEL_TEXT_CHANNEL_ID)
    if text_channel:
        warteraum = text_channel.guild.get_channel(WARTERAUM_ID)
        if warteraum:
            now = datetime.datetime.now(datetime.timezone.utc)
            for member in warteraum.members:
                if USER_NEED_HELP_ROLE_ID in [r.id for r in member.roles]:
                    warteraum_join_times[member.id] = now

    await find_or_create_panel()
    update_panel.start()


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Überwacht live Beitritte und berechnet beim Verlassen die historische Wartezeit."""
    global recent_wait_times
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # User betritt den Warteraum
    if after.channel and after.channel.id == WARTERAUM_ID:
        if USER_NEED_HELP_ROLE_ID in [r.id for r in member.roles]:
            if member.id not in warteraum_join_times:
                warteraum_join_times[member.id] = now
            
    # User verlässt den Warteraum (wird z.B. vom Dispatcher verschoben)
    if before.channel and before.channel.id == WARTERAUM_ID:
        if after.channel is None or after.channel.id != WARTERAUM_ID:
            join_time = warteraum_join_times.pop(member.id, None)
            
            # Wenn er die Bürger-Rolle hatte, loggen wir seine echte Wartezeit in die Historie ein
            if join_time and USER_NEED_HELP_ROLE_ID in [r.id for r in member.roles]:
                wait_duration = (now - join_time).total_seconds()
                # Nur loggen, wenn er länger als 1 Sekunde drin war (gegen Fehlsprünge)
                if wait_duration > 1:
                    recent_wait_times.append(wait_duration)
                    # Wir behalten nur die letzten 10 Support-Fälle für einen aktuellen Durchschnitt
                    if len(recent_wait_times) > 10:
                        recent_wait_times.pop(0)


async def find_or_create_panel():
    global panel_message, last_state_hash

    text_channel = bot.get_channel(PANEL_TEXT_CHANNEL_ID)
    if text_channel is None:
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
        
        if "🟢 Frei" in status or "Besetzt" in status:
            if any(TEAM_ROLE_ID in [r.id for r in m.roles] for m in channel.members):
                any_team_online = True

    warteraum = guild.get_channel(WARTERAUM_ID)
    state_str += f"w:{len(warteraum.members) if warteraum else 0}"
    last_state_hash = state_str

    async for msg in text_channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            embed = msg.embeds[0]
            if embed.title and "Support-Verfügbarkeit" in embed.title:
                panel_message = msg
                try:
                    embed_obj = build_embed(guild, lines, any_team_online)
                    await panel_message.edit(embed=embed_obj)
                except discord.HTTPException:
                    pass
                return

    embed_obj = build_embed(guild, lines, any_team_online)
    panel_message = await text_channel.send(embed=embed_obj)


@tasks.loop(seconds=5)
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

            if "🟢 Frei" in status or "Besetzt" in status:
                if any(TEAM_ROLE_ID in [r.id for r in m.roles] for m in channel.members):
                    any_team_online = True

        warteraum = guild.get_channel(WARTERAUM_ID)
        warteraum_count = len(warteraum.members) if warteraum else 0
        
        # Den aktuellen Durchschnitt berechnen, damit er in den Cache-String fließt
        update_average_wait_time(guild)
        state_str += f"w:{warteraum_count}|time:{GLOBAL_AVERAGE_TEXT}"

        if state_str == last_state_hash:
            return

        embed = build_embed(guild, lines, any_team_online)
        await panel_message.edit(embed=embed)
        last_state_hash = state_str
        print("📝 Panel aktualisiert (Durchschnitt gehalten).")
        
    except discord.NotFound:
        panel_message = None
        await find_or_create_panel()
    except discord.HTTPException as e:
        if e.status == 429:
            pass
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")


@update_panel.before_loop
async def before_update_panel():
    await bot.wait_until_ready()


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN Umgebungsvariable ist nicht gesetzt!")
    bot.run(TOKEN)
