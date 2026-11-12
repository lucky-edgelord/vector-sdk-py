"""Cooldowns and max-concurrency, as in ``discord.ext.commands``."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from .errors import MaxConcurrencyReached

__all__ = ("BucketType", "Cooldown", "CooldownMapping", "DynamicCooldownMapping", "MaxConcurrency")


class BucketType:
    default = 0
    user = 1
    guild = 2
    community = 2
    channel = 3
    member = 4
    category = 5
    role = 6

    @staticmethod
    def get_key(kind: int, ctx: Any) -> Any:
        msg = getattr(ctx, "message", ctx)
        author = getattr(msg, "author", None)
        npub = getattr(author, "npub", None)
        community = getattr(msg, "community", None)
        channel = getattr(msg, "channel", None)
        if kind == BucketType.user:
            return npub
        if kind == BucketType.guild:
            return (community or channel).id if (community or channel) else None
        if kind == BucketType.channel:
            return getattr(channel, "id", None)
        if kind == BucketType.member:
            return (getattr(community, "id", None), npub)
        if kind == BucketType.category:
            return getattr(channel, "category_id", None) or getattr(channel, "id", None)
        if kind == BucketType.role:
            roles = getattr(author, "roles", None)
            return roles[-1].id if roles else getattr(channel, "id", None)
        return None


class Cooldown:
    __slots__ = ("rate", "per", "_window", "_tokens", "_last")

    def __init__(self, rate: float, per: float):
        self.rate = int(rate)
        self.per = float(per)
        self._window = 0.0
        self._tokens = self.rate
        self._last = 0.0

    def get_tokens(self, current: Optional[float] = None) -> int:
        current = current or time.time()
        tokens = self._tokens
        if current > self._window + self.per:
            tokens = self.rate
        return tokens

    def get_retry_after(self, current: Optional[float] = None) -> float:
        current = current or time.time()
        if self.get_tokens(current) == 0:
            return self.per - (current - self._window)
        return 0.0

    def update_rate_limit(self, current: Optional[float] = None, *, tokens: int = 1) -> Optional[float]:
        current = current or time.time()
        self._last = current
        self._tokens = self.get_tokens(current)
        if self._tokens == self.rate:
            self._window = current
        self._tokens -= tokens
        if self._tokens < 0:
            self._tokens = 0
            return self.per - (current - self._window)
        return None

    def reset(self) -> None:
        self._tokens = self.rate
        self._last = 0.0

    def copy(self) -> "Cooldown":
        return Cooldown(self.rate, self.per)

    def __repr__(self) -> str:
        return f"<Cooldown rate={self.rate} per={self.per} window={self._window} tokens={self._tokens}>"


class CooldownMapping:
    def __init__(self, original: Optional[Cooldown], type: Any):
        self._cache: Dict[Any, Cooldown] = {}
        self._cooldown = original
        self._type = type

    def copy(self) -> "CooldownMapping":
        return CooldownMapping(self._cooldown, self._type)

    @property
    def valid(self) -> bool:
        return self._cooldown is not None

    @property
    def type(self) -> Any:
        return self._type

    @classmethod
    def from_cooldown(cls, rate: float, per: float, type: Any) -> "CooldownMapping":
        return cls(Cooldown(rate, per), type)

    def _bucket_key(self, ctx: Any) -> Any:
        if callable(self._type) and not isinstance(self._type, int):
            return self._type(ctx)
        return BucketType.get_key(self._type, ctx)

    def _verify_cache_integrity(self, current: Optional[float] = None) -> None:
        current = current or time.time()
        dead = [k for k, v in self._cache.items() if current > v._last + v.per]
        for k in dead:
            del self._cache[k]

    def create_bucket(self, ctx: Any) -> Optional[Cooldown]:
        return self._cooldown.copy() if self._cooldown else None

    def get_bucket(self, ctx: Any, current: Optional[float] = None) -> Optional[Cooldown]:
        if self._type == BucketType.default:
            return self._cooldown
        self._verify_cache_integrity(current)
        key = self._bucket_key(ctx)
        if key not in self._cache:
            bucket = self.create_bucket(ctx)
            if bucket is not None:
                self._cache[key] = bucket
        else:
            bucket = self._cache[key]
        return bucket

    def update_rate_limit(self, ctx: Any, current: Optional[float] = None, tokens: int = 1) -> Optional[float]:
        bucket = self.get_bucket(ctx, current)
        if bucket is None:
            return None
        return bucket.update_rate_limit(current, tokens=tokens)


class DynamicCooldownMapping(CooldownMapping):
    def __init__(self, factory: Callable[[Any], Optional[Cooldown]], type: Any):
        super().__init__(None, type)
        self._factory = factory

    @property
    def valid(self) -> bool:
        return True

    def create_bucket(self, ctx: Any) -> Optional[Cooldown]:
        return self._factory(ctx)


class MaxConcurrency:
    def __init__(self, number: int, *, per: Any, wait: bool):
        self.number = number
        self.per = per
        self.wait = wait
        self._mapping: Dict[Any, asyncio.Semaphore] = {}

    def copy(self) -> "MaxConcurrency":
        return MaxConcurrency(self.number, per=self.per, wait=self.wait)

    async def acquire(self, ctx: Any) -> None:
        key = BucketType.get_key(self.per, ctx)
        sem = self._mapping.get(key)
        if sem is None:
            sem = self._mapping[key] = asyncio.Semaphore(self.number)
        if not self.wait and sem.locked():
            raise MaxConcurrencyReached(self.number, self.per)
        await sem.acquire()

    async def release(self, ctx: Any) -> None:
        key = BucketType.get_key(self.per, ctx)
        sem = self._mapping.get(key)
        if sem is not None:
            sem.release()
