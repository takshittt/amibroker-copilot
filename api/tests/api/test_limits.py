from datetime import datetime
from zoneinfo import ZoneInfo

from copilot.api.limits import Limits
from copilot.config import Settings

IST = ZoneInfo("Asia/Kolkata")


def limits(redis_client, when, **changes):
    return Limits(redis_client, Settings(**changes), now=lambda: when)


def test_quota_is_taken_until_none_is_left(redis_client):
    made = limits(redis_client, datetime(2026, 10, 14, 10, 0, tzinfo=IST), daily_quota=2)
    assert made.take("u1")
    assert made.take("u1")
    assert not made.take("u1")
    assert made.usage("u1").used == 2
    assert made.usage("u1").remaining == 0
    assert made.usage("u2").used == 0


def test_giving_back_frees_a_unit_and_never_goes_below_zero(redis_client):
    made = limits(redis_client, datetime(2026, 10, 14, 10, 0, tzinfo=IST), daily_quota=1)
    assert made.take("u1")
    made.give_back("u1")
    assert made.take("u1")
    made.give_back("u1")
    made.give_back("u1")
    assert made.usage("u1").used == 0


def test_the_day_starts_at_midnight_india_time(redis_client):
    before = limits(redis_client, datetime(2026, 10, 14, 23, 59, tzinfo=IST), daily_quota=1)
    after = limits(redis_client, datetime(2026, 10, 15, 0, 1, tzinfo=IST), daily_quota=1)
    assert before.take("u1")
    assert not before.take("u1")
    assert after.take("u1")
    assert before.resets_at() == datetime(2026, 10, 15, 0, 0, tzinfo=IST)


def test_utc_late_evening_is_already_the_next_day_in_india(redis_client):
    # 19:00 UTC on the 14th is 00:30 on the 15th in India.
    made = limits(redis_client, datetime(2026, 10, 14, 19, 0, tzinfo=ZoneInfo("UTC")))
    assert made.today() == "2026-10-15"


def test_quota_keys_expire(redis_client):
    made = limits(redis_client, datetime(2026, 10, 14, 10, 0, tzinfo=IST))
    made.take("u1")
    assert 0 < redis_client.ttl("quota:u1:2026-10-14") <= 48 * 3600


def test_spend_adds_up_exactly_and_the_cap_is_checked(redis_client):
    made = limits(redis_client, datetime(2026, 10, 14, 10, 0, tzinfo=IST), daily_spend_cap_usd=0.3)
    for _ in range(3):
        assert not made.over_spend_cap()
        made.add_spend(0.1)
    assert made.spent_today() == 0.3
    assert made.over_spend_cap()


def test_no_cap_means_never_over(redis_client):
    made = limits(redis_client, datetime(2026, 10, 14, 10, 0, tzinfo=IST))
    made.add_spend(1000)
    assert not made.over_spend_cap()


def test_attempts_are_counted_in_a_window(redis_client):
    made = limits(redis_client, datetime(2026, 10, 14, 10, 0, tzinfo=IST))
    assert [made.attempt("login:x", 2, 60) for _ in range(3)] == [True, True, False]
    assert 0 < redis_client.ttl("attempts:login:x") <= 60
    made.clear("login:x")
    assert made.attempt("login:x", 2, 60)
