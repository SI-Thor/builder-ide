"""The stream (§4.3).

The night feed is the log, not a stream: peeking is reading and rewind is
free. So the SSE endpoint reads the ledger, and ``since_seq`` makes a
reconnect and a rewind the same operation. The event bus is only a wake-up
hint — if it were the source of truth, a reconnect after a restart would
lose everything that happened while the process was down.
"""
from __future__ import annotations

import json

import pytest

from core.events import core_actor

from tests.conftest import OWNER, PANEL


@pytest.fixture
def fast_stream(settings):
    """A heartbeat short enough to keep the tests quick."""
    settings.sse_heartbeat_seconds = 0.05
    settings.sse_poll_seconds = 0.01
    return settings


def frames(lines, want_data: int = 1, stop_on_beat: bool = False):
    """Pull SSE frames off one iterator.

    Returns (data_frames, saw_heartbeat). A heartbeat comment proves the
    stream is alive but idle, which is how "nothing arrived" is asserted
    without waiting for the socket to close.
    """
    data: list[dict] = []
    saw_beat = False
    for line in lines:
        if line.startswith("data: "):
            data.append(json.loads(line[6:]))
            if len(data) >= want_data:
                break
        elif line.startswith(": heartbeat"):
            saw_beat = True
            if stop_on_beat:
                break
    return data, saw_beat


def test_the_stream_is_an_event_stream(client):
    with client.stream("GET", "/v1/events", headers=OWNER) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")


def test_the_stream_needs_a_token(client):
    with client.stream("GET", "/v1/events") as r:
        assert r.status_code == 401


def test_the_stream_carries_the_ledger(client, core):
    """The boot events are already there — the feed is the log."""
    with client.stream("GET", "/v1/events?since_seq=0", headers=OWNER) as r:
        data, _ = frames(r.iter_lines(), want_data=2)
    assert [e["type"] for e in data[:2]] == ["core.boot", "core.recovered"]
    assert all("seq" in e and "actor" in e and "subject" in e for e in data)


def test_each_frame_carries_its_seq_as_the_id(client, core):
    """The SSE id is the ledger seq, so a reconnect can rewind exactly."""
    with client.stream("GET", "/v1/events?since_seq=0", headers=OWNER) as r:
        data, _ = frames(r.iter_lines(), want_data=2)
    seqs = [e["seq"] for e in data]
    assert seqs == sorted(seqs)
    assert seqs[0] >= 1
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


def test_since_seq_rewinds_the_stream(client, core, fast_stream):
    """§4.3: since_seq makes reconnects and rewinds the same operation."""
    core.store.append(core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, {"at": "x"}))
    last = core.store.max_seq()
    with client.stream("GET", f"/v1/events?since_seq={last}", headers=OWNER) as r:
        data, saw_beat = frames(r.iter_lines(), want_data=1, stop_on_beat=True)
    assert data == []
    assert saw_beat, "the stream stayed alive but idle"


def test_the_stream_can_be_filtered_by_type(client, core):
    core.store.append(core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, {"at": "x"}))
    with client.stream("GET", "/v1/events?types=night.tick", headers=OWNER) as r:
        data, _ = frames(r.iter_lines(), want_data=1)
    assert data[0]["type"] == "night.tick"


def test_the_type_filter_excludes_everything_else(client, core):
    core.store.append(core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, {"at": "x"}))
    with client.stream("GET", "/v1/events?types=wo.landed", headers=OWNER) as r:
        data, saw_beat = frames(r.iter_lines(), want_data=1, stop_on_beat=True)
    assert data == []


def test_last_event_id_is_the_same_operation(client, core, fast_stream):
    """The SSE-standard spelling of since_seq."""
    core.store.append(core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, {"at": "x"}))
    last = core.store.max_seq()
    with client.stream("GET", "/v1/events", headers={**OWNER, "Last-Event-ID": str(last)}) as r:
        data, saw_beat = frames(r.iter_lines(), want_data=1, stop_on_beat=True)
    assert data == []
    assert saw_beat


def test_a_new_event_arrives_on_the_open_stream(client, core):
    """The stream is live: an event appended after it opened is delivered."""
    with client.stream("GET", "/v1/events?since_seq=0", headers=OWNER) as r:
        lines = r.iter_lines()
        first, _ = frames(lines, want_data=2)
        assert first
        core.store.append(core.store.new_event(
            "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"},
            {"at": "later"}))
        seen, _ = frames(lines, want_data=1)
    assert seen[0]["type"] == "night.tick"
    assert seen[0]["payload"]["at"] == "later"


def test_the_stream_heartbeats(client, fast_stream):
    """A heartbeat keeps the connection alive through a quiet night."""
    with client.stream("GET", "/v1/events?since_seq=999999", headers=OWNER) as r:
        data, saw_beat = frames(r.iter_lines(), want_data=1, stop_on_beat=True)
    assert saw_beat
    assert data == []


def test_the_stream_is_readable_by_a_panel(client):
    """panel is read + SSE."""
    with client.stream("GET", "/v1/events", headers=PANEL) as r:
        assert r.status_code == 200


def test_a_closed_stream_is_released(live_server, fast_stream):
    """A client that walks away must not leave a stream spinning forever.

    This one runs against a real uvicorn server rather than the test
    transport: "the client went away" is a fact about sockets, and only a
    real server can observe it.
    """
    import time

    import httpx

    url, app = live_server
    with httpx.Client(timeout=10) as c:
        with c.stream("GET", f"{url}/v1/events?since_seq=0", headers=OWNER) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    break
            assert app.state.active_streams >= 1
        # the socket is closed here
    for _ in range(200):
        if app.state.active_streams == 0:
            break
        time.sleep(0.05)
    assert app.state.active_streams == 0


def test_the_stream_works_against_a_real_server(live_server, fast_stream):
    """The endpoint under uvicorn: the headers and the frames are what a
    browser's EventSource will see."""
    import httpx

    url, _app = live_server
    with httpx.Client(timeout=10) as c:
        with c.stream("GET", f"{url}/v1/events?since_seq=0", headers=OWNER) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["cache-control"] == "no-cache"
            data, _ = frames(r.iter_lines(), want_data=2)
    assert [e["type"] for e in data[:2]] == ["core.boot", "core.recovered"]
