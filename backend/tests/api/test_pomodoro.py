from __future__ import annotations

import time


def test_pomodoro_time_advances_on_server(client) -> None:
    from caseclosed import pomodoro

    pomodoro.STATE.work_minutes = 1
    pomodoro.STATE.break_minutes = 1
    pomodoro.STATE.cycle_count = 1
    pomodoro.STATE.phase = "work"
    pomodoro.STATE.current_cycle = 1
    pomodoro.STATE.is_running = False
    pomodoro.STATE.remaining_seconds = 1
    pomodoro.STATE.phase_ends_at_epoch = None

    start_response = client.post("/api/v1/pomodoro/start")
    assert start_response.status_code == 200
    assert start_response.json()["data"]["state"]["is_running"] is True

    time.sleep(1.2)
    state_response = client.get("/api/v1/pomodoro")
    assert state_response.status_code == 200
    state = state_response.json()["data"]["state"]
    assert state["phase"] == "break"
    assert state["is_running"] is True

    skip_response = client.post("/api/v1/pomodoro/skip")
    assert skip_response.status_code == 200
    done_state = skip_response.json()["data"]["state"]
    assert done_state["phase"] == "done"
    assert done_state["remaining_seconds"] == 0


def test_pomodoro_settings_reset_state(client) -> None:
    response = client.post(
        "/api/v1/pomodoro/settings",
        json={"work_minutes": 30, "break_minutes": 7, "cycle_count": 3},
    )
    assert response.status_code == 200
    state = response.json()["data"]["state"]
    assert state["work_minutes"] == 30
    assert state["break_minutes"] == 7
    assert state["cycle_count"] == 3
    assert state["phase"] == "work"
    assert state["remaining_seconds"] == 30 * 60
