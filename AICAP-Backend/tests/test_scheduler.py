"""Unit tests for the APScheduler-backed alarm scheduling service."""

import pytest

import scheduler as scheduler_module
from models import AlarmTypeEnum
from scheduler import (
    add_or_update_alarm_job,
    remove_alarm_job,
    send_push_notification,
    start_scheduler,
    stop_scheduler,
    sync_all_active_alarms,
    trigger_alarm_job,
)


def _job(alarm):
    return scheduler_module.scheduler.get_job(f"alarm_{alarm.id}")


def _cron_fields(job):
    return {f.name: str(f) for f in job.trigger.fields}


# ==========================================
# add_or_update_alarm_job
# ==========================================

def test_daily_alarm_is_scheduled_every_day(make_user, make_alarm):
    alarm = make_alarm(make_user(), alarm_time="06:45")

    add_or_update_alarm_job(alarm)

    fields = _cron_fields(_job(alarm))
    assert fields["hour"] == "6"
    assert fields["minute"] == "45"
    assert fields["day_of_week"] == "*"


def test_weekday_alarm_is_scheduled_monday_to_friday(make_user, make_alarm):
    alarm = make_alarm(
        make_user(), alarm_type=AlarmTypeEnum.WEEKDAY, repeat_days="MON,TUE"
    )

    add_or_update_alarm_job(alarm)

    assert _cron_fields(_job(alarm))["day_of_week"] == "mon-fri"


def test_weekend_alarm_is_scheduled_saturday_and_sunday(make_user, make_alarm):
    alarm = make_alarm(
        make_user(), alarm_type=AlarmTypeEnum.WEEKEND, repeat_days="SAT,SUN"
    )

    add_or_update_alarm_job(alarm)

    assert _cron_fields(_job(alarm))["day_of_week"] == "sat,sun"


def test_one_time_alarm_is_scheduled(make_user, make_alarm):
    alarm = make_alarm(make_user(), alarm_type=AlarmTypeEnum.ONE_TIME)

    add_or_update_alarm_job(alarm)

    assert _job(alarm) is not None


def test_smart_adaptive_alarm_is_scheduled_at_adaptive_time(make_user, make_alarm):
    alarm = make_alarm(
        make_user(),
        alarm_time="07:00",
        alarm_type=AlarmTypeEnum.SMART_ADAPTIVE,
        adaptive_offset=20,
    )

    add_or_update_alarm_job(alarm)

    fields = _cron_fields(_job(alarm))
    assert (fields["hour"], fields["minute"]) == ("7", "20")


def test_job_args_carry_alarm_identity(make_user, make_alarm):
    user = make_user()
    alarm = make_alarm(user, title="Gym")

    add_or_update_alarm_job(alarm)

    assert list(_job(alarm).args) == [alarm.id, "Gym", user.id]


def test_inactive_alarm_is_not_scheduled(make_user, make_alarm):
    alarm = make_alarm(make_user(), is_active=False)

    add_or_update_alarm_job(alarm)

    assert _job(alarm) is None


def test_existing_job_is_replaced_on_update(make_user, make_alarm, db):
    alarm = make_alarm(make_user(), alarm_time="06:00")
    add_or_update_alarm_job(alarm)

    alarm.alarm_time = "08:15"
    db.commit()
    add_or_update_alarm_job(alarm)

    jobs = [j for j in scheduler_module.scheduler.get_jobs() if j.id == f"alarm_{alarm.id}"]
    assert len(jobs) == 1
    assert _cron_fields(jobs[0])["hour"] == "8"


def test_updating_to_inactive_removes_existing_job(make_user, make_alarm, db):
    alarm = make_alarm(make_user())
    add_or_update_alarm_job(alarm)

    alarm.is_active = False
    db.commit()
    add_or_update_alarm_job(alarm)

    assert _job(alarm) is None


@pytest.mark.parametrize("bad_time", ["not-a-time", "7pm", ""])
def test_invalid_alarm_time_is_not_scheduled(make_user, make_alarm, bad_time):
    alarm = make_alarm(make_user(), alarm_time=bad_time)

    add_or_update_alarm_job(alarm)

    assert _job(alarm) is None


# ==========================================
# remove_alarm_job / sync_all_active_alarms
# ==========================================

def test_remove_alarm_job_removes_scheduled_job(make_user, make_alarm):
    alarm = make_alarm(make_user())
    add_or_update_alarm_job(alarm)

    remove_alarm_job(alarm.id)

    assert _job(alarm) is None


def test_remove_alarm_job_is_a_noop_for_unknown_alarm():
    remove_alarm_job(9999)  # must not raise


def test_sync_all_active_alarms_registers_only_active_alarms(db, make_user, make_alarm):
    user = make_user()
    active_one = make_alarm(user, alarm_time="05:00")
    active_two = make_alarm(user, alarm_time="06:00")
    inactive = make_alarm(user, alarm_time="07:00", is_active=False)

    sync_all_active_alarms(db)

    assert _job(active_one) is not None
    assert _job(active_two) is not None
    assert _job(inactive) is None


def test_sync_all_active_alarms_opens_its_own_session(make_user, make_alarm):
    alarm = make_alarm(make_user())

    sync_all_active_alarms()

    assert _job(alarm) is not None


# ==========================================
# trigger_alarm_job / notification hook
# ==========================================

def test_trigger_alarm_job_notifies_for_active_alarm(make_user, make_alarm, monkeypatch):
    user = make_user()
    alarm = make_alarm(user, title="Standup")
    sent = []
    monkeypatch.setattr(
        scheduler_module,
        "send_push_notification",
        lambda user_id, alarm_id, title: sent.append((user_id, alarm_id, title)),
    )

    trigger_alarm_job(alarm.id, "Standup", user.id)

    assert sent == [(user.id, alarm.id, "Standup")]


def test_trigger_alarm_job_deactivates_one_time_alarm(
    db, make_user, make_alarm, monkeypatch
):
    user = make_user()
    alarm = make_alarm(user, alarm_type=AlarmTypeEnum.ONE_TIME)
    monkeypatch.setattr(
        scheduler_module, "send_push_notification", lambda **kwargs: None
    )

    trigger_alarm_job(alarm.id, alarm.title, user.id)

    db.expire_all()
    assert db.get(type(alarm), alarm.id).is_active is False


def test_trigger_alarm_job_skips_inactive_alarm(make_user, make_alarm, monkeypatch):
    user = make_user()
    alarm = make_alarm(user, is_active=False)
    sent = []
    monkeypatch.setattr(
        scheduler_module,
        "send_push_notification",
        lambda **kwargs: sent.append(kwargs),
    )

    trigger_alarm_job(alarm.id, alarm.title, user.id)

    assert sent == []


def test_trigger_alarm_job_skips_deleted_alarm(monkeypatch):
    sent = []
    monkeypatch.setattr(
        scheduler_module,
        "send_push_notification",
        lambda **kwargs: sent.append(kwargs),
    )

    trigger_alarm_job(4242, "Ghost", 1)

    assert sent == []


def test_trigger_alarm_job_swallows_notification_errors(
    make_user, make_alarm, monkeypatch
):
    user = make_user()
    alarm = make_alarm(user)

    def boom(**kwargs):
        raise RuntimeError("FCM down")

    monkeypatch.setattr(scheduler_module, "send_push_notification", boom)

    trigger_alarm_job(alarm.id, alarm.title, user.id)  # must not propagate


def test_send_push_notification_logs_alarm_details(caplog):
    with caplog.at_level("INFO", logger="scheduler"):
        send_push_notification(user_id=3, alarm_id=9, title="Meds")

    assert "User ID=3" in caplog.text
    assert "Alarm ID=9" in caplog.text
    assert "Meds" in caplog.text


# ==========================================
# start / stop
# ==========================================

def test_start_and_stop_scheduler_toggle_running_state(make_user, make_alarm):
    alarm = make_alarm(make_user())
    try:
        start_scheduler()
        assert scheduler_module.scheduler.running is True
        assert _job(alarm) is not None

        start_scheduler()  # idempotent
        assert scheduler_module.scheduler.running is True
    finally:
        stop_scheduler()

    assert scheduler_module.scheduler.running is False
    stop_scheduler()  # idempotent
