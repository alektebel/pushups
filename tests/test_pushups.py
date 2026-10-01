"""Tests for pushups.py: state, periods, ranking, and the CLI commands.

Every test runs with PUSHUP_HOME pointed at a tmp dir, so the real
~/pushups/data/state.json is never touched. reps.analyze is stubbed so no
frames are extracted and no API is called.
"""

import json
import sys
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO

import pytest

import pushups
import reps


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point the module at a tmp PUSHUP_HOME (constants are bound at import)."""
    monkeypatch.setenv("PUSHUP_HOME", str(tmp_path))
    monkeypatch.setattr(pushups, "HOME", str(tmp_path))
    monkeypatch.setattr(pushups, "STATE", str(tmp_path / "data" / "state.json"))
    yield tmp_path


@pytest.fixture()
def fake_count(monkeypatch):
    """Replace reps.analyze: mock string 'N' -> N reps, no video/API work."""
    def analyze(video, fps, max_frames, mock):
        n = int(mock) if mock else 0
        return {"reps": n, "confidence": 0.9, "frames": 10,
                "timeline": (["DOWN", "UP"] * n)[:max(0, 2 * n)]}

    monkeypatch.setattr(pushups.reps, "analyze", analyze)


def run(*argv):
    """Invoke the CLI in-process, capturing stdout."""
    sys.argv = ["pushups"] + [str(a) for a in argv]
    buf = StringIO()
    with redirect_stdout(buf):
        pushups.main()
    return buf.getvalue()


def state():
    return pushups.load()


def member(chat="g1", user="u1"):
    return state()["chats"][chat]["members"][user]


# ----------------------------------------------------------------- state
def test_state_roundtrip(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "Diego", "--mock", "5")
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "Diego", "--mock", "3")
    m = member()
    assert m["total"] == 8
    assert m["sets"] == 2
    assert m["best_set"] == 5
    assert sum(m["days"].values()) == 8
    assert len(m["log"]) == 2
    assert m["log"][0]["n"] == 5


def test_corrupt_state_starts_fresh(home, fake_count):
    (home / "data").mkdir()
    (home / "data" / "state.json").write_text("{not json")
    out = run("ingest", "v.mp4", "--chat", "g", "--user", "u", "--mock", "2")
    assert "2 push-ups" in out


def test_chat_title_recorded(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--title", "Gym Rats", "--mock", "1")
    assert state()["chats"]["g1"]["title"] == "Gym Rats"


def test_new_member_defaults(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--mock", "1")
    m = member()
    assert m["name"] == "u1"
    assert m["last_ts"] is not None


def test_ingest_rename_keeps_history(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "old", "--mock", "5")
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "new", "--mock", "5")
    m = member()
    assert m["name"] == "new"
    assert m["total"] == 10
    assert m["sets"] == 2


# ----------------------------------------------------------------- periods
def test_period_sums(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--mock", "4")
    m = member()
    assert pushups.period_sum(m, "all") == 4
    assert pushups.period_sum(m, "today") == 4
    assert pushups.period_sum(m, "week") == 4
    assert pushups.period_sum(m, "month") == 4

    # a day 40 days back: counts for all-time only
    m["days"] = {(date.today() - timedelta(days=40)).isoformat(): 9}
    m["total"] = 13
    assert pushups.period_sum(m, "all") == 13
    assert pushups.period_sum(m, "today") == 0
    assert pushups.period_sum(m, "week") == 0
    assert pushups.period_sum(m, "month") == 0


# ----------------------------------------------------------------- ranking
def test_ranked_orders_by_score_then_name(home, fake_count):
    for user, name, n in [("u2", "ana", 10), ("u1", "beto", 10), ("u3", "caro", 20)]:
        run("ingest", "v.mp4", "--chat", "g1", "--user", user, "--name", name, "--mock", str(n))
    rows = pushups.ranked(state()["chats"]["g1"], "all")
    assert [(m["name"], v) for m, v in rows] == [("caro", 20), ("ana", 10), ("beto", 10)]


def test_ranked_period_filters(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "a", "--mock", "30")
    st = state()
    st["chats"]["g1"]["members"]["u1"]["days"] = {
        (date.today() - timedelta(days=40)).isoformat(): 30}
    pushups.save(st)
    chat = st["chats"]["g1"]
    assert pushups.ranked(chat, "today")[0][1] == 0
    assert pushups.ranked(chat, "all")[0][1] == 30


# ----------------------------------------------------------------- ingest output
def test_ingest_zero_reps_no_points(home, fake_count):
    out = run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--mock", "0")
    assert "couldn't see any push-ups" in out
    assert member()["total"] == 0


def test_ingest_reply_mentions_rank(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "a", "--mock", "7")
    out = run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "a", "--mock", "3")
    assert "3 push-ups" in out
    assert "#1" in out
    assert member()["best_set"] == 7


# ----------------------------------------------------------------- board/stats
def test_board_empty_chat(home):
    assert "No submissions yet." in run("board", "--chat", "missing")


def test_board_shows_totals(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "a", "--mock", "12")
    out = run("board", "--chat", "g1", "--period", "today")
    assert "a" in out and "12" in out


def test_board_top_limits_rows(home, fake_count):
    for u in ["u1", "u2", "u3", "u4"]:
        run("ingest", "v.mp4", "--chat", "g1", "--user", u, "--mock", "1")
    out = run("board", "--chat", "g1", "--top", "2")
    rows = [ln for ln in out.splitlines() if ln.strip() and ln.split()[-1].isdigit()]
    assert len(rows) == 2


def test_stats(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--name", "a", "--mock", "6")
    out = run("stats", "--chat", "g1", "--user", "u1")
    assert "total:    6" in out
    assert "sets:     1" in out
    assert "best set: 6" in out


def test_stats_unknown_user(home):
    assert "No record" in run("stats", "--chat", "g1", "--user", "nobody")


def test_export(home, fake_count):
    run("ingest", "v.mp4", "--chat", "g1", "--user", "u1", "--mock", "2")
    assert json.loads(run("export", "--chat", "g1"))["members"]["u1"]["total"] == 2
    assert json.loads(run("export", "--chat", "nope")) == {}


# ----------------------------------------------------------------- count cmd
def test_count_json(fake_count):
    assert json.loads(run("count", "v.mp4", "--mock", "3", "--json"))["reps"] == 3


def test_count_plain(fake_count):
    assert run("count", "v.mp4", "--mock", "3").strip() == "3"


def test_reps_mock_cli():
    import subprocess

    r = subprocess.run(
        [sys.executable, "reps.py", "x", "--mock", "down,up,down,up"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "push-ups: 2" in r.stdout
    assert "timeline: DOWN UP DOWN UP" in r.stdout
