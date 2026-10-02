// Local API so the Python backend can ask the bridge to send things.
// Listens on 127.0.0.1 only, needs a secret header, and can only message
// names listed in contacts.json (never a number taken from the request).

const fs = require("fs");
const http = require("http");
const path = require("path");
const { Location } = require("whatsapp-web.js");

const CONTACTS_FILE = path.resolve(__dirname, "..", "contacts.json"); // project root
const ROUTES = ["/send-text", "/send-location", "/send-reply"];
let started = false; // "ready" can fire again after a reconnect

// Re-read on every request so edits to contacts.json apply without a restart.
function findEntry(name) {
  const raw = JSON.parse(fs.readFileSync(CONTACTS_FILE, "utf-8"));
  const wanted = String(name || "").trim().toLowerCase();
  for (const [key, value] of Object.entries(raw)) {
    if (key.trim().toLowerCase() === wanted) return String(value).trim();
  }
  return null;
}

function startBridgeApi(client) {
  if (started) return;

  const token = process.env.BRIDGE_API_TOKEN;
  const port = Number(process.env.BRIDGE_API_PORT || 3001);
  if (!token) {
    console.error("BRIDGE_API_TOKEN is not set - send API disabled.");
    return;
  }
  started = true;

  const server = http.createServer((req, res) => {
    const reply = (code, obj) => {
      res.writeHead(code, { "Content-Type": "application/json" });
      res.end(JSON.stringify(obj));
    };

    if (req.method !== "POST" || !ROUTES.includes(req.url)) return reply(404, { error: "not found" });
    if (req.headers["x-bridge-token"] !== token) return reply(401, { error: "unauthorized" });

    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 20000) req.destroy();
    });
    req.on("end", async () => {
      try {
        const data = JSON.parse(body);

        if (req.url === "/send-reply") {
          // Reply to someone who messaged us. The backend takes chat_id from its own
          // database, never from the browser, and group chats are refused here.
          const chatId = String(data.chat_id || "");
          const text = String(data.text || "").trim();
          if (!/^\d+@(c\.us|lid)$/.test(chatId)) return reply(400, { error: "bad chat id" });
          if (!text || text.length > 4000) return reply(400, { error: "bad text" });
          await client.sendMessage(chatId, text);
          console.log("[send] /send-reply");
          return reply(200, { status: "sent" });
        }

        const entry = findEntry(data.contact);
        if (!entry) return reply(400, { error: "unknown contact" });

        let chatId = entry; // a full id like 112257593794569@lid is used as-is
        if (!entry.includes("@")) {
          // plain phone number: ask WhatsApp for the matching id
          const wid = await client.getNumberId(entry.replace(/\D/g, ""));
          if (!wid) return reply(404, { error: "number is not on WhatsApp" });
          chatId = wid._serialized || wid.$1; // WhatsApp renamed _serialized to $1 in July 2026
        }

        if (req.url === "/send-text") {
          const text = String(data.text || "").trim();
          if (!text || text.length > 4000) return reply(400, { error: "bad text" });
          await client.sendMessage(chatId, text);
        } else {
          const { latitude, longitude } = data;
          if (
            !Number.isFinite(latitude) || !Number.isFinite(longitude) ||
            Math.abs(latitude) > 90 || Math.abs(longitude) > 180
          ) return reply(400, { error: "bad coordinates" });

          const mapsUrl = `https://maps.google.com/?q=${latitude},${longitude}`;
          try {
            await client.sendMessage(chatId, new Location(latitude, longitude, { name: "My location", url: mapsUrl }));
          } catch (err) {
            console.error("Pin failed, sending a map link instead:", err.stack || err);
            await client.sendMessage(chatId, mapsUrl);
          }
        }
        console.log(`[send] ${req.url} -> "${data.contact}"`); // no message text or coordinates in logs
        reply(200, { status: "sent" });
      } catch (err) {
        console.error("send failed:", err.stack || err);
        reply(500, { error: "send failed" });
      }
    });
  });

  server.listen(port, "127.0.0.1", () => console.log(`Bridge API on 127.0.0.1:${port}`));
}

module.exports = { startBridgeApi };