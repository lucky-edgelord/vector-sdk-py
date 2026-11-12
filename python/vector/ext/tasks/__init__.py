"""``vector.ext.tasks``: background loops, the same API as ``discord.ext.tasks``.

    @tasks.loop(minutes=5)
    async def heartbeat():
        ...

    heartbeat.start()
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import logging
from typing import Any, Callable, Coroutine, Generic, List, Optional, Sequence, Type, TypeVar, Union

from ...utils import MISSING, utcnow

_log = logging.getLogger("vector.ext.tasks")

__all__ = ("Loop", "loop")

LF = TypeVar("LF", bound=Callable[..., Coroutine[Any, Any, Any]])


class Loop(Generic[LF]):
    def __init__(self, coro: LF, seconds: float, hours: float, minutes: float,
                 time: Union[datetime.time, Sequence[datetime.time]], count: Optional[int], reconnect: bool,
                 name: Optional[str] = None):
        self.coro: LF = coro
        self.reconnect = reconnect
        self.count = count
        self._current_loop = 0
        self._task: Optional[asyncio.Task] = None
        self._injected: Any = None
        self._valid_exception: tuple = (OSError, asyncio.TimeoutError)
        self._before_loop: Optional[Callable[..., Any]] = None
        self._after_loop: Optional[Callable[..., Any]] = None
        self._error: Optional[Callable[..., Any]] = None
        self._is_being_cancelled = False
        self._has_failed = False
        self._stop_next_iteration = False
        self._last_iteration: Optional[datetime.datetime] = None
        self._next_iteration: Optional[datetime.datetime] = None
        self._name = name or getattr(coro, "__qualname__", "loop")
        if self.count is not None and self.count <= 0:
            raise ValueError("count must be greater than 0 or None.")
        self.change_interval(seconds=seconds, minutes=minutes, hours=hours, time=time)
        if not inspect.iscoroutinefunction(self.coro):
            raise TypeError(f"Expected coroutine function, not {type(self.coro).__name__!r}.")

    def __get__(self, obj: Any, objtype: Any) -> "Loop[LF]":
        if obj is None:
            return self
        copy: Loop[LF] = Loop(self.coro, seconds=self._seconds, hours=self._hours, minutes=self._minutes,
                              time=self._time, count=self.count, reconnect=self.reconnect, name=self._name)
        copy._injected = obj
        copy._before_loop = self._before_loop
        copy._after_loop = self._after_loop
        copy._error = self._error
        setattr(obj, self.coro.__name__, copy)
        return copy

    # -- properties -----------------------------------------------------------------------

    @property
    def seconds(self) -> Optional[float]:
        return self._seconds if self._time is MISSING else None

    @property
    def minutes(self) -> Optional[float]:
        return self._minutes if self._time is MISSING else None

    @property
    def hours(self) -> Optional[float]:
        return self._hours if self._time is MISSING else None

    @property
    def time(self) -> Optional[List[datetime.time]]:
        return list(self._time) if self._time is not MISSING else None

    @property
    def current_loop(self) -> int:
        return self._current_loop

    @property
    def next_iteration(self) -> Optional[datetime.datetime]:
        if self._task is None or self._task.done():
            return None
        return self._next_iteration

    # -- control --------------------------------------------------------------------------

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._injected is not None:
            args = (self._injected, *args)
        return await self.coro(*args, **kwargs)

    def start(self, *args: Any, **kwargs: Any) -> asyncio.Task:
        if self._task is not None and not self._task.done():
            raise RuntimeError("Task is already launched and is not completed.")
        if self._injected is not None:
            args = (self._injected, *args)
        self._has_failed = False
        self._task = asyncio.ensure_future(self._loop(*args, **kwargs))
        return self._task

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._stop_next_iteration = True

    def _can_be_cancelled(self) -> bool:
        return bool(not self._is_being_cancelled and self._task and not self._task.done())

    def cancel(self) -> None:
        if self._can_be_cancelled() and self._task is not None:
            self._task.cancel()

    def restart(self, *args: Any, **kwargs: Any) -> None:
        def restart_when_over(fut: Any, *, args: Any = args, kwargs: Any = kwargs) -> None:
            if self._task is not None:
                self._task.remove_done_callback(restart_when_over)
            self.start(*args, **kwargs)

        if self._can_be_cancelled() and self._task is not None:
            self._task.add_done_callback(restart_when_over)
            self._task.cancel()

    def add_exception_type(self, *exceptions: Type[BaseException]) -> None:
        self._valid_exception = (*self._valid_exception, *exceptions)

    def clear_exception_types(self) -> None:
        self._valid_exception = ()

    def remove_exception_type(self, *exceptions: Type[BaseException]) -> bool:
        old = len(self._valid_exception)
        self._valid_exception = tuple(x for x in self._valid_exception if x not in exceptions)
        return len(self._valid_exception) == old - len(exceptions)

    def get_task(self) -> Optional[asyncio.Task]:
        return self._task

    def is_being_cancelled(self) -> bool:
        return self._is_being_cancelled

    def failed(self) -> bool:
        return self._has_failed

    def is_running(self) -> bool:
        return not bool(self._task is None or self._task.done())

    # -- hooks ----------------------------------------------------------------------------

    def before_loop(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(coro):
            raise TypeError("Expected coroutine function")
        self._before_loop = coro
        return coro

    def after_loop(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(coro):
            raise TypeError("Expected coroutine function")
        self._after_loop = coro
        return coro

    def error(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(coro):
            raise TypeError("Expected coroutine function")
        self._error = coro
        return coro

    async def _call_hook(self, hook: Optional[Callable[..., Any]], *args: Any) -> None:
        if hook is None:
            return
        if self._injected is not None:
            await hook(self._injected, *args)
        else:
            await hook(*args)

    async def _default_error(self, *args: Any) -> None:
        exc = args[-1]
        _log.error("Unhandled exception in internal background task %r.", self._name, exc_info=exc)

    # -- scheduling -----------------------------------------------------------------------

    def change_interval(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0,
                        time: Union[datetime.time, Sequence[datetime.time]] = MISSING) -> None:
        if time is MISSING:
            seconds, minutes, hours = seconds or 0, minutes or 0, hours or 0
            sleep = seconds + (minutes * 60.0) + (hours * 3600.0)
            if sleep < 0:
                raise ValueError("Total number of seconds cannot be less than zero.")
            self._sleep = sleep
            self._seconds, self._minutes, self._hours = float(seconds), float(minutes), float(hours)
            self._time: Any = MISSING
        else:
            if any((seconds, minutes, hours)):
                raise TypeError("Cannot mix explicit time with relative time")
            times = [time] if isinstance(time, datetime.time) else list(time)
            self._time = sorted(t if t.tzinfo is not None else t.replace(tzinfo=datetime.timezone.utc) for t in times)
            self._sleep = self._seconds = self._minutes = self._hours = MISSING

    def _next_time(self, now: datetime.datetime) -> datetime.datetime:
        for t in self._time:
            candidate = datetime.datetime.combine(now.date(), t.replace(tzinfo=None), tzinfo=t.tzinfo)
            if candidate > now:
                return candidate
        first = self._time[0]
        return datetime.datetime.combine(now.date() + datetime.timedelta(days=1), first.replace(tzinfo=None), tzinfo=first.tzinfo)

    async def _sleep_until_next(self) -> None:
        if self._time is not MISSING:
            now = utcnow()
            self._next_iteration = self._next_time(now)
            await asyncio.sleep(max((self._next_iteration - now).total_seconds(), 0))
        else:
            self._next_iteration = utcnow() + datetime.timedelta(seconds=self._sleep)
            await asyncio.sleep(self._sleep)

    async def _loop(self, *args: Any, **kwargs: Any) -> None:
        await self._call_hook(self._before_loop)
        self._last_iteration = utcnow()
        try:
            if self._time is not MISSING:
                await self._sleep_until_next()
            while True:
                if self._stop_next_iteration:
                    return
                try:
                    await self.coro(*args, **kwargs)
                except self._valid_exception:
                    if not self.reconnect:
                        raise
                    await asyncio.sleep(5)
                    continue
                self._last_iteration = utcnow()
                if self._stop_next_iteration:
                    return
                self._current_loop += 1
                if self._current_loop == self.count:
                    break
                await self._sleep_until_next()
        except asyncio.CancelledError:
            self._is_being_cancelled = True
            raise
        except Exception as exc:
            self._has_failed = True
            if self._error is not None:
                await self._call_hook(self._error, exc)
            else:
                await self._default_error(exc)
            raise
        finally:
            await self._call_hook(self._after_loop)
            self._is_being_cancelled = False
            self._current_loop = 0
            self._stop_next_iteration = False


def loop(*, seconds: float = MISSING, minutes: float = MISSING, hours: float = MISSING,
         time: Union[datetime.time, Sequence[datetime.time]] = MISSING, count: Optional[int] = None,
         reconnect: bool = True, name: Optional[str] = None) -> Callable[[LF], Loop[LF]]:
    def decorator(func: LF) -> Loop[LF]:
        return Loop(func, seconds=seconds or 0, minutes=minutes or 0, hours=hours or 0, count=count, time=time,
                    reconnect=reconnect, name=name)

    return decorator

# placeholders for discord.py names (see vector._stubs)
from ..._stubs import fill as _fill_stubs  # noqa: E402

_fill_stubs(globals(), "tasks")
