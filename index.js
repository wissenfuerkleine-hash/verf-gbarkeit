import express from "express";
import { Client, GatewayIntentBits, EmbedBuilder } from "discord.js";

/* =========================
   SETUP
========================= */

const app = express();
app.use(express.json());

// GuildVoiceStates ist notwendig, um Mitglieder in den Sprachkanälen zu sehen
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildVoiceStates
  ]
});

/* =========================
   CONFIG
========================= */

const DISCORD_TOKEN = process.env.DISCORD_TOKEN;
const CHANNEL_ID = "1520386261284688004"; // ID des Textkanals für das Panel

const UPDATE_INTERVAL = 30000; // Panel Update (Alle 30 Sekunden gegen Rate-Limits)
const CHECK_INTERVAL = 10000;  // Down Check (Alle 10 Sekunden)
const TIMEOUT = 90 * 1000;     // 90 Sekunden ohne API-Meldung = BOT DOWN

// HIER DIE 5 IDS DEINER SUPPORT-SPRACHKANÄLE EINTRAGEN
const SUPPORT_CHANNEL_IDS = [
  "KANAL_ID_1",
  "KANAL_ID_2",
  "KANAL_ID_3",
  "KANAL_ID_4",
  "KANAL_ID_5"
];
const SUPPORT_ROLE_ID = "1515119690219786250"; // ID der Support-Rolle

/* =========================
   STORAGE
========================= */

const botStatus = {};
let panelMessage = null;
let lastEmbedDescription = ""; // Speichert den letzten Textzustand (Intelligentes Caching)

/* =========================
   API (Bots senden Status hierhin)
========================= */

app.post("/status", (req, res) => {
  const { name, status } = req.body;

  botStatus[name] = {
    status: status || "active",
    lastSeen: Date.now()
  };

  res.sendStatus(200);
});

/* =========================
   AUTO DOWN CHECK
========================= */

function checkDownBots() {
  const now = Date.now();

  for (const name in botStatus) {
    const bot = botStatus[name];

    if (now - bot.lastSeen > TIMEOUT) {
      bot.status = "down";
    }
  }
}

/* =========================
   EMBED BUILDER LOGIC
========================= */

// Generiert den reinen Textinhalt für das Embed
function generateDescriptionText() {
  // 1. Bots auflisten
  const text = Object.entries(botStatus)
    .map(([name, data]) => {
      const emoji =
        data.status === "active" ? "🟢" :
        data.status === "down" ? "🔴" :
        data.status === "maintenance" ? "🛠" :
        "🟡";

      return `${emoji} **${name}**`;
    })
    .join("\n") || "Keine Daten";

  // 2. Die 5 Support-Kanäle prüfen
  let hasSupportStaff = false;

  for (const channelId of SUPPORT_CHANNEL_IDS) {
    try {
      const supportChannel = client.channels.cache.get(channelId);
      
      if (supportChannel && supportChannel.isVoiceBased()) {
        const staffInChannel = supportChannel.members.some(member => 
          member.roles.cache.has(SUPPORT_ROLE_ID)
        );

        if (staffInChannel) {
          hasSupportStaff = true;
          break; // Einer gefunden, Schleife abbrechen
        }
      }
    } catch (error) {
      // Fehler silent abfangen, falls ein Kanal mal nicht im Cache ist
    }
  }

  const supportStatusText = hasSupportStaff 
    ? "🟢 **Support:** Besetzt & bereit" 
    : "🔴 **Support:** Zurzeit nicht besetzt";

  return `${text}\n\n---\n\n${supportStatusText}`;
}

// Baut das finale Embed-Objekt
function buildEmbed(description) {
  return new EmbedBuilder()
    .setTitle("📊 Bot Status Panel")
    .setColor(0x00ff00)
    .setDescription(description)
    .setFooter({ text: "Auto-Update aktiv" })
    .setTimestamp();
}

/* =========================
   PANEL ERSTELLEN
========================= */

async function createPanel(channel) {
  const description = generateDescriptionText();
  lastEmbedDescription = description; // Start-Zustand merken

  panelMessage = await channel.send({
    embeds: [buildEmbed(description)]
  });
}

/* =========================
   PANEL UPDATEN
========================= */

async function updatePanel() {
  if (!panelMessage) return;

  const currentDescription = generateDescriptionText();

  // INTELLIGENTES CACH