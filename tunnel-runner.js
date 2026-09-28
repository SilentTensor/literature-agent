/*
 * Literature Survey Agent - public tunnel runner
 *
 * Opens a localtunnel for the local service and keeps it alive, writing the
 * current public URL to public-url.txt every time it changes. Kept in plain
 * JavaScript so the PowerShell launcher does not have to parse any output.
 *
 * Usage:  node tunnel-runner.js <port> <urlFile> <logFile>
 */
const fs = require("fs");
const path = require("path");

const PORT = Number(process.argv[2] || 8765);
const URL_FILE = process.argv[3] || path.join(__dirname, "..", "public-url.txt");
const LOG_FILE = process.argv[4] || path.join(__dirname, "tunnel.log");

function log(msg) {
  const line = new Date().toISOString().replace("T", " ").slice(0, 19) + "  " + msg;
  console.log(line);
  try {
    fs.appendFileSync(LOG_FILE, line + "\n", "utf8");
  } catch (e) {
    /* logging must never crash the tunnel */
  }
}

function publish(url) {
  try {
    fs.writeFileSync(URL_FILE, url + "\n", "utf8");
    log("public url: " + url);
    log("share this address, or open it in a browser");
  } catch (e) {
    log("failed to write url file: " + e.message);
  }
}

let localtunnel;
try {
  localtunnel = require("localtunnel");
} catch (e) {
  log("localtunnel is not installed: " + e.message);
  log("run:  npm install localtunnel   inside the logs folder");
  process.exit(1);
}

log("========== tunnel starting for port " + PORT + " ==========");

function connect(attempt) {
  log("connecting (attempt " + attempt + ") ...");

  localtunnel({ port: PORT })
    .then((tunnel) => {
      publish(tunnel.url);

      tunnel.on("close", () => {
        log("tunnel closed by remote - reconnecting in 5s");
        setTimeout(() => connect(attempt + 1), 5000);
      });

      tunnel.on("error", (err) => {
        log("tunnel error: " + (err && err.message ? err.message : err));
      });
    })
    .catch((err) => {
      log("connect failed: " + (err && err.message ? err.message : err) + " - retry in 10s");
      setTimeout(() => connect(attempt + 1), 10000);
    });
}

connect(1);
