from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import threading
import time

from caseclosed.db import runtime
from caseclosed.services.orchestrator import Orchestrator
from caseclosed.settings import get_background_worker_count
from caseclosed.settings import get_background_worker_idle_sleep_seconds
from caseclosed.settings import get_background_worker_stale_check_seconds
from caseclosed.settings import get_background_worker_stale_timeout_seconds
from caseclosed.settings import is_background_worker_enabled


def kick_job_drain(*, reason: str, max_jobs: int = 50) -> None:
    del reason
    if not is_background_worker_enabled():
        return
    thread = threading.Thread(
        target=_drain_jobs,
        args=(max_jobs,),
        name="caseclosed-worker-drain",
        daemon=True,
    )
    thread.start()


def _drain_jobs(max_jobs: int) -> None:
    orchestrator = Orchestrator(worker_id="worker-background-drain")
    for _ in range(max_jobs):
        try:
            job_id = orchestrator.run_once()
        except Exception:
            return
        if job_id is None:
            return


@dataclass
class BackgroundWorkerSupervisor:
    worker_count: int | None = None
    idle_sleep_seconds: float | None = None
    stale_timeout_seconds: int | None = None
    stale_check_seconds: int | None = None

    def __post_init__(self) -> None:
        self.worker_count = self.worker_count or get_background_worker_count()
        self.idle_sleep_seconds = (
            self.idle_sleep_seconds or get_background_worker_idle_sleep_seconds()
        )
        self.stale_timeout_seconds = (
            self.stale_timeout_seconds or get_background_worker_stale_timeout_seconds()
        )
        self.stale_check_seconds = (
            self.stale_check_seconds or get_background_worker_stale_check_seconds()
        )
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        for index in range(self.worker_count or 1):
            thread = threading.Thread(
                target=self._worker_loop,
                args=(f"worker-background-{index + 1}",),
                name=f"caseclosed-worker-{index + 1}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        stale_thread = threading.Thread(
            target=self._stale_job_loop,
            name="caseclosed-worker-stale-check",
            daemon=True,
        )
        stale_thread.start()
        self._threads.append(stale_thread)

    async def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def _worker_loop(self, worker_id: str) -> None:
        orchestrator = Orchestrator(worker_id=worker_id)
        while not self._stop_event.is_set():
            try:
                job_id = orchestrator.run_once()
            except Exception:
                time.sleep(self.idle_sleep_seconds or 1.0)
                continue
            if job_id is None:
                time.sleep(self.idle_sleep_seconds or 1.0)

    def _stale_job_loop(self) -> None:
        orchestrator = Orchestrator(worker_id="worker-background-stale-check")
        timeout = timedelta(seconds=self.stale_timeout_seconds or 300)
        while not self._stop_event.is_set():
            try:
                orchestrator.mark_stale_jobs(
                    now=runtime.jst_now(),
                    heartbeat_timeout=timeout,
                )
            except Exception:
                pass
            time.sleep(self.stale_check_seconds or 60)
