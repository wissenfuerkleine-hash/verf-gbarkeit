import express from "express";
import { Client, GatewayIntentBits, EmbedBuilder } from "discord.js";

/* =========================
   SETUP
========================= */

const app = express();
app.use(express.json());

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
const CHANNEL_ID = "1520386261284688004"; 

const UPDATE_INTERVAL = 30000; // Alle 30 Sekunden prüfen gegen Rate-Limits
const CHECK_INTERVAL = 10000;  
const TIMEOUT = 90 * 1000;     

// HIER DIE 5 IDS DEINER SUPPORT-SPRACHKANÄLE EINTRAGEN
const SUPPORT_CHANNEL_IDS = [
  "KANAL_ID_1",
  "KANAL_ID_2",
  "KANAL_ID_3",
  "KANAL_ID_4",
  "KANAL_ID_5"
];
const SUPPORT_ROLE_ID = "1515119690219786250"; 

/* =========================
   STORAGE
========================= */

const botStatus = {};
let panelMessage = null;
let lastEmbedDescription = ""; 
let lastSupportState = null; // Speichert, ob zuletzt besetzt (true) oder unbesetzt (false) war

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

// Gibt zurück, ob mindestens ein Supporter in den Kanälen ist
function checkSupportStaff() {
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
          break; 
        }
      }
    } catch (error) {
      // Fehler ignorieren
    }
  }
  return hasSupportStaff;
}

// Generiert den reinen Beschreibungstext
function generateDescriptionText(hasSupportStaff) {
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

  const supportStatusText = hasSupportStaff 
    ? "🟢 **Support:** Besetzt & bereit" 
    : "🔴 **Support:** Zurzeit nicht besetzt";

  return `${text}\n\n---\n\n${supportStatusText}`;
}

// Baut das Embed mit dynamischer Farbe (Rot = Unbesetzt, Grün = Besetzt)
function buildEmbed(description, hasSupportStaff) {
  const embedColor = hasSupportStaff ? 0x00ff00 : 0xff0000; // Grün wenn besetzt, Rot wenn unbesetzt

  return new EmbedBuilder()
    .setTitle("📊 Bot Status Panel")
    .setColor(embedColor)
    .setDescription(description)
    .setFooter({ text: "Auto-Update aktiv" })
    .setTimestamp();
}

/* =========================
   PANEL INITIALISIEREN / BEREINIGEN
========================= */

async function initPanel(channel) {
  const hasStaff = checkSupportStaff();
  const description = generateDescriptionText(hasStaff);
  
  lastEmbedDescription = description;
  lastSupportState = hasStaff;

  try {
    const messages = await channel.messages.fetch({ limit: 20 });
    const oldPanel = messages.find(m => m.author.id === client.user.id && m.embeds.length > 0);

    if (oldPanel) {
      panelMessage = oldPanel;
      // Versuche das alte Panel zu editieren
      await panelMessage.edit({
        embeds: [buildEmbed(description, hasStaff)]
      });
      console.log("🔄 Altes Panel erfolgreich aktualisiert.");
    } else {
      throw new Error("Kein altes Panel gefunden, erstelle neues.");
    }
  } catch (err) {
    // Falls das alte Panel blockiert ist (429) oder nicht existiert: Löschen & Neu senden!
    console.log("⚠️ Altes Panel blockiert oder nicht lesbar. Sende ein komplett neues Panel...");
    
    try {
      if (panelMessage) await panelMessage.delete().catch(() => {});
    } catch (e) {}

    panelMessage = await channel.send({
      embeds: [buildEmbed(description, hasStaff)]
    });
    console.log("✨ Neues Panel frisch gepostet.");
  }
}

/* =========================
   PANEL UPDATEN
========================= */

async function updatePanel() {
  if (!panelMessage) return;

  const hasStaff = checkSupportStaff();
  const currentDescription = generateDescriptionText(hasStaff);

  // Caching: Nur updaten, wenn sich der Text ODER die Farbe (Support-Status) geändert hat!
  if (currentDescription === lastEmbedDescription && hasStaff === lastSupportState) {
    return; 
  }

  try {
    await panelMessage.edit({
      embeds: [buildEmbed(currentDescription, hasStaff)]
    });
    lastEmbedDescription = currentDescription;
    lastSupportState = hasStaff;
    console.log("📝 Panel aktualisiert (Status-Änderung erkannt).");
  } catch (error) {
    console.error("Fehler beim Editieren, erstelle Panel neu...", error.message);
    // Bei hartnäckigem Rate-Limit das Panel neu aufbauen
    const channel = panelMessage.channel;
    await initPanel(channel);
  }
}

/* =========================
   DISCORD READY
========================= */

client.once("ready", async () => {
  console.log(`✅ Logged in as ${client.user.tag}`);

  try {
    const channel = await client.channels.fetch(CHANNEL_ID);
    await initPanel(channel);
  } catch (err) {
    console.error("Kanal konnte nicht geladen werden:", err);
  }

  setInterval(() => {
    checkDownBots();
  }, CHECK_INTERVAL);

  setInterval(() => {
    updatePanel();
  }, UPDATE_INTERVAL);
});

/* =========================
   START SERVER
========================= */

app.listen(3000, () => {
  console.log("🚀 API läuft auf Port 3000");
});

/* =========================
   LOGIN
========================= */

client.login(DISCORD_TOKEN);