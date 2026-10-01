# pushups — count push-ups friends send into a WhatsApp group

> This repo also ships [`pi-mic/`](pi-mic/README.md): dictate pi prompts by
> voice on Termux (`/mic`, `Ctrl+Alt+V`).

Three pieces, all working:

1. **`reps.py`** — counts reps in one video.
2. **`pushups.py`** — records submissions per chat/member, prints a leaderboard.
3. **`wa/bot.mjs`** — WhatsApp adapter: links as a companion device, watches
   group videos, calls the core, replies with the count.

## Repo layout

```
reps.py            video -> frames -> vision model -> DOWN/UP cycles
pushups.py         submissions, leaderboard, stats (JSON state)
wa/bot.mjs         WhatsApp (Baileys) adapter
wa/start.sh        run it in the background with a wake lock
pi-mic/listen      record speech -> transcript (shell)
pi-mic/mic.ts      pi extension: /mic + Ctrl+Alt+V -> editor
```

## How counting works

Asking a vision model "how many push-ups?" is unreliable. Instead:

```
video --ffmpeg--> N frames --vision model--> UP / DOWN / NONE per frame
                                                   |
                            count DOWN -> UP cycles +---- leaderboard
```

The model is only a per-frame classifier, which it is good at. Frames are
sampled at `--fps` (default 1.5) and capped at `--max-frames` (default 24), so
a clip costs 2–4 cheap API calls. `NONE` frames are gap-filled.

Verified on two stock clips: **5 reps / 13 s** and **6 reps / 12 s**, with a
clean `UP DOWN DOWN UP ...` timeline. Vision model defaults to `qwen3.8-flash`
(`PUSHUP_VLM` to change).

## Use the core

```bash
cd ~/pushups
./reps.py VIDEO --json                 # count only
./pushups.py count VIDEO
./pushups.py ingest VIDEO --chat 123 --user 42 --name Diego
./pushups.py board --chat 123 --period today
./pushups.py stats --chat 123 --user 42
```

State: `~/pushups/data/state.json`. Test the counter without a video:
`./reps.py x --mock down,up,down,up`.

## WhatsApp setup

You need a **phone number that has WhatsApp registered on it** — this is the
"SIM card" part. Use a spare SIM/number, **not your main one** (see the warning
below). The bot then links to that account as a *companion device*, exactly like
WhatsApp Web on a laptop.

1. Put the spare SIM in a phone and register it in the normal WhatsApp app
   (SMS/call verification).
2. On this Termux device:
   ```bash
   cd ~/pushups/wa
   WA_PHONE=40712345678 node bot.mjs     # country code + number, digits only
   ```
   It prints an 8-character pairing code.
3. On the spare phone: **WhatsApp → Settings → Linked devices → Link a device →
   Link with phone number**, and type the code.
4. Add the bot's number to your friends' group.
5. Send a video — the bot replies with the count. `!board` posts the
   leaderboard, `!stats` your totals, `!help` the commands.

Run it in the background:

```bash
~/pushups/wa/start.sh     # wake-lock + logs to wa/bot.log
~/pushups/wa/stop.sh
```

Config (env): `WA_PHONE`, `WA_AUTH_DIR`, `WA_ALLOW` (limit to group JIDs),
`WA_PREFIX`, `WA_BOARD_PERIOD`, `LOG_LEVEL`.

### The honest warning

This uses **Baileys**, an unofficial client. Meta bans accounts it thinks are
automated; reply-ratio, contact-graph distance and robotic timing are the
signals. A lone bot in a small friends' group replying to every video is
low-volume but still unofficial. **Use a spare number** so a ban costs you a
throwaway account, not your life. Keep the primary phone sending a real message
now and then: WhatsApp logs out companion devices if the primary has not been
online for ~14 days.

### Can the official API do this?

No. WhatsApp's Cloud API added a Groups API, but groups must be *created
programmatically by a business account*, are capped at **8 participants**, and
require an Official Business Account. There is no way to add a bot to an
existing personal group officially. That is why the unofficial route is the
only one.

## Keeping it alive

The phone must stay online and Termux must not be frozen. `start.sh` takes a
wake lock; for scheduled revival reuse the `termux-job-scheduler` trick from
`phone focus` (`~/phone/lib/focus.py`, `apps/focus-revive.sh`).

## Privacy

Every sampled frame is uploaded to the vision API at `api.nan.builders`. Tell
your friends.
