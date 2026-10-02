// Thin WhatsApp connection layer.
// All "thinking" (RAG, LLM, STT, TTS, vision) happens in the Python backend.
// This file only: receives messages, forwards them, sends back the reply.

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const axios = require("axios");
const path = require("path");
const { startBridgeApi } = require("./bridge_api");

// Load the SAME .env file the Python backend uses, from the project root
// (one level up from whatsapp-bridge/).
require("dotenv").config({ path: path.resolve(__dirname, "..", ".env") });

// PHASE 1: leave this true to test the WhatsApp connection alone, with no
// Python backend involved — it just echoes whatever you send back to you.
// PHASE 2: flip to false once main.py is running, to route through the
// real agent instead.
const ECHO_ONLY = false;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000/webhook";
const ALLOW_GROUPS = (process.env.ALLOW_GROUPS || "false").toLowerCase() === "true";
const ALLOWED_CONTACTS = (process.env.ALLOWED_CONTACTS || "")
  .split(",")
  .map((c) => c.trim())
  .filter(Boolean);

// Applied BEFORE anything else, in both echo mode and real mode.
// Some contacts show up as an opaque "@lid" privacy ID instead of their
// real phone number ("@c.us") — this resolves those back to a phone
// number first, so ALLOWED_CONTACTS only ever needs to list phone numbers.
async function isAllowed(msg) {
  const from = msg.from;
  if (from.endsWith("@g.us") && !ALLOW_GROUPS) return false;
  if (ALLOWED_CONTACTS.length === 0) return true; // open — fine for now, tighten before going live

  let number = from.split("@")[0];

  if (from.endsWith("@lid")) {
    try {
      const contact = await msg.getContact();
      if (contact && contact.number) {
        number = contact.number.replace(/\D/g, ""); // digits only
      }
    } catch (err) {
      console.error("Could not resolve @lid contact to a phone number:", err.message);
      // falls through and checks the raw @lid id below, as a last resort
    }
  }

  return ALLOWED_CONTACTS.includes(number);
}

const puppeteerConfig = {
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--no-zygote",
  ],
};
if (process.env.PUPPETEER_EXECUTABLE_PATH) {
  // Only override if you explicitly set this — otherwise puppeteer uses
  // its own bundled Chromium, which already downloaded successfully.
  puppeteerConfig.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
}

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: puppeteerConfig,
});

client.on("qr", (qr) => {
  console.log("Scan this QR code with WhatsApp > Linked devices:");
  qrcode.generate(qr, { small: true });
});

// client.on("ready", () => {
//   console.log(`WhatsApp bridge is ready. ECHO_ONLY = ${ECHO_ONLY}`);
// });
client.on("ready", () => {
  console.log(`WhatsApp bridge is ready. ECHO_ONLY = ${ECHO_ONLY}`);
  startBridgeApi(client);
});

client.on("message", async (msg) => {
  try {
    if (msg.fromMe) {
      console.log(`[BLOCKED - fromMe] ${msg.from}: ${msg.body}`);
      return;
    }
    if (!(await isAllowed(msg))) {
      console.log(`[BLOCKED - not allowed] ${msg.from}: ${msg.body}`);
      return;
    }
    console.log(`[ALLOWED] ${msg.from}: ${msg.body}`);

    if (ECHO_ONLY) {
      await client.sendMessage(msg.from, `echo: ${msg.body}`);
      return;
    }
      const payload = {
        from: msg.from,
        body: msg.body || "",
        type: "text",
        media_base64: null,
        mimetype: null,
      };  

      console.log(`[DEBUG] type=${msg.type} hasMedia=${msg.hasMedia}`);

      if (msg.hasMedia && (msg.type === "ptt" || msg.type === "audio" || msg.type === "image")) {
        try {
          const media = await msg.downloadMedia();
          if (!media || !media.data) throw new Error("downloadMedia returned nothing");
          payload.media_base64 = media.data;
          payload.mimetype = media.mimetype;
          payload.type = msg.type === "image" ? "image" : "voice";
        } catch (err) {
          console.error("downloadMedia failed:", err.stack || err);
          if (!payload.body) return; // voice note or image with no text: nothing to answer
          // image with a caption: fall through and answer the text only
        }
      }

      const { data } = await axios.post(BACKEND_URL, payload, { timeout: 180000 });

      if (data.action === "send") {
        if (data.reply_audio_base64) {
          const voiceMedia = new MessageMedia("audio/ogg", data.reply_audio_base64);
          await client.sendMessage(msg.from, voiceMedia, { sendAudioAsVoice: true });
        } else if (data.reply_text) {
          await client.sendMessage(msg.from, data.reply_text);
        }
      } else if (data.action === "hold") {
        console.log(`Held for approval: "${data.reply_text}" — check your dashboard.`);
      }
    }   catch (err) {
      console.error("Error handling message:", err.stack || err);
    } 
});

//     const payload = {
//       from: msg.from,
//       body: msg.body || "",
//       type: "text",
//       media_base64: null,
//       mimetype: null,
//     };

//     if (msg.hasMedia && (msg.type === "ptt" || msg.type === "audio" || msg.type === "image")) {
//       const media = await msg.downloadMedia();
//       payload.media_base64 = media.data;
//       payload.mimetype = media.mimetype;
//       payload.type = msg.type === "image" ? "image" : "voice";
//     }

//     const { data } = await axios.post(BACKEND_URL, payload, { timeout: 60000 });

//     if (data.action === "send") {
//       if (data.reply_audio_base64) {
//         const voiceMedia = new MessageMedia("audio/ogg", data.reply_audio_base64);
//         await client.sendMessage(msg.from, voiceMedia, { sendAudioAsVoice: true });
//       } else if (data.reply_text) {
//         await client.sendMessage(msg.from, data.reply_text);
//       }
//     } else if (data.action === "hold") {
//       console.log(`Held for approval: "${data.reply_text}" — check your dashboard.`);
//     } else {
//       // "ignore" — not on the allowlist, or a group chat with ALLOW_GROUPS off.
//       // No reply, no log spam, nothing sent back.
//     }
//   } catch (err) {
//     console.error("Error handling message:", err.message);
//   }
// });

client.initialize().catch((err) => {
  console.error("Failed to start WhatsApp client:", err.message);
});