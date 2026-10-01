/** Tests for wa/bot.mjs pure helpers: videoInfo + messageText.
 *
 * Run: node bot.test.mjs  (from wa/, after `npm install`)
 */
import assert from "node:assert/strict";

import { messageText, videoInfo } from "./bot.mjs";

let n = 0;
function t(name, fn) {
	n++;
	fn();
	console.log("ok %d - %s", n, name);
}

// ---------------------------------------------------------------- messageText
t("messageText: plain conversation", () => {
	assert.equal(
		messageText({ message: { conversation: "!board" } }),
		"!board",
	);
});

t("messageText: extended text", () => {
	assert.equal(
		messageText({ message: { extendedTextMessage: { text: "!stats" } } }),
		"!stats",
	);
});

t("messageText: empty message -> empty string", () => {
	assert.equal(messageText({}), "");
	assert.equal(messageText({ message: {} }), "");
});

// ---------------------------------------------------------------- videoInfo
t("videoInfo: plain video message", () => {
	const m = { message: { videoMessage: { caption: "look at me", url: "x" } } };
	assert.deepEqual(videoInfo(m), { caption: "look at me", ext: ".mp4" });
});

t("videoInfo: video without caption -> empty caption", () => {
	const m = { message: { videoMessage: {} } };
	assert.deepEqual(videoInfo(m), { caption: "", ext: ".mp4" });
});

t("videoInfo: video document by mimetype", () => {
	const m = {
		message: {
			documentMessage: {
				mimetype: "video/mp4",
				caption: "my set",
				fileName: "clip.mp4",
			},
		},
	};
	assert.deepEqual(videoInfo(m), { caption: "my set", ext: ".mp4" });
});

t("videoInfo: video document uses file extension", () => {
	const m = {
		message: {
			documentMessage: { mimetype: "video/webm", fileName: "set.webm" },
		},
	};
	assert.deepEqual(videoInfo(m), { caption: "set.webm", ext: ".webm" });
});

t("videoInfo: image document is ignored", () => {
	const m = {
		message: { documentMessage: { mimetype: "image/jpeg", fileName: "a.jpg" } },
	};
	assert.equal(videoInfo(m), null);
});

t("videoInfo: image message is ignored", () => {
	assert.equal(videoInfo({ message: { imageMessage: {} } }), null);
});

t("videoInfo: document with caption wrapper", () => {
	const m = {
		message: {
			documentWithCaptionMessage: {
				message: {
					documentMessage: {
						mimetype: "video/mp4",
						caption: "wrapped",
						fileName: "w.mp4",
					},
				},
			},
		},
	};
	assert.deepEqual(videoInfo(m), { caption: "wrapped", ext: ".mp4" });
});

t("videoInfo: no message content -> null", () => {
	assert.equal(videoInfo({}), null);
});

t("videoInfo: audio message is ignored", () => {
	assert.equal(videoInfo({ message: { audioMessage: {} } }), null);
});

console.log("\n# pass %d", n);
