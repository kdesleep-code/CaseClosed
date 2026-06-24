from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time

from caseclosed.db import runtime
from caseclosed.google_integration import google_calendar_auto_sync_settings_data
from caseclosed.google_integration import run_google_calendar_auto_sync_once

logger = logging.getLogger("uvicorn.error")


@dataclass
class CalendarAutoSyncSupervisor:
    initial_delay_seconds: float = 20.0

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="caseclosed-calendar-auto-sync",
            daemon=True,
        )
        self._thread.start()

    async def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self) -> None:
        if self._stop_event.wait(self.initial_delay_seconds):
            return
        while not self._stop_event.is_set():
            interval_seconds = 60 * 60
            started_at = time.perf_counter()
            try:
                with runtime.SessionLocal() as session:
                    settings = google_calendar_auto_sync_settings_data(session)
                    interval_seconds = int(settings["interval_minutes"]) * 60
                    logger.info(
                        "Calendar auto sync starting interval_seconds=%s enabled=%s",
                        interval_seconds,
                        settings.get("enabled"),
                    )
                    result = run_google_calendar_auto_sync_once(session)
                    logger.info(
                        "Calendar auto sync finished duration_seconds=%.3f result=%s",
                        time.perf_counter() - started_at,
                        result,
                    )
            except Exception:
                logger.exception(
                    "Calendar auto sync failed duration_seconds=%.3f",
                    time.perf_counter() - started_at,
                )
            self._stop_event.wait(max(5 * 60, interval_seconds))
