from __future__ import annotations

from types import SimpleNamespace

from pollux.extensions.timestamp_linker import link_timestamps


def test_link_timestamps_parses_and_links_youtube():
    env = {
        "status": "ok",
        "answers": [
            "The key point is at 14:23 and also around 1:02:03 in the lecture.",
        ],
    }
    sources = [
        SimpleNamespace(
            identifier="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            mime_type="text/html",
        )
    ]
    out = link_timestamps(env, sources)
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) >= 2
    # Check one timestamp entry shape
    first = ts[0]
    assert (
        "timestamp" in first
        and "seconds" in first
        and "url" in first
        and "display" in first
    )
    assert "?t=" in first["url"] or "&t=" in first["url"]
    # Normalized timestamp must be HH:MM:SS
    assert first["timestamp"].count(":") == 2
    # Display for <1h should be M:SS
    assert ":" in first["display"] and first["display"].count(":") == 1
    # Ensure the 1:02:03 entry has display H:MM:SS
    entry_1h = next(e for e in ts if e["seconds"] == 1 * 3600 + 2 * 60 + 3)
    assert entry_1h["display"] == "1:02:03"


def test_link_timestamps_idempotent_merge():
    env = {
        "status": "ok",
        "answers": ["Check 00:30"],
        # Existing entry should be kept and not duplicated. It will be enriched later tests.
        "structured_data": {"timestamps": [{"timestamp": "00:30", "seconds": 30}]},
    }
    out = link_timestamps(env, [])
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) == 1
    assert ts[0]["timestamp"] == "00:30"
    assert ts[0]["seconds"] == 30


def test_existing_t_param_is_replaced_per_timestamp():
    env = {
        "status": "ok",
        "answers": ["See 00:05 and 00:10"],
    }
    sources = [
        SimpleNamespace(
            identifier="https://youtu.be/abc123?t=99&foo=bar",
            mime_type="text/html",
        )
    ]
    out = link_timestamps(env, sources)
    ts = sorted(
        out.get("structured_data", {}).get("timestamps"), key=lambda x: x["seconds"]
    )
    assert ts[0]["url"].endswith("t=5")
    assert ts[1]["url"].endswith("t=10")
    assert "foo=bar" in ts[0]["url"] and "foo=bar" in ts[1]["url"]


def test_invalid_time_ranges_are_ignored():
    env = {
        "status": "ok",
        "answers": ["We saw at 99:99 and then 12:60 and 60:00, but 09:59 is valid."],
    }
    out = link_timestamps(env, [])
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) == 1
    assert ts[0]["timestamp"] == "00:09:59" and ts[0]["seconds"] == 9 * 60 + 59


def test_existing_entries_are_enriched_with_url_when_available():
    env = {
        "status": "ok",
        "answers": ["Check 00:30"],
        "structured_data": {"timestamps": [{"timestamp": "00:00:30", "seconds": 30}]},
    }
    sources = [
        SimpleNamespace(
            identifier="https://www.youtube.com/watch?v=xyz", mime_type="text/html"
        )
    ]
    out = link_timestamps(env, sources)
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) == 1
    assert ts[0]["url"].endswith("t=30")
    assert ts[0]["display"] == "0:30"


def test_deterministic_youtube_selection_among_multiple():
    env = {"status": "ok", "answers": ["See 00:02"]}
    sources = [
        SimpleNamespace(identifier="https://youtu.be/zZZ", mime_type="text/html"),
        SimpleNamespace(identifier="https://youtu.be/aAA?x=1", mime_type="text/html"),
    ]
    out = link_timestamps(env, sources)
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) == 1
    # Sorted lexicographically -> aAA comes before zZZ
    assert ts[0]["url"].startswith("https://youtu.be/aAA?x=1")


def test_non_string_answers_are_ignored():
    env = {"status": "ok", "answers": [None, 123, {"k": "v"}, "00:03"]}
    out = link_timestamps(env, [])
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) == 1
    assert ts[0]["timestamp"] == "00:00:03"


def test_idempotent_across_multiple_runs():
    env = {"status": "ok", "answers": ["00:01", "00:01"]}
    sources = [
        SimpleNamespace(identifier="https://youtu.be/xyz", mime_type="text/html")
    ]
    out1 = link_timestamps(env, sources)
    out2 = link_timestamps(out1, sources)
    ts1 = out1.get("structured_data", {}).get("timestamps")
    ts2 = out2.get("structured_data", {}).get("timestamps")
    assert ts1 == ts2 and len(ts2) == 1


def test_component_style_parsing_variants():
    env = {
        "status": "ok",
        "answers": [
            "Starts around 1m02s, then jumps to 1h2m3s; also a quick 90s highlight.",
        ],
    }
    out = link_timestamps(env, [])
    ts = sorted(
        out.get("structured_data", {}).get("timestamps"), key=lambda e: e["seconds"]
    )
    seconds_list = [e["seconds"] for e in ts]
    assert 62 in seconds_list  # 1m02s
    assert 3723 in seconds_list  # 1h2m3s
    assert 90 in seconds_list  # 90s
    # Check displays
    m02s = next(e for e in ts if e["seconds"] == 62)
    assert m02s["display"] == "1:02"
    hms = next(e for e in ts if e["seconds"] == 3723)
    assert hms["display"] == "1:02:03"


def test_multi_url_emits_urls_list_and_preserves_url():
    env = {"status": "ok", "answers": ["See 00:02"]}
    sources = [
        SimpleNamespace(identifier="https://youtu.be/zZZ", mime_type="text/html"),
        SimpleNamespace(identifier="https://youtu.be/aAA?x=1", mime_type="text/html"),
    ]
    out = link_timestamps(env, sources, multi_url=True)
    ts = out.get("structured_data", {}).get("timestamps")
    assert isinstance(ts, list) and len(ts) == 1
    entry = ts[0]
    # url should be the primary (first sorted)
    assert entry["url"].startswith("https://youtu.be/aAA?x=1")
    # urls should include both, sorted
    urls = entry.get("urls")
    assert isinstance(urls, list) and len(urls) == 2
    assert urls[0].startswith("https://youtu.be/aAA?x=1") and urls[1].startswith(
        "https://youtu.be/zZZ"
    )
