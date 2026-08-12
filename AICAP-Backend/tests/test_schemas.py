"""Unit tests for the Pydantic request/response schemas and their validators."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from models import AlarmTypeEnum, DifficultyEnum, ProviderEnum, RoleEnum
from schemas import (
    AlarmCreate,
    AlarmOut,
    AlarmUpdate,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserProfile,
)


# ==========================================
# RegisterRequest
# ==========================================

def test_register_request_defaults_to_user_role():
    data = RegisterRequest(name="Ann", email="ann@example.com", password="Password1")

    assert data.role is RoleEnum.USER


def test_register_request_allows_wellness_coach_self_registration():
    data = RegisterRequest(
        name="Coach",
        email="coach@example.com",
        password="Password1",
        role=RoleEnum.WELLNESS_COACH,
    )

    assert data.role is RoleEnum.WELLNESS_COACH


def test_register_request_rejects_admin_self_registration():
    with pytest.raises(ValidationError) as exc:
        RegisterRequest(
            name="Sneaky",
            email="sneaky@example.com",
            password="Password1",
            role=RoleEnum.ADMIN,
        )

    assert "role must be one of" in str(exc.value)


@pytest.mark.parametrize(
    "password,message",
    [
        ("password1", "uppercase"),
        ("PASSWORD1", "lowercase"),
        ("PasswordX", "digit"),
    ],
)
def test_register_request_enforces_password_strength(password, message):
    with pytest.raises(ValidationError) as exc:
        RegisterRequest(name="Ann", email="ann@example.com", password=password)

    assert message in str(exc.value)


def test_register_request_enforces_password_length():
    with pytest.raises(ValidationError):
        RegisterRequest(name="Ann", email="ann@example.com", password="Pass1")


@pytest.mark.parametrize("name", ["A", "x" * 101])
def test_register_request_enforces_name_bounds(name):
    with pytest.raises(ValidationError):
        RegisterRequest(name=name, email="ann@example.com", password="Password1")


def test_register_request_rejects_invalid_email():
    with pytest.raises(ValidationError):
        RegisterRequest(name="Ann", email="not-an-email", password="Password1")


# ==========================================
# LoginRequest / UpdateProfileRequest / responses
# ==========================================

def test_login_request_requires_non_empty_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="ann@example.com", password="")


def test_update_profile_request_omits_role_and_email_fields():
    fields = set(UpdateProfileRequest.model_fields)

    assert fields == {"name", "phone", "bio", "profile_picture"}


def test_update_profile_request_defaults_to_all_none():
    data = UpdateProfileRequest()

    assert data.model_dump() == {
        "name": None,
        "phone": None,
        "bio": None,
        "profile_picture": None,
    }


@pytest.mark.parametrize(
    "payload",
    [{"name": "A"}, {"phone": "1" * 21}, {"bio": "b" * 501}],
)
def test_update_profile_request_enforces_field_bounds(payload):
    with pytest.raises(ValidationError):
        UpdateProfileRequest(**payload)


def test_user_profile_reads_from_orm_object(make_user):
    user = make_user(email="orm@example.com", role=RoleEnum.ADMIN)

    profile = UserProfile.model_validate(user)

    assert profile.email == "orm@example.com"
    assert profile.role is RoleEnum.ADMIN
    assert profile.provider is ProviderEnum.LOCAL
    assert profile.bio is None


def test_token_response_defaults_to_bearer_type():
    token = TokenResponse(
        access_token="abc", role=RoleEnum.USER, name="Ann", email="ann@example.com"
    )

    assert token.token_type == "bearer"


# ==========================================
# AlarmCreate / AlarmBase validators
# ==========================================

@pytest.mark.parametrize("alarm_time", ["00:00", "07:05", "23:59", "12:30"])
def test_alarm_create_accepts_valid_times(alarm_time):
    alarm = AlarmCreate(title="Wake", alarm_time=alarm_time)

    assert alarm.alarm_time == alarm_time
    assert alarm.alarm_type is AlarmTypeEnum.DAILY
    assert alarm.difficulty_level is DifficultyEnum.EASY
    assert alarm.is_active is True
    assert alarm.sound == "default"
    assert alarm.vibration is True


@pytest.mark.parametrize(
    "alarm_time", ["24:00", "7:00", "07:60", "0700", "07:0", "", "aa:bb"]
)
def test_alarm_create_rejects_invalid_times(alarm_time):
    with pytest.raises(ValidationError) as exc:
        AlarmCreate(title="Wake", alarm_time=alarm_time)

    assert "24-hour" in str(exc.value)


def test_alarm_create_normalizes_repeat_days_casing_and_spacing():
    alarm = AlarmCreate(
        title="Wake",
        alarm_time="07:00",
        alarm_type=AlarmTypeEnum.WEEKDAY,
        repeat_days=[" mon ", "tue"],
    )

    assert alarm.repeat_days == ["MON", "TUE"]


def test_alarm_create_rejects_unknown_repeat_days():
    with pytest.raises(ValidationError) as exc:
        AlarmCreate(title="Wake", alarm_time="07:00", repeat_days=["MON", "FUNDAY"])

    assert "invalid repeat_days" in str(exc.value)


@pytest.mark.parametrize(
    "alarm_type", [AlarmTypeEnum.WEEKDAY, AlarmTypeEnum.WEEKEND]
)
def test_alarm_create_requires_repeat_days_for_weekday_and_weekend(alarm_type):
    with pytest.raises(ValidationError) as exc:
        AlarmCreate(
            title="Wake",
            alarm_time="07:00",
            alarm_type=alarm_type,
            repeat_days=None,
        )

    assert "repeat_days is required" in str(exc.value)

    with pytest.raises(ValidationError):
        AlarmCreate(
            title="Wake", alarm_time="07:00", alarm_type=alarm_type, repeat_days=[]
        )


def test_alarm_create_allows_missing_repeat_days_for_daily():
    alarm = AlarmCreate(
        title="Wake", alarm_time="07:00", alarm_type=AlarmTypeEnum.DAILY
    )

    assert alarm.repeat_days is None


def test_alarm_create_enforces_title_bounds():
    with pytest.raises(ValidationError):
        AlarmCreate(title="", alarm_time="07:00")
    with pytest.raises(ValidationError):
        AlarmCreate(title="t" * 101, alarm_time="07:00")


# ==========================================
# AlarmUpdate
# ==========================================

def test_alarm_update_allows_all_fields_omitted():
    update = AlarmUpdate()

    assert update.alarm_time is None
    assert update.repeat_days is None


def test_alarm_update_validates_time_when_provided():
    with pytest.raises(ValidationError):
        AlarmUpdate(alarm_time="25:00")

    assert AlarmUpdate(alarm_time="21:15").alarm_time == "21:15"


def test_alarm_update_normalizes_repeat_days():
    assert AlarmUpdate(repeat_days=["sat", " sun"]).repeat_days == ["SAT", "SUN"]


def test_alarm_update_does_not_require_days_for_weekday_type():
    # The cross-field requirement only applies at creation time.
    assert AlarmUpdate(alarm_type=AlarmTypeEnum.WEEKDAY).repeat_days is None


# ==========================================
# AlarmOut
# ==========================================

def test_alarm_out_splits_comma_separated_repeat_days(make_user, make_alarm):
    alarm = make_alarm(
        make_user(), repeat_days="MON,TUE,WED", alarm_type=AlarmTypeEnum.WEEKDAY
    )

    out = AlarmOut.model_validate(alarm)

    assert out.repeat_days == ["MON", "TUE", "WED"]
    assert out.snooze_count == 0
    assert out.adaptive_offset == 0
    assert isinstance(out.created_at, datetime)


def test_alarm_out_handles_empty_and_missing_repeat_days(make_user, make_alarm):
    user = make_user()

    assert AlarmOut.model_validate(make_alarm(user, repeat_days="")).repeat_days == []
    assert AlarmOut.model_validate(make_alarm(user)).repeat_days is None


def test_alarm_out_drops_empty_segments_in_repeat_days(make_user, make_alarm):
    alarm = make_alarm(make_user(), repeat_days="MON,,TUE,")

    assert AlarmOut.model_validate(alarm).repeat_days == ["MON", "TUE"]
