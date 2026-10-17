# -*- coding: utf-8 -*-
"""取消令牌：界面线程取消时，能立刻结束正在跑的转换进程。"""
from __future__ import annotations

import subprocess
import threading


class CancelToken:
    def __init__(self) -> None:
        self.event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ---- 查询 ----
    def cancelled(self) -> bool:
        return self.event.is_set()

    # ---- 取消 ----
    def cancel(self) -> None:
        self.event.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    # ---- 后端把当前子进程挂上来 ----
    def attach(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._proc = proc

    def detach(self, proc: subprocess.Popen | None = None) -> None:
        with self._lock:
            if proc is None or self._proc is proc:
                self._proc = None
