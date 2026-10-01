"""Tests for the reps.py counter: mock mode, label parsing, smoothing, dwell."""

import reps


# ----------------------------------------------------------------- analyze mock
def test_mock_counts_down_up_cycles():
    r = reps.analyze("no-video.mp4", 1.5, 24, "down,up,down,up")
    assert r["reps"] == 2
    assert r["mock"] is True
    assert r["confidence"] == 1.0
    assert r["timeline"] == ["DOWN", "UP", "DOWN", "UP"]


def test_mock_starting_state_not_counted():
    # starts UP; only DOWN -> UP transitions count
    assert reps.analyze("x", 1.5, 24, "up,down,up")["reps"] == 1
    assert reps.analyze("x", 1.5, 24, "up,down")["reps"] == 0


def test_mock_nonphase_tokens_count_zero():
    # a bare number is not a phase label; nothing counts
    r = reps.analyze("x", 1.5, 24, "5")
    assert r["reps"] == 0
    assert r["timeline"] == ["5"]


# ----------------------------------------------------------------- parse_labels
def test_parse_labels_json_array():
    assert reps.parse_labels('["UP", "DOWN", "UP"]', 3) == ["UP", "DOWN", "UP"]


def test_parse_labels_json_with_noise():
    assert reps.parse_labels('result: ["UP","DOWN"] thanks', 2) == ["UP", "DOWN"]


def test_parse_labels_broken_json_falls_back_to_regex():
    assert reps.parse_labels("[UP DOWN garbage UP]", 3) == ["UP", "DOWN", "UP"]


def test_parse_labels_no_brackets_returns_none():
    assert reps.parse_labels("UP DOWN garbage UP", 2) == ["NONE", "NONE"]
    assert reps.parse_labels("no usable answer", 2) == ["NONE", "NONE"]


def test_parse_labels_unknown_word_becomes_none():
    assert reps.parse_labels('["UP","SIDEWAYS"]', 2) == ["UP", "NONE"]


def test_parse_labels_pads_short_answer():
    assert reps.parse_labels('["UP"]', 3) == ["UP", "NONE", "NONE"]


def test_parse_labels_truncates_long_answer():
    assert reps.parse_labels('["UP","UP","UP","UP"]', 3) == ["UP", "UP", "UP"]


# ----------------------------------------------------------------- smooth
def test_smooth_bridges_none_gaps():
    seq = [0, None, None, 1]  # DOWN, ?, ?, UP
    assert reps.smooth(seq) == [0, 0, 0, 1]


def test_smooth_drops_leading_none():
    assert reps.smooth([None, None, 1, 0]) == [1, 0]


def test_smooth_keeps_only_none():
    assert reps.smooth([None, None]) == []


def test_smooth_median_window_flips_one_frame_spike():
    seq = [0, 0, 1, 0, 0]
    assert reps.smooth(seq, window=3) == [0, 0, 0, 0, 0]


def test_smooth_median_window_keeps_real_transitions():
    seq = [0, 0, 0, 1, 1, 1]
    assert reps.smooth(seq, window=3) == [0, 0, 0, 1, 1, 1]


# ----------------------------------------------------------------- count_reps
def test_count_reps_basic_cycles():
    assert reps.count_reps(["DOWN", "UP", "DOWN", "UP"]) == 2
    assert reps.count_reps(["DOWN", "UP"] * 5) == 5


def test_count_reps_repeated_states_do_not_count():
    assert reps.count_reps(["DOWN"] * 4 + ["UP"]) == 1
    assert reps.count_reps(["DOWN", "UP", "UP", "UP"]) == 1


def test_count_reps_min_dwell():
    # glitch: single-frame DOWN inside UP run
    labels = ["UP", "UP", "DOWN", "UP", "UP"]
    assert reps.count_reps(labels, min_dwell=1) == 1
    assert reps.count_reps(labels, min_dwell=2) == 0
    # two real cycles, each with 2-frame dwell
    labels = ["DOWN", "DOWN", "UP", "UP", "DOWN", "DOWN", "UP", "UP"]
    assert reps.count_reps(labels, min_dwell=2) == 2


def test_count_reps_none_between_states_still_counts():
    # NONE bridges: DOWN _ _ UP -> one rep
    assert reps.count_reps(["DOWN", "NONE", "NONE", "UP"]) == 1


def test_count_reps_empty():
    assert reps.count_reps([]) == 0
    assert reps.count_reps(["NONE"] * 5) == 0


# ----------------------------------------------------------------- confidence
def test_confidence():
    assert reps.confidence([]) == 0.0
    assert reps.confidence(["UP", "DOWN"]) == 1.0
    assert reps.confidence(["UP", "NONE", "DOWN", "NONE"]) == 0.5


# ----------------------------------------------------------------- classify
def test_classify_batches_and_preserves_order(monkeypatch):
    calls = []

    def fake_batch(frames):
        calls.append(list(frames))
        return ["UP"] * len(frames)

    monkeypatch.setattr(reps, "classify_batch", fake_batch)
    labels = reps.classify(["f%d" % i for i in range(7)], batch=6)
    assert labels == ["UP"] * 7
    assert [len(c) for c in calls] == [6, 1]
