"""PipelineManager — bridges the synchronous orchestrator thread to async SSE subscribers."""

import asyncio
import threading
from typing import Any

from verbatim.db.manager import StateManager
from verbatim.pipeline.orchestrator import OrchestratorConfig, PipelineOrchestrator


class PipelineManager:
    """Manages a single running orchestrator in a background thread.

    Subscribers receive progress events via asyncio.Queue so the SSE endpoint
    can stream them without blocking the event loop.
    """

    def __init__(self) -> None:
        self.orchestrator: PipelineOrchestrator | None = None
        self.thread: threading.Thread | None = None
        self.status: str = "idle"  # idle | running | paused | complete | stopped | error
        self.project_id: int | None = None
        self.last_results: dict[str, Any] | None = None
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # -- SSE subscriber management ----------------------------------------

    def subscribe(self) -> "asyncio.Queue[dict[str, Any]]":
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[dict[str, Any]]") -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _on_progress(self, event: dict[str, Any]) -> None:
        """Called from the orchestrator's background thread — must be thread-safe."""
        if self._loop:
            for q in list(self._subscribers):
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    # -- Lifecycle --------------------------------------------------------

    def start(
        self,
        project_id: int,
        sm: StateManager,
        cfg: OrchestratorConfig,
        # Injectable for tests
        orchestrator_cls: type = PipelineOrchestrator,
    ) -> None:
        if self.status == "running":
            raise ValueError("Pipeline is already running.")
        if self.thread and self.thread.is_alive():
            raise ValueError(
                "Pipeline is still finishing the current chapter. Try again in a moment."
            )

        self.orchestrator = orchestrator_cls(
            project_id=project_id,
            sm=sm,
            cfg=cfg,
            progress_callback=self._on_progress,
        )
        self.project_id = project_id
        self.status = "running"

        def _run() -> None:
            try:
                self.last_results = self.orchestrator.run()  # type: ignore[union-attr]
                self.status = "stopped" if self.orchestrator.stopped else "complete"  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                self.status = "error"
                self._on_progress({"type": "pipeline_error", "error": str(exc)})

        self.thread = threading.Thread(target=_run, name="pipeline", daemon=True)
        self.thread.start()

    def pause(self) -> None:
        if self.orchestrator and self.status == "running":
            self.orchestrator.pause()
            self.status = "paused"

    def resume(self) -> None:
        if self.orchestrator and self.status == "paused":
            self.orchestrator.resume()
            self.status = "running"

    def stop(self) -> None:
        if self.orchestrator and self.status in ("running", "paused"):
            self.orchestrator.stop()
            self.status = "stopped"

    def get_status(self) -> dict[str, Any]:
        # Map internal status names to the UI's PipelineStatus.state values.
        # complete/stopped/error all mean the pipeline is no longer active → 'idle'
        _state_map = {"idle": "idle", "running": "running", "paused": "paused",
                      "stopping": "stopping", "stopped": "idle", "complete": "idle",
                      "error": "idle"}
        state = _state_map.get(self.status, "idle")
        events = list(self.orchestrator.events) if self.orchestrator else []
        return {
            "state":      state,
            "project_id": self.project_id if state != "idle" else None,
            "last_event": events[-1] if events else None,
        }
