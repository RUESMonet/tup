import asyncio

from src.models.task import PipelineResult, TaskRecord, TaskStatus


class InMemoryTaskStorage:
    def __init__(self):
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, owner_id: str) -> TaskRecord:
        async with self._lock:
            task = TaskRecord(owner_id=owner_id)
            self._tasks[task.task_id] = task
            return task.model_copy(deep=True)

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task else None

    async def set_running(self, task_id: str) -> None:
        async with self._lock:
            task = self._tasks[task_id]
            task.status = TaskStatus.running
            task.touch()

    async def set_succeeded(self, task_id: str, result: PipelineResult) -> None:
        async with self._lock:
            task = self._tasks[task_id]
            task.status = TaskStatus.succeeded
            task.result = result
            task.touch()

    async def set_failed(self, task_id: str, error: str) -> None:
        async with self._lock:
            task = self._tasks[task_id]
            task.status = TaskStatus.failed
            task.error = error
            task.touch()

