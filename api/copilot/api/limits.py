"""Counters in Redis: the daily answer quota, the daily spend, and login attempts.

A quota unit is taken before a run starts and given back if the run
gives no answer (a clarifying question, an error, or a cancelled run).
Taking it first means two requests at once cannot both slip past the limit.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import redis

from copilot.config import Settings

_DAY_SECONDS = 48 * 3600  # keys outlive their day, for the daily totals
_MICRO = 1_000_000


@dataclass(frozen=True)
class Usage:
    used: int
    limit: int
    resets_at: datetime

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class Limits:
    def __init__(self, client: redis.Redis, settings: Settings, now=None):
        self.redis = client
        self.settings = settings
        self._zone = ZoneInfo(settings.quota_timezone)
        self._now = now or (lambda: datetime.now(self._zone))

    # The day

    def today(self) -> str:
        return self._now().astimezone(self._zone).strftime("%Y-%m-%d")

    def resets_at(self) -> datetime:
        now = self._now().astimezone(self._zone)
        return datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=self._zone)

    # Quota

    def _quota_key(self, user_id: str) -> str:
        return f"quota:{user_id}:{self.today()}"

    def usage(self, user_id: str) -> Usage:
        used = int(self.redis.get(self._quota_key(user_id)) or 0)
        return Usage(used, self.settings.daily_quota, self.resets_at())

    def take(self, user_id: str) -> bool:
        """Takes one unit. False, and nothing taken, when the user has none left."""
        key = self._quota_key(user_id)
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _DAY_SECONDS)
        used, _ = pipe.execute()
        if used > self.settings.daily_quota:
            self.redis.decr(key)
            return False
        return True

    def give_back(self, user_id: str) -> None:
        key = self._quota_key(user_id)
        if int(self.redis.decr(key)) < 0:
            self.redis.set(key, 0, ex=_DAY_SECONDS)

    # Spend, counted in millionths of a dollar so it adds up exactly

    def _spend_key(self) -> str:
        return f"spend:{self.today()}"

    def spent_today(self) -> float:
        return int(self.redis.get(self._spend_key()) or 0) / _MICRO

    def add_spend(self, dollars: float) -> None:
        key = self._spend_key()
        pipe = self.redis.pipeline()
        pipe.incrby(key, round(dollars * _MICRO))
        pipe.expire(key, _DAY_SECONDS)
        pipe.execute()

    def over_spend_cap(self) -> bool:
        cap = self.settings.daily_spend_cap_usd
        return cap is not None and self.spent_today() >= cap

    # Attempts (login per email and per IP, sign-up per IP)

    def attempt(self, key: str, limit: int, window_seconds: int) -> bool:
        """Counts an attempt. False when the limit for the window is used up."""
        full = f"attempts:{key}"
        pipe = self.redis.pipeline()
        pipe.incr(full)
        pipe.expire(full, window_seconds, nx=True)
        count, _ = pipe.execute()
        return count <= limit

    def clear(self, key: str) -> None:
        self.redis.delete(f"attempts:{key}")
