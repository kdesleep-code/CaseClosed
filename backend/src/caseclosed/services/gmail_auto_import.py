from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from caseclosed.db import runtime
from caseclosed.google_integration import google_gmail_auto_import_settings_data
from caseclosed.google_integration import run_google_gmail_auto_import_once


@dataclass
class GmailAutoImportSupervisor:
    initial_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="caseclosed-gmail-auto-import",
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
            interval_seconds = 10 * 60
            try:
                with runtime.SessionLocal() as session:
                    settings = google_gmail_auto_import_settings_data(session)
                    interval_seconds = int(settings["interval_minutes"]) * 60
                    run_google_gmail_auto_import_once(session)
            except Exception:
                pass
            self._stop_event.wait(max(60, interval_seconds))
