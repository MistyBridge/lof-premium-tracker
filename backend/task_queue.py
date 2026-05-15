# -*- coding: utf-8 -*-
"""
后台任务队列 — 线程池调度 + 任务状态管理

特性:
  - 每种任务类型最多一个并发实例
  - 任务进度可查询
  - 线程安全
  - 自动清理已完成任务
"""
import logging
import threading
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    def __init__(self, task_type: str, description: str, target: Callable, args=(), kwargs=None):
        self.id = str(uuid.uuid4())[:8]
        self.type = task_type
        self.description = description
        self.status = TaskStatus.PENDING
        self.progress = 0       # 0-100
        self.progress_msg = ""
        self.result = None
        self.error = None
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "status": self.status.value,
            "progress": self.progress,
            "progress_msg": self.progress_msg,
            "error": str(self.error) if self.error else None,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def run(self, progress_callback: Optional[Callable] = None):
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()
        try:
            if progress_callback:
                self._kwargs["_progress_cb"] = progress_callback
            self.result = self._target(*self._args, **self._kwargs)
            self.status = TaskStatus.COMPLETED
        except Exception as e:
            self.status = TaskStatus.FAILED
            self.error = e
            logger.error("Task %s/%s failed: %s", self.type, self.id, e)
        finally:
            self.finished_at = datetime.now()


class TaskQueue:
    """
    后台任务队列 — 每种类型最多一个并发，其余排队。
    使用固定大小线程池 (max_workers=4) 执行任务。
    """

    def __init__(self, max_workers: int = 4):
        self._lock = threading.Lock()
        self._tasks: Dict[str, Task] = {}          # task_id -> Task
        self._running_types: Dict[str, str] = {}    # type -> task_id (running only)
        self._pending: list = []                    # [(task_id, Task)]
        self._sem = threading.Semaphore(max_workers)
        self._max_workers = max_workers
        self._active_workers = 0
        self._workers_lock = threading.Lock()

    def submit(self, task_type: str, description: str, target: Callable,
               progress_callback: Optional[Callable] = None,
               *args, **kwargs) -> Task:
        """提交任务。同类型已有运行中任务则返回已有任务。"""
        with self._lock:
            # 检查同类型是否已在运行
            if task_type in self._running_types:
                existing_id = self._running_types[task_type]
                return self._tasks.get(existing_id)

            task = Task(task_type, description, target, args, kwargs)
            self._tasks[task.id] = task

            # 检查是否有空闲 worker
            with self._workers_lock:
                if self._active_workers < self._max_workers:
                    self._active_workers += 1
                    self._running_types[task_type] = task.id
                    t = threading.Thread(target=self._run_task, args=(task, progress_callback), daemon=True)
                    t.start()
                else:
                    # 排队
                    self._pending.append((task.id, task_type))
                    task.progress_msg = "queued"

            return task

    def _run_task(self, task: Task, progress_callback: Optional[Callable]):
        try:
            task.run(progress_callback)
        finally:
            with self._lock:
                task_type = task.type
                if task_type in self._running_types:
                    del self._running_types[task_type]

            with self._workers_lock:
                self._active_workers -= 1

            # 处理排队任务
            self._process_pending()

    def _process_pending(self):
        with self._lock:
            with self._workers_lock:
                while self._pending and self._active_workers < self._max_workers:
                    task_id, task_type = self._pending.pop(0)
                    task = self._tasks.get(task_id)
                    if task and task_type not in self._running_types:
                        self._active_workers += 1
                        self._running_types[task_type] = task_id
                        t = threading.Thread(target=self._run_task, args=(task, None), daemon=True)
                        t.start()

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_tasks_by_type(self, task_type: str) -> list:
        with self._lock:
            return [t for t in self._tasks.values() if t.type == task_type]

    def get_all_tasks(self) -> list:
        with self._lock:
            return list(self._tasks.values())

    def get_stats(self) -> dict:
        with self._lock:
            running = [t.to_dict() for t in self._tasks.values() if t.status == TaskStatus.RUNNING]
            pending = [t.to_dict() for t in self._tasks.values() if t.status == TaskStatus.PENDING]
            return {
                "running": running,
                "pending": pending,
                "active_workers": self._active_workers,
                "max_workers": self._max_workers,
            }

    def cleanup_old(self, max_age_seconds: int = 3600):
        """清理超过1小时的已完成/失败任务"""
        cutoff = datetime.now().timestamp() - max_age_seconds
        with self._lock:
            stale = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                and t.finished_at and t.finished_at.timestamp() < cutoff
            ]
            for tid in stale:
                del self._tasks[tid]


# ── Singleton ─────────────────────────────────────
_instance: Optional[TaskQueue] = None
_inst_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = TaskQueue(max_workers=4)
    return _instance
