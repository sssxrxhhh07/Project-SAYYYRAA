"""Unit tests for the rule-based SMART_ADAPTIVE algorithm."""

from datetime import datetime, timedelta

import pytest

from models import Alarm, AlarmEvent, AlarmTypeEnum
from smart_adaptive import SmartAdaptiveAlgorithm as Algo


# ==========================================
# get_adaptive_alarm_time
# ==========================================

@pytest.mark.parametrize(
    "alarm_time,offset,expected",
    [
        ("07:00", 0, "07:00"),
        ("07:00", 5, "07:05"),
        ("07:00", -5, "06:55"),
        ("23:58", 5, "00:03"),      # wraps past midnight
        ("00:02", -5, "23:57"),     # wraps backwards past midnight
        ("09:30", 30, "10:00"),
    ],
)
def test_get_adaptive_alarm_time_applies_offset(alarm_time, offset, expected):
    alarm = Alarm(alarm_time=alarm_time, adaptive_offset=offset)
    assert Algo.get_adaptive_alarm_time(alarm) == expected


@pytest.mark.parametrize("bad_time", ["not-a-time", "7 oclock", ""])
def test_get_adaptive_alarm_time_returns_original_on_bad_format(bad_time):
    alarm = Alarm(alarm_time=bad_time, adaptive_offset=10)
    assert Algo.get_adaptive_alarm_time(alarm) == bad_time


def test_get_adaptive_alarm_time_returns_original_when_time_is_none():
    alarm = Alarm(alarm_time=None, adaptive_offset=10)
    assert Algo.get_adaptive_alarm_time(alarm) is None


# ==========================================
# should_trigger_now
# ==========================================

def test_should_trigger_now_true_for_matching_adaptive_time():
    alarm = Alarm(alarm_time="07:00", adaptive_offset=15)
    assert Algo.should_trigger_now(alarm, "07:15") is True


def test_should_trigger_now_false_for_raw_time_when_offset_applied():
    alarm = Alarm(alarm_time="07:00", adaptive_offset=15)
    assert Algo.should_trigger_now(alarm, "07:00") is False


# ==========================================
# metric helpers
# ==========================================

def test_calculate_avg_dismiss_time_averages_dismiss_events_only():
    events = [
        AlarmEvent(event_type="dismiss", seconds_to_dismiss=10),
        AlarmEvent(event_type="dismiss", seconds_to_dismiss=20),
        AlarmEvent(event_type="snooze", seconds_to_dismiss=999),
        AlarmEvent(event_type="dismiss", seconds_to_dismiss=None),
    ]
    assert Algo._calculate_avg_dismiss_time(events) == 15


def test_calculate_avg_dismiss_time_zero_without_dismiss_data():
    assert Algo._calculate_avg_dismiss_time([]) == 0
    assert Algo._calculate_avg_dismiss_time([AlarmEvent(event_type="snooze")]) == 0


def test_count_recent_snoozes():
    events = [
        AlarmEvent(event_type="snooze"),
        AlarmEvent(event_type="snooze"),
        AlarmEvent(event_type="dismiss"),
        AlarmEvent(event_type="missed"),
    ]
    assert Algo._count_recent_snoozes(events) == 2
    assert Algo._count_recent_snoozes([]) == 0


# ==========================================
# calculate_adaptive_offset
# ==========================================

def _add_events(db, alarm, specs):
    """specs: list of (event_type, seconds_to_dismiss) — spaced event times."""
    base = datetime.utcnow()
    for i, (event_type, seconds) in enumerate(specs):
        db.add(
            AlarmEvent(
                alarm_id=alarm.id,
                event_type=event_type,
                event_time=base - timedelta(minutes=i),
                seconds_to_dismiss=seconds,
            )
        )
    db.commit()


def test_offset_unchanged_below_min_trigger_count(db, make_user, make_alarm):
    alarm = make_alarm(make_user(), trigger_count=2, adaptive_offset=5)
    _add_events(db, alarm, [("dismiss", 120)])

    assert Algo.calculate_adaptive_offset(alarm, db) == 5


def test_offset_unchanged_when_no_events_recorded(db, make_user, make_alarm):
    alarm = make_alarm(make_user(), trigger_count=10, adaptive_offset=-5)

    assert Algo.calculate_adaptive_offset(alarm, db) == -5


def test_high_dismiss_time_shifts_alarm_later(db, make_user, make_alarm):
    alarm = make_alarm(make_user(), trigger_count=3, adaptive_offset=0)
    _add_events(db, alarm, [("dismiss", 60), ("dismiss", 40)])

    assert Algo.calculate_adaptive_offset(alarm, db) == Algo.ADJUSTMENT_INCREMENT


def test_high_snooze_count_shifts_alarm_later_more_aggressively(
    db, make_user, make_alarm
):
    alarm = make_alarm(make_user(), trigger_count=3, adaptive_offset=0)
    _add_events(
        db,
        alarm,
        [("snooze", None), ("snooze", None), ("snooze", None), ("dismiss", 15)],
    )

    assert Algo.calculate_adaptive_offset(alarm, db) == Algo.ADJUSTMENT_INCREMENT * 2


def test_low_dismiss_time_without_snoozes_shifts_alarm_earlier(
    db, make_user, make_alarm
):
    alarm = make_alarm(make_user(), trigger_count=5, adaptive_offset=0)
    _add_events(db, alarm, [("dismiss", 5), ("dismiss", 7)])

    assert Algo.calculate_adaptive_offset(alarm, db) == -Algo.ADJUSTMENT_INCREMENT


def test_mid_range_dismiss_time_leaves_offset_untouched(db, make_user, make_alarm):
    alarm = make_alarm(make_user(), trigger_count=5, adaptive_offset=10)
    _add_events(db, alarm, [("dismiss", 20), ("dismiss", 20)])

    assert Algo.calculate_adaptive_offset(alarm, db) == 10


def test_offset_clamped_to_max_positive(db, make_user, make_alarm):
    alarm = make_alarm(
        make_user(), trigger_count=5, adaptive_offset=Algo.MAX_OFFSET_MINUTES
    )
    _add_events(db, alarm, [("dismiss", 90)])

    assert Algo.calculate_adaptive_offset(alarm, db) == Algo.MAX_OFFSET_MINUTES


def test_offset_clamped_to_max_negative(db, make_user, make_alarm):
    alarm = make_alarm(
        make_user(), trigger_count=5, adaptive_offset=-Algo.MAX_OFFSET_MINUTES
    )
    _add_events(db, alarm, [("dismiss", 2)])

    assert Algo.calculate_adaptive_offset(alarm, db) == -Algo.MAX_OFFSET_MINUTES


def test_only_ten_most_recent_events_are_considered(db, make_user, make_alarm):
    alarm = make_alarm(make_user(), trigger_count=5, adaptive_offset=0)
    # 10 recent fast dismissals plus one very old slow dismissal that must be
    # excluded by the LIMIT 10 window.
    _add_events(db, alarm, [("dismiss", 5)] * 10)
    db.add(
        AlarmEvent(
            alarm_id=alarm.id,
            event_type="dismiss",
            event_time=datetime.utcnow() - timedelta(days=30),
            seconds_to_dismiss=100000,
        )
    )
    db.commit()

    assert Algo.calculate_adaptive_offset(alarm, db) == -Algo.ADJUSTMENT_INCREMENT


# ==========================================
# record_alarm_event
# ==========================================

def test_record_snooze_event_updates_counters(db, make_user, make_alarm):
    alarm = make_alarm(make_user())

    Algo.record_alarm_event(alarm.id, "snooze", db, snooze_duration=5)

    db.refresh(alarm)
    event = db.query(AlarmEvent).filter(AlarmEvent.alarm_id == alarm.id).one()
    assert event.event_type == "snooze"
    assert event.snooze_duration == 5
    assert alarm.snooze_count == 1
    assert alarm.last_snooze_time is not None
    assert alarm.trigger_count == 0


def test_record_dismiss_event_updates_rolling_average(db, make_user, make_alarm):
    alarm = make_alarm(make_user())

    Algo.record_alarm_event(alarm.id, "dismiss", db, seconds_to_dismiss=10)
    Algo.record_alarm_event(alarm.id, "dismiss", db, seconds_to_dismiss=20)

    db.refresh(alarm)
    assert alarm.trigger_count == 2
    assert alarm.avg_dismiss_time == 15


def test_record_dismiss_event_without_duration_keeps_average(
    db, make_user, make_alarm
):
    alarm = make_alarm(make_user(), avg_dismiss_time=12)

    Algo.record_alarm_event(alarm.id, "dismiss", db)

    db.refresh(alarm)
    assert alarm.trigger_count == 1
    assert alarm.avg_dismiss_time == 12


def test_record_event_recalculates_offset_only_for_smart_adaptive(
    db, make_user, make_alarm
):
    user = make_user()
    smart = make_alarm(
        user, alarm_type=AlarmTypeEnum.SMART_ADAPTIVE, trigger_count=5
    )
    daily = make_alarm(user, alarm_type=AlarmTypeEnum.DAILY, trigger_count=5)

    # Two slow dismissals: the offset is derived from events already committed,
    # so the adjustment lands on the second recording.
    for _ in range(2):
        Algo.record_alarm_event(smart.id, "dismiss", db, seconds_to_dismiss=120)
        Algo.record_alarm_event(daily.id, "dismiss", db, seconds_to_dismiss=120)

    db.refresh(smart)
    db.refresh(daily)
    assert smart.adaptive_offset == Algo.ADJUSTMENT_INCREMENT
    assert daily.adaptive_offset == 0


def test_record_event_for_missing_alarm_still_persists_nothing_extra(db):
    Algo.record_alarm_event(4242, "dismiss", db, seconds_to_dismiss=5)

    # No alarm row exists, so the pending event is never committed.
    assert db.query(AlarmEvent).count() == 0
