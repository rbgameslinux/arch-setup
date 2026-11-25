"""Asynchronous task runner bridging background operations with GTK4."""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from gi.repository import GLib

STEP_MARKER_RE = re.compile(r"^@@STEP\s+(\d+)\s+(\d+)\s+(.+)$")
PRIVILEGED_SCRIPT = Path(__file__).resolve().with_name("privileged.py")


class TaskCancelledError(RuntimeError):
    """Raised when the user cancels a running execution plan."""


class TaskLogger(Protocol):
    """Logging interface passed to user-space task callables."""

    def info(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...
    def raw(self, line: str) -> None: ...
    def set_progress(self, fraction: float, status: str | None = None) -> None: ...
    def run_command(self, cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> int: ...


@dataclass(frozen=True)
class PrivilegedTask:
    """Single action to include in a pkexec batch."""

    action: str
    label: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "label": self.label,
            "params": self.params,
        }


@dataclass(frozen=True)
class PrivilegedBatch:
    """Group of privileged tasks executed under a single pkexec prompt."""

    title: str
    tasks: list[PrivilegedTask]
    dry_run: bool = False


@dataclass(frozen=True)
class UserStep:
    """Single non-root step executed in the user session."""

    title: str
    fn: Callable[[TaskLogger], None]


PlanStage = PrivilegedBatch | UserStep


@dataclass(frozen=True)
class ExecutionPlan:
    """Ordered list of privileged batches and user steps."""

    title: str
    stages: list[PlanStage]


@dataclass
class RunnerCallbacks:
    """Callbacks invoked on the GTK main loop via GLib.idle_add."""

    on_log: Callable[[str, str], None]
    on_progress: Callable[[float, str], None]
    on_error_prompt: Callable[[str, str, Callable[[bool], None]], None]
    on_finished: Callable[[bool, str, Path], None]


class _RunnerContext:
    """Per-run logging, subprocess tracking, and cancellation helper."""

    def __init__(
        self,
        log_path: Path,
        callbacks: RunnerCallbacks,
    ) -> None:
        self.log_path = log_path
        self.callbacks = callbacks
        self.cancel_event = threading.Event()
        self._proc_lock = threading.Lock()
        self._active_proc: subprocess.Popen[str] | None = None
        self._log_lock = threading.Lock()
        self._current_progress = 0.0

    def _write_log_file(self, line: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self._log_lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{timestamp}] {line}\n")

    @staticmethod
    def _detect_level(line: str) -> str:
        if line.startswith("[ERRO]"):
            return "error"
        if line.startswith("[AVISO]"):
            return "warn"
        if line.startswith("[INFO]"):
            return "info"
        return "normal"

    def emit_line(self, line: str, level: str | None = None) -> None:
        resolved_level = level or self._detect_level(line)
        self._write_log_file(line)
        GLib.idle_add(self.callbacks.on_log, line, resolved_level)

    def info(self, msg: str) -> None:
        self.emit_line(f"[INFO] {msg}", "info")

    def warn(self, msg: str) -> None:
        self.emit_line(f"[AVISO] {msg}", "warn")

    def error(self, msg: str) -> None:
        self.emit_line(f"[ERRO] {msg}", "error")

    def raw(self, line: str) -> None:
        self.emit_line(line)

    def set_progress(self, fraction: float, status: str | None = None) -> None:
        clamped = max(0.0, min(1.0, fraction))
        self._current_progress = clamped
        GLib.idle_add(self.callbacks.on_progress, clamped, status or "")

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise TaskCancelledError("Execução cancelada pelo usuário.")

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._proc_lock:
            proc = self._active_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def run_command(
        self,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        on_marker: Callable[[int, int, str], None] | None = None,
    ) -> int:
        self.check_cancelled()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        with self._proc_lock:
            self._active_proc = proc

        try:
            assert proc.stdout is not None
            try:
                for raw_line in proc.stdout:
                    line = raw_line.rstrip("\r\n")
                    if on_marker:
                        match = STEP_MARKER_RE.match(line)
                        if match:
                            on_marker(
                                int(match.group(1)),
                                int(match.group(2)),
                                match.group(3),
                            )
                            continue
                    self.raw(line)
                    if self.cancel_event.is_set() and proc.poll() is None:
                        proc.terminate()
            finally:
                proc.stdout.close()
            rc = proc.wait()
        finally:
            with self._proc_lock:
                self._active_proc = None

        self.check_cancelled()
        return rc

    def ask_continue(self, stage_title: str, error_msg: str) -> bool:
        """Pause worker thread and ask the GUI whether to continue after failure."""
        if self.cancel_event.is_set():
            return False
        event = threading.Event()
        decision = {"continue": False}

        def _respond(should_continue: bool) -> None:
            decision["continue"] = should_continue
            event.set()

        GLib.idle_add(self.callbacks.on_error_prompt, stage_title, error_msg, _respond)
        while not event.is_set():
            if self.cancel_event.wait(timeout=0.1):
                return False
        return decision["continue"]


class CommandRunner:
    """Runs an ExecutionPlan asynchronously and reports updates via GTK idle."""

    def __init__(self) -> None:
        self._ctx: _RunnerContext | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, plan: ExecutionPlan, callbacks: RunnerCallbacks) -> Path:
        if self.is_running:
            raise RuntimeError("Já existe uma execução em andamento.")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = Path(f"/tmp/arch-setup-{timestamp}.log")
        ctx = _RunnerContext(log_path, callbacks)
        self._ctx = ctx

        thread = threading.Thread(
            target=self._execute_plan,
            args=(plan, ctx),
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return log_path

    def cancel(self) -> None:
        if self._ctx is not None:
            self._ctx.cancel()

    def _execute_plan(self, plan: ExecutionPlan, ctx: _RunnerContext) -> None:
        total_stages = max(len(plan.stages), 1)
        had_nonfatal_error = False

        ctx.info(f"Iniciando: {plan.title}")
        ctx.info(f"Log salvo em: {ctx.log_path}")

        try:
            for idx, stage in enumerate(plan.stages):
                ctx.check_cancelled()
                base_fraction = idx / total_stages
                stage_span = 1.0 / total_stages

                if isinstance(stage, PrivilegedBatch):
                    ctx.set_progress(base_fraction, f"Autenticação / {stage.title}...")
                    try:
                        self._run_privileged_batch(
                            stage, ctx, base_fraction, stage_span
                        )
                    except TaskCancelledError:
                        raise
                    except Exception as exc:
                        ctx.error(f"Falha em '{stage.title}': {exc}")
                        if not ctx.ask_continue(stage.title, str(exc)):
                            GLib.idle_add(
                                ctx.callbacks.on_finished,
                                False,
                                f"Abortado após falha em: {stage.title}",
                                ctx.log_path,
                            )
                            return
                        had_nonfatal_error = True
                else:
                    ctx.set_progress(base_fraction, stage.title)
                    ctx.info(f"Etapa: {stage.title}")
                    try:
                        stage.fn(ctx)
                    except TaskCancelledError:
                        raise
                    except Exception as exc:
                        ctx.error(f"Falha em '{stage.title}': {exc}")
                        if not ctx.ask_continue(stage.title, str(exc)):
                            GLib.idle_add(
                                ctx.callbacks.on_finished,
                                False,
                                f"Abortado após falha em: {stage.title}",
                                ctx.log_path,
                            )
                            return
                        had_nonfatal_error = True

                ctx.set_progress((idx + 1) / total_stages, stage.title)

            summary = (
                "Concluído com avisos/falhas ignoradas."
                if had_nonfatal_error
                else "Todas as etapas foram concluídas com sucesso!"
            )
            ctx.info(summary)
            GLib.idle_add(ctx.callbacks.on_finished, True, summary, ctx.log_path)
        except TaskCancelledError as exc:
            ctx.warn(str(exc))
            GLib.idle_add(ctx.callbacks.on_finished, False, str(exc), ctx.log_path)
        except Exception as exc:  # pragma: no cover - defensive fallback
            ctx.error(f"Erro inesperado: {exc}")
            GLib.idle_add(ctx.callbacks.on_finished, False, str(exc), ctx.log_path)

    def _run_privileged_batch(
        self,
        batch: PrivilegedBatch,
        ctx: _RunnerContext,
        base_fraction: float,
        stage_span: float,
    ) -> None:
        if not batch.tasks:
            return

        manifest = {
            "target_user": getpass.getuser(),
            "tasks": [task.to_dict() for task in batch.tasks],
        }

        fd, tmp_name = tempfile.mkstemp(prefix="arch-setup-manifest-", suffix=".json")
        manifest_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
            # pkexec runs as root, and tempfile creates 0600 owned by user (root can read),
            # keeping 0600 prevents unprivileged local tampering.
            os.chmod(manifest_path, 0o600)

            if batch.dry_run:
                cmd = [sys.executable, str(PRIVILEGED_SCRIPT), "--dry-run", str(manifest_path)]
            else:
                cmd = ["pkexec", sys.executable, str(PRIVILEGED_SCRIPT), str(manifest_path)]

            def _on_marker(step_idx: int, step_total: int, label: str) -> None:
                inner = (step_idx - 1) / max(step_total, 1)
                ctx.set_progress(base_fraction + stage_span * inner, label)
                ctx.info(f"[{step_idx}/{step_total}] {label}")

            rc = ctx.run_command(cmd, on_marker=_on_marker)
            if rc != 0:
                if rc in (126, 127):
                    raise RuntimeError(
                        "Autenticação pkexec cancelada ou não autorizada."
                    )
                raise RuntimeError(f"Worker privilegiado retornou código {rc}.")
        finally:
            try:
                manifest_path.unlink(missing_ok=True)
            except OSError:
                pass
