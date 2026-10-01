/**
 * mic - dictate a prompt with the phone's microphone.
 *
 *   /mic [seconds]        record (or use the Android recognizer) and drop the
 *                         transcript into the editor so you can tweak + send
 *   Ctrl+Alt+V            same, with the default duration
 *
 * Environment:
 *   MIC_BACKEND     "android" (default, instant) or "whisper" (more accurate)
 *   MIC_SECONDS     duration used by the whisper backend (default 8)
 *   MIC_LANGUAGE    language hint, e.g. "es", "en-US"
 *   MIC_AUTO_SUBMIT "1" to send the transcript immediately instead of editing
 *   MIC_SHORTCUT    override the shortcut (default ctrl+alt+v)
 *
 * The heavy lifting lives in `listen` (~/phone/bin/listen) so the same
 * recording/transcription path is usable straight from the shell.
 */
import { spawn } from "node:child_process";
import { accessSync } from "node:fs";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const BACKEND = process.env.MIC_BACKEND || "android";
const DEFAULT_SECONDS = (process.env.MIC_SECONDS || "8").replace(/[^0-9]/g, "") || "8";
const LANGUAGE = process.env.MIC_LANGUAGE || "";
const AUTO_SUBMIT = /^(1|true|yes|on)$/i.test(process.env.MIC_AUTO_SUBMIT || "");
const SHORTCUT = process.env.MIC_SHORTCUT || "ctrl+alt+v";
const LABEL = BACKEND === "android" ? "🎙 listening (speak now)…" : "🎙 recording…";

function findListen(): string {
	const candidates = [
		`${process.env.HOME}/phone/bin/listen`,
		`${process.env.HOME}/bin/listen`,
		`${process.env.PREFIX}/bin/listen`,
	];
	return candidates.find((p) => {
		try {
			accessSync(p);
			return true;
		} catch {
			return false;
		}
	}) ?? "listen";
}

async function runListen(args: string[], timeoutMs: number): Promise<{ text: string; code: number; stderr: string }> {
	const bin = findListen();
	return await new Promise((resolve) => {
		const child = spawn(bin, args, { stdio: ["ignore", "pipe", "pipe"] });
		let out = "";
		let err = "";
		const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);
		child.stdout.on("data", (d) => (out += d.toString()));
		child.stderr.on("data", (d) => (err += d.toString()));
		child.on("error", (e) => {
			clearTimeout(timer);
			resolve({ text: "", code: 127, stderr: String(e) });
		});
		child.on("close", (code) => {
			clearTimeout(timer);
			resolve({ text: out, code: code ?? 1, stderr: err });
		});
	});
}

export default function (pi: ExtensionAPI) {
	const dictate = async (ctx: ExtensionContext, secondsArg?: string) => {
		if (!ctx.hasUI) {
			ctx.ui.notify("mic needs an interactive session", "error");
			return;
		}
		const secs = (secondsArg || "").replace(/[^0-9]/g, "") || DEFAULT_SECONDS;
		const args = [`--${BACKEND}`, secs];
		if (LANGUAGE) args.push("-l", LANGUAGE);

		ctx.ui.setStatus("mic", LABEL);
		try {
			const { text, code, stderr } = await runListen(args, (Number(secs) + 30) * 1000);
			const transcript = text.trim();
			if (!transcript) {
				ctx.ui.notify(
					code === 0 ? "Heard nothing." : `Mic failed: ${stderr.trim().split("\n").pop() || code}`,
					"warning",
				);
				return;
			}
			if (AUTO_SUBMIT) {
				pi.sendUserMessage(transcript, { expandPromptTemplates: true });
				return;
			}
			const existing = ctx.ui.getEditorText();
			ctx.ui.setEditorText(existing.trim() ? `${existing.trimEnd()} ${transcript}` : transcript);
			ctx.ui.notify("Transcript ready - edit, then Enter to send.", "info");
		} finally {
			ctx.ui.setStatus("mic", undefined);
		}
	};

	pi.registerCommand("mic", {
		description: "Dictate a prompt with the microphone (mic → editor)",
		handler: async (args, ctx) => {
			await dictate(ctx, args?.trim());
		},
	});

	pi.registerShortcut(SHORTCUT as never, {
		description: "Dictate a prompt with the microphone",
		handler: async (ctx) => {
			await dictate(ctx);
		},
	});
}
