/**
 * pushups WhatsApp adapter
 *
 * Links to a WhatsApp account as a companion device (pairing code or QR),
 * watches group chats for videos, counts the push-ups with the local
 * `pushups.py` core, and replies with the count / leaderboard.
 *
 *   WA_PHONE=40712345678 node bot.mjs        # first run: prints a pairing code
 *   node bot.mjs --test-video clip.mp4       # dry-run the counting path
 *
 * Env:
 *   WA_PHONE       phone number for pairing (country code + number, digits only)
 *   WA_AUTH_DIR    where the session lives (default ~/pushups/wa/auth)
 *   WA_ALLOW       comma-separated group JIDs to watch (default: all groups)
 *   WA_PREFIX      command prefix (default "!")
 *   WA_BOARD_PERIOD all|today|week|month (default today)
 *   LOG_LEVEL      pino level (default warn)
 *
 * Honest warning: this is an UNOFFICIAL client. Meta bans accounts that use
 * them. Use a spare number, not your main one.
 */
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
	Browsers,
	DisconnectReason,
	downloadMediaMessage,
	fetchLatestBaileysVersion,
	getContentType,
	jidNormalizedUser,
	makeWASocket,
	useMultiFileAuthState,
} from "baileys";
import pino from "pino";

const HOME = process.env.PUSHUP_HOME || path.join(os.homedir(), "pushups");
const CLI = path.join(HOME, "pushups.py");
const AUTH_DIR = process.env.WA_AUTH_DIR || path.join(HOME, "wa", "auth");
const PHONE = (process.env.WA_PHONE || "").replace(/[^0-9]/g, "");
const PREFIX = process.env.WA_PREFIX || "!";
const BOARD_PERIOD = process.env.WA_BOARD_PERIOD || "today";
const ALLOW = (process.env.WA_ALLOW || "").split(",").map((s) => s.trim()).filter(Boolean);
const MEDIA_TMP = path.join(HOME, "wa", "media");
const SEEN_FILE = path.join(HOME, "wa", "processed.json");
const logger = pino({ level: process.env.LOG_LEVEL || "warn" });

// ---------------------------------------------------------------- helpers
function runCli(args, timeout = 300_000) {
	return new Promise((resolve) => {
		execFile("python3", [CLI, ...args], { timeout, maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
			resolve({ ok: !err, out: (stdout || "").trim(), err: (stderr || String(err || "")).trim() });
		});
	});
}

let seen = new Set();
async function loadSeen() {
	try {
		seen = new Set(JSON.parse(await fs.readFile(SEEN_FILE, "utf8")));
	} catch {}
}
async function markSeen(id) {
	seen.add(id);
	if (seen.size > 2000) seen = new Set([...seen].slice(-1000));
	await fs.mkdir(path.dirname(SEEN_FILE), { recursive: true });
	await fs.writeFile(SEEN_FILE, JSON.stringify([...seen]));
}

const groups = new Map();
async function groupName(sock, jid) {
	if (groups.has(jid)) return groups.get(jid);
	try {
		const meta = await sock.groupMetadata(jid);
		groups.set(jid, meta.subject);
		return meta.subject;
	} catch {
		return jid;
	}
}

export function messageText(m) {
	return m.message?.conversation || m.message?.extendedTextMessage?.text || "";
}

/** Pull the first video out of a message: a video caption without a body, or a video document. */
export function videoInfo(m) {
	const type = getContentType(m.message);
	if (!type) return null;
	const node = m.message[type];
	if (type === "videoMessage") return { caption: node?.caption || "", ext: ".mp4" };
	if (type === "documentMessage" && String(node?.mimetype || "").startsWith("video/")) {
		return { caption: node?.caption || node?.fileName || "", ext: path.extname(node?.fileName || "") || ".mp4" };
	}
	if (type === "documentWithCaptionMessage") {
		const inner = node?.message?.documentMessage;
		if (String(inner?.mimetype || "").startsWith("video/")) {
			return { caption: inner?.caption || inner?.fileName || "", ext: path.extname(inner?.fileName || "") || ".mp4" };
		}
	}
	return null;
}

async function downloadVideo(sock, m, ext) {
	const buffer = await downloadMediaMessage(
		m,
		"buffer",
		{},
		{ logger, reuploadRequest: sock.updateMediaMessage },
	);
	await fs.mkdir(MEDIA_TMP, { recursive: true });
	const file = path.join(MEDIA_TMP, `${m.key.id}${ext}`);
	await fs.writeFile(file, buffer);
	return file;
}

// ---------------------------------------------------------------- processing
async function handleVideo(sock, m, chatJid) {
	const video = videoInfo(m);
	if (!video) return false;
	if (ALLOW.length && !ALLOW.includes(chatJid)) return false;

	const senderJid = m.key.participant ? jidNormalizedUser(m.key.participant) : chatJid;
	const name = m.pushName || senderJid.split("@")[0];
	const title = await groupName(sock, chatJid);

	await sock.sendMessage(chatJid, { text: "🔎 counting…" }, { quoted: m });
	let file;
	try {
		file = await downloadVideo(sock, m, video.ext);
		const res = await runCli([
			"ingest", file,
			"--chat", chatJid,
			"--user", senderJid,
			"--name", name,
			"--title", title,
		]);
		const reply = res.ok ? res.out : `Could not count that: ${res.err.split("\n").pop()}`;
		await sock.sendMessage(chatJid, { text: reply }, { quoted: m });
	} catch (e) {
		await sock.sendMessage(chatJid, { text: `Could not read that video: ${e.message}` }, { quoted: m });
	} finally {
		if (file) fs.unlink(file).catch(() => {});
	}
	await markSeen(m.key.id);
	return true;
}

async function handleCommand(sock, m, chatJid) {
	const text = messageText(m).trim();
	if (!text.startsWith(PREFIX)) return false;
	const cmd = text.slice(PREFIX.length).split(/\s+/)[0].toLowerCase();
	const senderJid = m.key.participant ? jidNormalizedUser(m.key.participant) : chatJid;

	if (["board", "leaderboard", "top"].includes(cmd)) {
		const res = await runCli(["board", "--chat", chatJid, "--period", BOARD_PERIOD]);
		await sock.sendMessage(chatJid, { text: res.out || "No submissions yet." }, { quoted: m });
		return true;
	}
	if (["stats", "me"].includes(cmd)) {
		const res = await runCli(["stats", "--chat", chatJid, "--user", senderJid]);
		await sock.sendMessage(chatJid, { text: res.out }, { quoted: m });
		return true;
	}
	if (["help", "pushups"].includes(cmd)) {
		await sock.sendMessage(chatJid, {
			text: `💪 Send a video of your push-ups and I'll count it.\n${PREFIX}board — leaderboard\n${PREFIX}stats — your totals`,
		}, { quoted: m });
		return true;
	}
	return false;
}

async function onMessages(sock, upsert) {
	for (const m of upsert.messages || []) {
		if (!m.message || m.key.fromMe) continue;
		if (seen.has(m.key.id)) continue;
		const chatJid = m.key.remoteJid || "";
		if (!chatJid.endsWith("@g.us")) continue; // groups only
		try {
			if (await handleVideo(sock, m, chatJid)) continue;
			await handleCommand(sock, m, chatJid);
		} catch (e) {
			logger.error({ err: e.message }, "message failed");
		}
		await markSeen(m.key.id);
	}
}

// ---------------------------------------------------------------- connection
// Serialize message handling: several videos can arrive at once and the
// Python core writes a single state file, so overlapping runs would race.
let chain = Promise.resolve();
function enqueue(fn) {
	chain = chain.then(fn).catch((e) => logger.error({ err: e.message }, "handler failed"));
	return chain;
}

async function connect() {
	await fs.mkdir(AUTH_DIR, { recursive: true });
	const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
	const { version } = await fetchLatestBaileysVersion();

	const sock = makeWASocket({
		version,
		auth: state,
		logger,
		browser: Browsers.ubuntu("Chrome"),
		markOnlineOnConnect: false,
		syncFullHistory: false,
	});

	sock.ev.on("creds.update", saveCreds);
	sock.ev.on("messages.upsert", (u) => enqueue(() => onMessages(sock, u)));

	if (!state.creds.registered && PHONE) {
		setTimeout(async () => {
			try {
				const code = await sock.requestPairingCode(PHONE);
				console.log(`\n>>> PAIRING CODE: ${code}\n>>> WhatsApp → Linked devices → Link with phone number → enter it.\n`);
			} catch (e) {
				console.error("pairing code failed:", e.message);
			}
		}, 3000);
	}

	sock.ev.on("connection.update", (u) => {
		const { connection, lastDisconnect, qr } = u;
		if (qr && !PHONE) {
			console.log("Scan this QR in WhatsApp → Linked devices:");
			console.log(qr);
		}
		if (connection === "open") console.log("✅ WhatsApp connected");
		if (connection === "close") {
			const code = lastDisconnect?.error?.output?.statusCode;
			if (code === DisconnectReason.loggedOut) {
				console.error("❌ Logged out. Delete", AUTH_DIR, "and re-pair.");
				process.exit(1);
			}
			console.log(`reconnecting (code ${code ?? "?"})…`);
			setTimeout(connect, 3000);
		}
	});
}

// ---------------------------------------------------------------- entry
async function main() {
	await loadSeen();
	await fs.mkdir(MEDIA_TMP, { recursive: true });

	if (process.argv.includes("--test-video")) {
		const file = process.argv[process.argv.indexOf("--test-video") + 1];
		const res = await runCli(["ingest", file, "--chat", "test@g.us", "--user", "test@test", "--name", "Tester"]);
		console.log(res.out || res.err);
		return;
	}

	if (!PHONE) {
		console.log("No WA_PHONE set — will print a QR code instead of a pairing code.");
	}
	await connect();
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
	main().catch((e) => {
		console.error(e);
		process.exit(1);
	});
}
