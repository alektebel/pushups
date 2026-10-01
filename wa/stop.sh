#!/data/data/com.termux/files/usr/bin/bash
# Stop the WhatsApp push-up bot.
set -uo pipefail
cd "$(dirname "$0")"

if [ -f bot.pid ] && kill "$(cat bot.pid)" 2>/dev/null; then
  rm -f bot.pid
  echo "pushups-wa: stopped"
else
  pkill -f 'node bot.mjs' 2>/dev/null && echo "pushups-wa: stopped" || echo "pushups-wa: not running"
fi

command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock
