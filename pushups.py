#!/data/data/com.termux/files/usr/bin/python3
"""pushups - track push-ups submitted as videos in a group chat.

This is the platform-agnostic core: give it a video plus who sent it, and it
counts the reps and updates a leaderboard. A chat adapter (Telegram, Discord,
...) only has to download the video and call `ingest`.

  pushups count VIDEO
  pushups ingest VIDEO --chat 123 --user 42 --name Diego
  pushups board --chat 123
  pushups stats --chat 123 --user 42
  pushups export --chat 123

State lives in $PUSHUP_HOME/data/state.json (default ~/pushups).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reps  # noqa: E402

HOME = os.path.expanduser(os.environ.get("PUSHUP_HOME", "~/pushups"))
STATE = os.path.join(HOME, "data", "state.json")


def load() -> dict:
    if os.path.exists(STATE):
        try:
            with open(STATE) as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            pass
    return {"chats": {}}


def save(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, STATE)


def today() -> str:
    return dt.date.today().isoformat()


def chat_of(state: dict, chat_id: str, title: str | None = None) -> dict:
    chat = state["chats"].setdefault(str(chat_id), {"title": title or str(chat_id), "members": {}})
    if title:
        chat["title"] = title
    return chat


def member_of(chat: dict, user_id: str, name: str | None = None) -> dict:
    m = chat["members"].setdefault(str(user_id), {
        "name": name or str(user_id),
        "total": 0,
        "sets": 0,
        "best_set": 0,
        "last_ts": None,
        "days": {},
        "log": [],
    })
    if name:
        m["name"] = name
    return m


def period_sum(member: dict, period: str) -> int:
    if period == "all":
        return member["total"]
    d = dt.date.today()
    if period == "today":
        return member["days"].get(d.isoformat(), 0)
    if period == "week":
        start = d - dt.timedelta(days=d.weekday())
        return sum(v for k, v in member["days"].items() if k >= start.isoformat())
    if period == "month":
        return sum(v for k, v in member["days"].items() if k[:7] == d.isoformat()[:7])
    return member["total"]


def ranked(chat: dict, period: str = "all") -> list[tuple[dict, int]]:
    rows = [(m, period_sum(m, period)) for m in chat["members"].values()]
    rows.sort(key=lambda r: (-r[1], r[0]["name"].lower()))
    return rows


# ----------------------------------------------------------------- commands
def cmd_count(a) -> None:
    result = reps.analyze(a.video, a.fps, a.max_frames, a.mock)
    if a.json:
        print(json.dumps(result))
    else:
        print(result["reps"])


def cmd_ingest(a) -> None:
    state = load()
    chat = chat_of(state, a.chat, a.title)
    member = member_of(chat, a.user, a.name)

    result = reps.analyze(a.video, a.fps, a.max_frames, a.mock)
    n = result["reps"]

    ts = dt.datetime.now().isoformat(timespec="seconds")
    d = today()
    member["total"] += n
    member["sets"] += 1
    member["best_set"] = max(member["best_set"], n)
    member["last_ts"] = ts
    member["days"][d] = member["days"].get(d, 0) + n
    member["log"].append({"ts": ts, "n": n, "video": os.path.basename(a.video),
                          "confidence": result["confidence"]})
    save(state)

    rows = ranked(chat)
    pos = next((i + 1 for i, (m, _) in enumerate(rows) if m is member), len(rows))
    day = member["days"].get(d, 0)

    if n == 0:
        reply = ("%s: I couldn't see any push-ups in that video (confidence %.2f). "
                 "Side-on angle and good lighting help. Totals unchanged."
                 % (member["name"], result["confidence"]))
    else:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, "")
        reply = ("💪 %s: %d push-up%s! Today: %d · All-time: %d · %s#%d on the board."
                 % (member["name"], n, "" if n == 1 else "s", day, member["total"], medal, pos))
    print(reply)


def cmd_board(a) -> None:
    state = load()
    chat = state["chats"].get(str(a.chat))
    if not chat:
        print("No submissions yet.")
        return
    rows = ranked(chat, a.period)
    label = {"all": "all-time", "today": "today", "week": "this week", "month": "this month"}[a.period]
    print("🏆 Push-up board (%s) — %s" % (label, chat["title"]))
    shown = 0
    for i, (m, v) in enumerate(rows, 1):
        if a.top and i > a.top:
            break
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "  ")
        print("%s %d. %-18s %5d" % (medal, i, m["name"], v))
        shown += 1
    if not shown:
        print("No submissions in this period.")


def cmd_stats(a) -> None:
    state = load()
    chat = state["chats"].get(str(a.chat))
    if not chat or str(a.user) not in chat["members"]:
        print("No record for that user.")
        return
    m = chat["members"][str(a.user)]
    print("%s — %s" % (m["name"], chat["title"]))
    print("  total:    %d" % m["total"])
    print("  sets:     %d" % m["sets"])
    print("  best set: %d" % m["best_set"])
    print("  today:    %d" % period_sum(m, "today"))
    print("  week:     %d" % period_sum(m, "week"))
    if m["last_ts"]:
        print("  last:     %s" % m["last_ts"])


def cmd_export(a) -> None:
    state = load()
    chat = state["chats"].get(str(a.chat))
    print(json.dumps(chat or {}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="pushups", description="group push-up tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    def model_args(sp):
        sp.add_argument("--fps", type=float, default=1.5)
        sp.add_argument("--max-frames", type=int, default=24)
        sp.add_argument("--mock")

    c = sub.add_parser("count", help="count reps in a video")
    c.add_argument("video")
    model_args(c)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_count)

    i = sub.add_parser("ingest", help="count and record a submission")
    i.add_argument("video")
    i.add_argument("--chat", required=True)
    i.add_argument("--user", required=True)
    i.add_argument("--name")
    i.add_argument("--title")
    model_args(i)
    i.set_defaults(func=cmd_ingest)

    b = sub.add_parser("board", help="show the leaderboard")
    b.add_argument("--chat", required=True)
    b.add_argument("--period", choices=["all", "today", "week", "month"], default="all")
    b.add_argument("--top", type=int, default=10)
    b.set_defaults(func=cmd_board)

    s = sub.add_parser("stats", help="show one member's totals")
    s.add_argument("--chat", required=True)
    s.add_argument("--user", required=True)
    s.set_defaults(func=cmd_stats)

    e = sub.add_parser("export", help="dump raw state for a chat")
    e.add_argument("--chat", required=True)
    e.set_defaults(func=cmd_export)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
