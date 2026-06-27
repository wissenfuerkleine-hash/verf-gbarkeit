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

const UPDATE_INTERVAL = 30000; // Alle 30 Sekunden prüfen
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
let lastEmbedDescription = ""; // Caching-Variable für den reinen Text-Vergleich

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

// Generiert NUR den reinen Textinhalt (ohne Zeitstempel) für den exakten Vergleich
function generateDescriptionText() {
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

  const supportStatusText = hasSupportStaff 
    ? "🟢 **Support:** Besetzt & bereit" 
    : "🔴 **Support:** Zurzeit nicht besetzt";

  return `${text}\n\n---\n\n${supportStatusText}`;
}

// Baut das Embed und setzt den Zeitstempel NUR bei echtem Update
function buildEmbed(description) {
  return new EmbedBuilder()
    .setTitle("📊 Bot Status Panel")
    .setColor(0x00ff00)
    .setDescription(description)
    .setFooter({ text: "Letztes Status-Update" })
    .setTimestamp(); // Zeitstempel wird jetzt fixiert für diese Version generiert
}

/* =========================
   PANEL INITIALISIEREN / BEREINIGEN
========================= */

async function initPanel(channel) {
  const description = generateDescriptionText();
  lastEmbedDescription = description;

  // Letzte 20 Nachrichten holen und alte Panels löschen, um Spam zu vermeiden
  const messages = await channel.messages.fetch({ limit: 20 });
  const oldPanel = messages.find(m => m.author.id === client.user.id && m.embeds.length > 0);

  if (oldPanel) {
    panelMessage = oldPanel;
    await panelMessage.edit({
      embeds: [buildEmbed(description)]
    });
    console.log("🔄 Altes Panel gefunden und aktualisiert.");
  } else {
    panelMessage = await channel.send({
      embeds: [buildEmbed(description)]
    });
    console.log("✨ Neues Panel gepostet.");
  }
}

/* =========================
   PANEL UPDATEN
========================= */

async function updatePanel() {
  if (!panelMessage) return;

  const currentDescription = generateDescriptionText();

  // STRENGER VERGLEICH: Wenn der Text exakt identisch ist, brechen wir SOFORT ab!
  if (currentDescription === lastEmbedDescription) {
    return; 
  }

  try {
    await panelMessage.edit({
      embeds: [buildEmbed(currentDescription)]
    });
    lastEmbedDescription = currentDescription; // Cache aktualisieren
    console.log("📝 Panel erfolgreich aktualisiert, da sich ein Status geändert hat.");
  } catch (error) {
    console.error("Fehler beim Editieren des Panels:", error);
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