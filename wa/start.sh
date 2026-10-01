#!/data/data/com.termux/files/usr/bin/bash
# Start the WhatsApp push-up bot, keeping the device awake and restarting on crash.
set -uo pipefail
cd "$(dirname "$0")"

if pgrep -f 'node bot.mjs' >/dev/null 2>&1; then
  echo "pushups-wa: already running (pid $(pgrep -f 'node bot.mjs' | head -1))"
  exit 0
fi

command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

nohup node bot.mjs >> bot.log 2>&1 &
echo $! > bot.pid
echo "pushups-wa: started (pid $(cat bot.pid)), logs -> $(pwd)/bot.log"
