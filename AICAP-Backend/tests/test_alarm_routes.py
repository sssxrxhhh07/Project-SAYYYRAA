"""Unit tests for the alarm CRUD/query endpoints and their scheduling helpers."""

from datetime import datetime, time

import pytest

from models import Alarm, AlarmTypeEnum, DifficultyEnum
from routers.alarm_routes import calculate_next_trigger, parse_alarm_time

# 2024-01-03 is a Wednesday, 2024-01-06 a Saturday.
WEDNESDAY = datetime(2024, 1, 3, 8, 0)
SATURDAY = datetime(2024, 1, 6, 8, 0)


# ==========================================
# parse_alarm_time
# ==========================================

@pytest.mark.parametrize(
    "value,expected", [("07:00", time(7, 0)), ("00:00", time(0, 0)), ("23:59", time(23, 59))]
)
def test_parse_alarm_time(value, expected):
    assert parse_alarm_time(value) == expected


def test_parse_alarm_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_alarm_time("bedtime")


# ==========================================
# calculate_next_trigger
# ==========================================

def test_next_trigger_is_none_for_inactive_alarm(make_user, make_alarm):
    alarm = make_alarm(make_user(), is_active=False)

    assert calculate_next_trigger(alarm, WEDNESDAY) is None


def test_daily_alarm_triggers_later_today_when_time_has_not_passed(
    make_user, make_alarm
):
    alarm = make_alarm(make_user(), alarm_time="09:30")

    assert calculate_next_trigger(alarm, WEDNESDAY) == datetime(2024, 1, 3, 9, 30)


def test_daily_alarm_rolls_over_to_tomorrow_when_time_has_passed(
    make_user, make_alarm
):
    alarm = make_alarm(make_user(), alarm_time="07:00")

    assert calculate_next_trigger(alarm, WEDNESDAY) == datetime(2024, 1, 4, 7, 0)


def test_weekday_alarm_skips_the_weekend(make_user, make_alarm):
    alarm = make_alarm(
        make_user(),
        alarm_time="07:00",
        alarm_type=AlarmTypeEnum.WEEKDAY,
        repeat_days="MON,TUE,WED,THU,FRI",
    )

    # Saturday 08:00 → next weekday occurrence is Monday.
    assert calculate_next_trigger(alarm, SATURDAY) == datetime(2024, 1, 8, 7, 0)


def test_weekend_alarm_waits_for_saturday(make_user, make_alarm):
    alarm = make_alarm(
        make_user(),
        alarm_time="09:00",
        alarm_type=AlarmTypeEnum.WEEKEND,
        repeat_days="SAT,SUN",
    )

    assert calculate_next_trigger(alarm, WEDNESDAY) == datetime(2024, 1, 6, 9, 0)


def test_one_time_alarm_returns_next_matching_slot(make_user, make_alarm):
    alarm = make_alarm(
        make_user(), alarm_time="09:30", alarm_type=AlarmTypeEnum.ONE_TIME
    )

    assert calculate_next_trigger(alarm, WEDNESDAY) == datetime(2024, 1, 3, 9, 30)


def test_smart_adaptive_alarm_uses_adaptive_offset(make_user, make_alarm):
    alarm = make_alarm(
        make_user(),
        alarm_time="09:00",
        alarm_type=AlarmTypeEnum.SMART_ADAPTIVE,
        adaptive_offset=45,
    )

    assert calculate_next_trigger(alarm, WEDNESDAY) == datetime(2024, 1, 3, 9, 45)


# ==========================================
# create / list / read
# ==========================================

def test_create_alarm_persists_and_returns_payload(client, make_user, auth_headers):
    user = make_user()

    response = client.post(
        "/alarms",
        headers=auth_headers(user),
        json={
            "title": "Morning run",
            "alarm_time": "06:15",
            "alarm_type": "WEEKDAY",
            "repeat_days": ["mon", "wed"],
            "difficulty_level": "HARD",
            "sound": "birds",
            "vibration": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Morning run"
    assert body["alarm_time"] == "06:15"
    assert body["repeat_days"] == ["MON", "WED"]
    assert body["difficulty_level"] == DifficultyEnum.HARD.value
    assert body["vibration"] is False
    assert body["user_id"] == user.id


def test_create_alarm_rejects_invalid_time(client, make_user, auth_headers):
    response = client.post(
        "/alarms",
        headers=auth_headers(make_user()),
        json={"title": "Bad", "alarm_time": "26:00"},
    )

    assert response.status_code == 422


def test_alarm_endpoints_require_authentication(client):
    assert client.get("/alarms").status_code == 401


def test_list_alarms_returns_only_own_alarms(
    client, make_user, make_alarm, auth_headers
):
    owner = make_user()
    other = make_user()
    make_alarm(owner, title="Mine")
    make_alarm(other, title="Theirs")

    body = client.get("/alarms", headers=auth_headers(owner)).json()

    assert [a["title"] for a in body] == ["Mine"]


def test_get_alarm_returns_owned_alarm(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user)

    response = client.get(f"/alarms/{alarm.id}", headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json()["id"] == alarm.id


def test_get_alarm_hides_other_users_alarm(
    client, make_user, make_alarm, auth_headers
):
    alarm = make_alarm(make_user())

    response = client.get(f"/alarms/{alarm.id}", headers=auth_headers(make_user()))

    assert response.status_code == 404
    assert response.json()["detail"] == "Alarm not found or access denied"


def test_get_alarm_returns_404_for_unknown_id(client, make_user, auth_headers):
    assert client.get("/alarms/999", headers=auth_headers(make_user())).status_code == 404


# ==========================================
# update / delete
# ==========================================

def test_update_alarm_applies_partial_changes(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, title="Old", alarm_time="07:00")

    response = client.put(
        f"/alarms/{alarm.id}",
        headers=auth_headers(user),
        json={"title": "New", "alarm_time": "08:45", "repeat_days": ["sat"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New"
    assert body["alarm_time"] == "08:45"
    assert body["repeat_days"] == ["SAT"]
    db.expire_all()
    assert db.get(type(alarm), alarm.id).alarm_time == "08:45"


def test_update_alarm_ignores_omitted_fields(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, title="Keep me", sound="chimes")

    body = client.put(
        f"/alarms/{alarm.id}", headers=auth_headers(user), json={"vibration": False}
    ).json()

    assert body["title"] == "Keep me"
    assert body["sound"] == "chimes"
    assert body["vibration"] is False


def test_update_alarm_can_change_type_difficulty_sound_and_state(
    client, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user)

    body = client.put(
        f"/alarms/{alarm.id}",
        headers=auth_headers(user),
        json={
            "alarm_type": "SMART_ADAPTIVE",
            "difficulty_level": "MEDIUM",
            "sound": "waves",
            "is_active": False,
        },
    ).json()

    assert body["alarm_type"] == AlarmTypeEnum.SMART_ADAPTIVE.value
    assert body["difficulty_level"] == DifficultyEnum.MEDIUM.value
    assert body["sound"] == "waves"
    assert body["is_active"] is False


def test_update_alarm_rejects_foreign_alarm(client, make_user, make_alarm, auth_headers):
    alarm = make_alarm(make_user())

    response = client.put(
        f"/alarms/{alarm.id}", headers=auth_headers(make_user()), json={"title": "Hijack"}
    )

    assert response.status_code == 404


def test_delete_alarm_removes_row(client, db, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user)
    alarm_id = alarm.id

    response = client.delete(f"/alarms/{alarm_id}", headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json()["id"] == alarm.id
    db.expire_all()
    assert db.query(Alarm).filter(Alarm.id == alarm_id).first() is None


def test_delete_alarm_rejects_foreign_alarm(client, make_user, make_alarm, auth_headers):
    alarm = make_alarm(make_user())

    assert (
        client.delete(f"/alarms/{alarm.id}", headers=auth_headers(make_user())).status_code
        == 404
    )


# ==========================================
# enable / disable
# ==========================================

def test_enable_alarm_activates_it(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, is_active=False)

    body = client.patch(f"/alarms/{alarm.id}/enable", headers=auth_headers(user)).json()

    assert body["is_active"] is True


def test_disable_alarm_deactivates_it(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user)

    body = client.patch(f"/alarms/{alarm.id}/disable", headers=auth_headers(user)).json()

    assert body["is_active"] is False


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_toggle_endpoints_reject_foreign_alarm(
    client, make_user, make_alarm, auth_headers, action
):
    alarm = make_alarm(make_user())

    response = client.patch(
        f"/alarms/{alarm.id}/{action}", headers=auth_headers(make_user())
    )

    assert response.status_code == 404


# ==========================================
# snooze / dismiss
# ==========================================

def test_snooze_alarm_shifts_time_and_records_event(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, alarm_time="07:00")

    body = client.patch(
        f"/alarms/{alarm.id}/snooze?snooze_minutes=15", headers=auth_headers(user)
    ).json()

    assert body["alarm_time"] == "07:15"
    assert body["snooze_count"] == 1
    assert body["last_snooze_time"] is not None


def test_snooze_alarm_defaults_to_five_minutes(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, alarm_time="07:00")

    body = client.patch(f"/alarms/{alarm.id}/snooze", headers=auth_headers(user)).json()

    assert body["alarm_time"] == "07:05"


def test_snooze_alarm_wraps_past_midnight(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, alarm_time="23:55")

    body = client.patch(
        f"/alarms/{alarm.id}/snooze?snooze_minutes=10", headers=auth_headers(user)
    ).json()

    assert body["alarm_time"] == "00:05"


def test_snooze_alarm_rejects_corrupt_stored_time(
    client, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, alarm_time="not-a-time")

    response = client.patch(f"/alarms/{alarm.id}/snooze", headers=auth_headers(user))

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid alarm time format"


def test_snooze_alarm_rejects_foreign_alarm(client, make_user, make_alarm, auth_headers):
    alarm = make_alarm(make_user())

    response = client.patch(
        f"/alarms/{alarm.id}/snooze", headers=auth_headers(make_user())
    )

    assert response.status_code == 404


def test_dismiss_alarm_records_event_and_statistics(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user)

    response = client.post(
        f"/alarms/{alarm.id}/dismiss?seconds_to_dismiss=12", headers=auth_headers(user)
    )

    assert response.status_code == 200
    assert response.json()["alarm_id"] == alarm.id
    db.expire_all()
    refreshed = db.get(type(alarm), alarm.id)
    assert refreshed.trigger_count == 1
    assert refreshed.avg_dismiss_time == 12


def test_dismiss_deactivates_one_time_alarm(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, alarm_type=AlarmTypeEnum.ONE_TIME)

    client.post(f"/alarms/{alarm.id}/dismiss", headers=auth_headers(user))

    db.expire_all()
    assert db.get(type(alarm), alarm.id).is_active is False


def test_dismiss_keeps_daily_alarm_active(client, db, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, alarm_type=AlarmTypeEnum.DAILY)

    client.post(f"/alarms/{alarm.id}/dismiss", headers=auth_headers(user))

    db.expire_all()
    assert db.get(type(alarm), alarm.id).is_active is True


def test_dismiss_alarm_rejects_foreign_alarm(client, make_user, make_alarm, auth_headers):
    alarm = make_alarm(make_user())

    response = client.post(f"/alarms/{alarm.id}/dismiss", headers=auth_headers(make_user()))

    assert response.status_code == 404


# ==========================================
# today / upcoming / check-next
# ==========================================

def test_today_endpoint_includes_daily_and_excludes_inactive(
    client, make_user, make_alarm, auth_headers
):
    user = make_user()
    make_alarm(user, title="Daily", alarm_time="08:00")
    make_alarm(user, title="Inactive", alarm_time="09:00", is_active=False)

    titles = [
        a["title"] for a in client.get("/alarms/today", headers=auth_headers(user)).json()
    ]

    assert titles == ["Daily"]


def test_today_endpoint_filters_by_weekday_or_weekend(
    client, make_user, make_alarm, auth_headers
):
    user = make_user()
    make_alarm(
        user,
        title="Weekday",
        alarm_time="07:00",
        alarm_type=AlarmTypeEnum.WEEKDAY,
        repeat_days="MON,TUE,WED,THU,FRI",
    )
    make_alarm(
        user,
        title="Weekend",
        alarm_time="10:00",
        alarm_type=AlarmTypeEnum.WEEKEND,
        repeat_days="SAT,SUN",
    )

    titles = [
        a["title"] for a in client.get("/alarms/today", headers=auth_headers(user)).json()
    ]

    is_weekend = datetime.utcnow().weekday() in (5, 6)
    assert titles == (["Weekend"] if is_weekend else ["Weekday"])


def test_today_endpoint_sorts_by_alarm_time(client, make_user, make_alarm, auth_headers):
    user = make_user()
    make_alarm(user, title="Late", alarm_time="21:00")
    make_alarm(user, title="Early", alarm_time="05:30")

    titles = [
        a["title"] for a in client.get("/alarms/today", headers=auth_headers(user)).json()
    ]

    assert titles == ["Early", "Late"]


def test_upcoming_endpoint_orders_by_time_and_scopes_to_user(
    client, make_user, make_alarm, auth_headers
):
    user = make_user()
    make_alarm(user, title="Noon", alarm_time="12:00")
    make_alarm(user, title="Dawn", alarm_time="04:00")
    make_alarm(make_user(), title="Other user", alarm_time="01:00")

    titles = [
        a["title"]
        for a in client.get("/alarms/upcoming", headers=auth_headers(user)).json()
    ]

    assert titles == ["Dawn", "Noon"]


def test_check_next_without_alarms(client, make_user, auth_headers):
    body = client.post("/alarms/check-next", headers=auth_headers(make_user())).json()

    assert body["next_alarm"] is None
    assert body["message"] == "No active alarms scheduled"


def test_check_next_returns_closest_alarm(client, make_user, make_alarm, auth_headers):
    user = make_user()
    make_alarm(user, title="Later today", alarm_time="23:59")
    make_alarm(user, title="Tomorrow", alarm_time="00:01")

    body = client.post("/alarms/check-next", headers=auth_headers(user)).json()

    assert body["message"] == "Next alarm identified"
    assert body["time_remaining_seconds"] > 0
    assert body["alarm"]["title"] in {"Later today", "Tomorrow"}
    assert body["next_trigger_at"] is not None
