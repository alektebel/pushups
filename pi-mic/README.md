# pi-mic — dictate prompts on Android

Use the phone's microphone to write prompts for
[pi](https://github.com/earendil-works/pi) (or any shell) on Termux.

- `listen` — record speech and print a transcript. Shell-friendly, reusable.
- `mic.ts` — a pi extension: `/mic` command and `Ctrl+Alt+V` shortcut that drop
  the transcript straight into pi's editor.

## Install

```bash
cp listen ~/phone/bin/listen && chmod +x ~/phone/bin/listen
mkdir -p ~/.pi/agent/extensions
cp mic.ts ~/.pi/agent/extensions/mic.ts
```

Then restart pi (or `/reload`). Run `/mic`, speak, edit, Enter.

## Backends

| Backend | How | Notes |
|---|---|---|
| `android` (default) | `termux-speech-to-text` | instant, on-device/Google recognizer |
| `whisper` | `termux-microphone-record` → `nan stt` | more accurate, fixed duration |

```bash
listen                      # android recognizer, unlimited until you stop
listen --whisper 12         # record 12s, transcribe with whisper
listen -l es 10             # Spanish hint
```

Env for the extension: `MIC_BACKEND`, `MIC_SECONDS`, `MIC_LANGUAGE`,
`MIC_AUTO_SUBMIT=1` (send immediately instead of editing), `MIC_SHORTCUT`.

## One-time permission

The mic needs **Termux:API → Microphone**. Without it:

```
listen: Termux:API does not have microphone permission.
```

Grant it in Android Settings → Apps → Termux:API → Permissions.

## Requirements

`pkg install termux-api` plus the **Termux:API** Android app. The whisper backend
also needs `nan` (NaN API client) with `NAN_API_KEY` set.
