from __future__ import annotations

from dataclasses import dataclass
import time

from fastapi import APIRouter
from pydantic import BaseModel

from caseclosed.auth import json_error

router = APIRouter(prefix="/api/v1/pomodoro", tags=["pomodoro"])

POMODORO_PHASES = {"work", "break", "done"}


class PomodoroSettings(BaseModel):
    work_minutes: int
    break_minutes: int
    cycle_count: int


@dataclass
class PomodoroState:
    work_minutes: int = 25
    break_minutes: int = 5
    cycle_count: int = 4
    phase: str = "work"
    current_cycle: int = 1
    is_running: bool = False
    remaining_seconds: int = 25 * 60
    phase_ends_at_epoch: float | None = None
    updated_at_epoch: float = time.time()
    version: int = 1


STATE = PomodoroState()


def clamp_settings(settings: PomodoroSettings) -> tuple[int, int, int]:
    return (
        min(180, max(1, round(settings.work_minutes))),
        min(60, max(1, round(settings.break_minutes))),
        min(24, max(1, round(settings.cycle_count))),
    )


def duration_for_phase(state: PomodoroState, phase: str) -> int:
    if phase == "break":
        return state.break_minutes * 60
    if phase == "work":
        return state.work_minutes * 60
    return 0


def advance_state(state: PomodoroState, now: float | None = None) -> None:
    current_time = time.time() if now is None else now
    if not state.is_running or state.phase == "done" or state.phase_ends_at_epoch is None:
        state.updated_at_epoch = current_time
        return

    while state.is_running and state.phase != "done" and state.phase_ends_at_epoch is not None:
        if current_time < state.phase_ends_at_epoch:
            state.remaining_seconds = max(0, int(round(state.phase_ends_at_epoch - current_time)))
            state.updated_at_epoch = current_time
            return
        if state.phase == "work":
            state.phase = "break"
            state.remaining_seconds = state.break_minutes * 60
            state.phase_ends_at_epoch += state.remaining_seconds
            state.version += 1
            continue
        if state.current_cycle >= state.cycle_count:
            state.phase = "done"
            state.is_running = False
            state.remaining_seconds = 0
            state.phase_ends_at_epoch = None
            state.version += 1
            state.updated_at_epoch = current_time
            return
        state.current_cycle += 1
        state.phase = "work"
        state.remaining_seconds = state.work_minutes * 60
        state.phase_ends_at_epoch += state.remaining_seconds
        state.version += 1
    state.updated_at_epoch = current_time


def state_data(state: PomodoroState) -> dict[str, object]:
    advance_state(state)
    total_seconds = duration_for_phase(state, state.phase)
    return {
        "work_minutes": state.work_minutes,
        "break_minutes": state.break_minutes,
        "cycle_count": state.cycle_count,
        "phase": state.phase,
        "current_cycle": state.current_cycle,
        "is_running": state.is_running,
        "remaining_seconds": state.remaining_seconds,
        "total_seconds": total_seconds,
        "phase_ends_at_epoch_ms": (
            int(state.phase_ends_at_epoch * 1000) if state.phase_ends_at_epoch is not None else None
        ),
        "updated_at_epoch_ms": int(state.updated_at_epoch * 1000),
        "version": state.version,
    }


@router.get("")
def get_pomodoro_state() -> dict[str, object]:
    return {"ok": True, "data": {"state": state_data(STATE)}}


@router.post("/settings")
def update_pomodoro_settings(payload: PomodoroSettings) -> dict[str, object]:
    work_minutes, break_minutes, cycle_count = clamp_settings(payload)
    STATE.work_minutes = work_minutes
    STATE.break_minutes = break_minutes
    STATE.cycle_count = cycle_count
    STATE.phase = "work"
    STATE.current_cycle = 1
    STATE.is_running = False
    STATE.remaining_seconds = work_minutes * 60
    STATE.phase_ends_at_epoch = None
    STATE.updated_at_epoch = time.time()
    STATE.version += 1
    return {"ok": True, "data": {"state": state_data(STATE)}}


@router.post("/start")
def start_pomodoro() -> dict[str, object]:
    advance_state(STATE)
    if STATE.phase == "done":
        STATE.phase = "work"
        STATE.current_cycle = 1
        STATE.remaining_seconds = STATE.work_minutes * 60
    if STATE.remaining_seconds <= 0:
        STATE.remaining_seconds = duration_for_phase(STATE, STATE.phase)
    now = time.time()
    STATE.is_running = True
    STATE.phase_ends_at_epoch = now + STATE.remaining_seconds
    STATE.updated_at_epoch = now
    STATE.version += 1
    return {"ok": True, "data": {"state": state_data(STATE)}}


@router.post("/pause")
def pause_pomodoro() -> dict[str, object]:
    advance_state(STATE)
    if STATE.is_running and STATE.phase_ends_at_epoch is not None:
        STATE.remaining_seconds = max(0, int(round(STATE.phase_ends_at_epoch - time.time())))
    STATE.is_running = False
    STATE.phase_ends_at_epoch = None
    STATE.updated_at_epoch = time.time()
    STATE.version += 1
    return {"ok": True, "data": {"state": state_data(STATE)}}


@router.post("/reset")
def reset_pomodoro() -> dict[str, object]:
    STATE.phase = "work"
    STATE.current_cycle = 1
    STATE.is_running = False
    STATE.remaining_seconds = STATE.work_minutes * 60
    STATE.phase_ends_at_epoch = None
    STATE.updated_at_epoch = time.time()
    STATE.version += 1
    return {"ok": True, "data": {"state": state_data(STATE)}}


@router.post("/skip")
def skip_pomodoro() -> dict[str, object]:
    advance_state(STATE)
    if STATE.phase == "done":
        raise json_error(409, "POMODORO_DONE", "Pomodoro is already done.")
    now = time.time()
    STATE.is_running = True
    STATE.phase_ends_at_epoch = now
    advance_state(STATE, now)
    return {"ok": True, "data": {"state": state_data(STATE)}}
