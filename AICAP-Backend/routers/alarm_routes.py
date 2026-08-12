from datetime import datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import User, Alarm, AlarmTypeEnum
from schemas import AlarmCreate, AlarmUpdate, AlarmOut, SnoozeRequest, DismissRequest
from scheduler import add_or_update_alarm_job, remove_alarm_job
from smart_adaptive import SmartAdaptiveAlgorithm

router = APIRouter(
    prefix="/alarms",
    tags=["Alarms"]
)

DEFAULT_SNOOZE_MINUTES = 5

DAY_MAP = {
    0: "MON",
    1: "TUE",
    2: "WED",
    3: "THU",
    4: "FRI",
    5: "SAT",
    6: "SUN"
}


# ==========================================
# Helpers for Day / Next Alarm Calculation
# ==========================================

def parse_alarm_time(alarm_time_str: str) -> time:
    hour, minute = map(int, alarm_time_str.split(":"))
    return time(hour=hour, minute=minute)


def calculate_next_trigger(alarm: Alarm, now: datetime) -> Optional[datetime]:
    if not alarm.is_active:
        return None

    # For SMART_ADAPTIVE alarms, use the adaptive time
    alarm_time_str = alarm.alarm_time
    if alarm.alarm_type == AlarmTypeEnum.SMART_ADAPTIVE:
        alarm_time_str = SmartAdaptiveAlgorithm.get_adaptive_alarm_time(alarm)
    
    at_time = parse_alarm_time(alarm_time_str)
    today_trigger = datetime.combine(now.date(), at_time)

    # Check next 7 days for the closest matching day
    for day_offset in range(8):
        check_dt = today_trigger + timedelta(days=day_offset)
        if check_dt <= now:
            continue

        weekday_idx = check_dt.weekday()  # 0=MON, 6=SUN
        day_str = DAY_MAP[weekday_idx]

        if alarm.alarm_type == AlarmTypeEnum.DAILY:
            return check_dt

        elif alarm.alarm_type == AlarmTypeEnum.WEEKDAY and weekday_idx in range(0, 5):
            return check_dt

        elif alarm.alarm_type == AlarmTypeEnum.WEEKEND and weekday_idx in (5, 6):
            return check_dt

        elif alarm.alarm_type == AlarmTypeEnum.ONE_TIME:
            return check_dt

        elif alarm.alarm_type == AlarmTypeEnum.SMART_ADAPTIVE:
            return check_dt

        elif alarm.repeat_days:
            days_list = [d.strip().upper() for d in alarm.repeat_days.split(",") if d]
            if day_str in days_list:
                return check_dt

    return None


# ==========================================
# Specialized Query Endpoints (Before /{id})
# ==========================================

@router.get("/today", response_model=List[AlarmOut])
def get_today_alarms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch active alarms scheduled to fire today for current user."""
    today_weekday = datetime.utcnow().weekday()
    today_code = DAY_MAP[today_weekday]
    is_weekend = today_weekday in (5, 6)

    active_alarms = (
        db.query(Alarm)
        .filter(Alarm.user_id == current_user.id, Alarm.is_active == True)
        .all()
    )

    today_alarms = []
    for alarm in active_alarms:
        if alarm.alarm_type in (AlarmTypeEnum.DAILY, AlarmTypeEnum.SMART_ADAPTIVE, AlarmTypeEnum.ONE_TIME):
            today_alarms.append(alarm)
        elif alarm.alarm_type == AlarmTypeEnum.WEEKDAY and not is_weekend:
            today_alarms.append(alarm)
        elif alarm.alarm_type == AlarmTypeEnum.WEEKEND and is_weekend:
            today_alarms.append(alarm)
        elif alarm.repeat_days:
            days = [d.strip().upper() for d in alarm.repeat_days.split(",") if d]
            if today_code in days:
                today_alarms.append(alarm)

    today_alarms.sort(key=lambda a: a.alarm_time)
    return today_alarms


@router.get("/upcoming", response_model=List[AlarmOut])
def get_upcoming_alarms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch active alarms for current user ordered by alarm time."""
    alarms = (
        db.query(Alarm)
        .filter(Alarm.user_id == current_user.id, Alarm.is_active == True)
        .order_by(Alarm.alarm_time.asc())
        .all()
    )
    return alarms


@router.post("/check-next")
def check_next_alarm(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find the next alarm that will trigger for current user."""
    active_alarms = (
        db.query(Alarm)
        .filter(Alarm.user_id == current_user.id, Alarm.is_active == True)
        .all()
    )

    if not active_alarms:
        return {"message": "No active alarms scheduled", "next_alarm": None}

    now = datetime.utcnow()
    next_pairs = []

    for alarm in active_alarms:
        next_dt = calculate_next_trigger(alarm, now)
        if next_dt:
            next_pairs.append((next_dt, alarm))

    if not next_pairs:
        return {"message": "No upcoming triggers found", "next_alarm": None}

    next_pairs.sort(key=lambda p: p[0])
    closest_dt, closest_alarm = next_pairs[0]
    time_remaining_seconds = int((closest_dt - now).total_seconds())

    return {
        "message": "Next alarm identified",
        "next_trigger_at": closest_dt.isoformat(),
        "time_remaining_seconds": time_remaining_seconds,
        "alarm": AlarmOut.from_orm(closest_alarm),
    }


# ==========================================
# Standard CRUD Endpoints
# ==========================================

@router.post("", response_model=AlarmOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=AlarmOut, status_code=status.HTTP_201_CREATED)
def create_alarm(
    data: AlarmCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new alarm scoped to current_user."""
    repeat_days_str = None
    if data.repeat_days:
        repeat_days_str = ",".join(data.repeat_days)

    alarm = Alarm(
        user_id=current_user.id,
        title=data.title,
        alarm_time=data.alarm_time,
        alarm_type=data.alarm_type,
        repeat_days=repeat_days_str,
        is_active=data.is_active,
        difficulty_level=data.difficulty_level,
        sound=data.sound,
        vibration=data.vibration,
    )

    db.add(alarm)
    db.commit()
    db.refresh(alarm)

    # Sync background job
    add_or_update_alarm_job(alarm)

    return alarm


@router.get("", response_model=List[AlarmOut])
@router.get("/", response_model=List[AlarmOut])
def list_alarms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all alarms owned by current user."""
    alarms = (
        db.query(Alarm)
        .filter(Alarm.user_id == current_user.id)
        .order_by(Alarm.created_at.desc())
        .all()
    )
    return alarms


@router.get("/{alarm_id}", response_model=AlarmOut)
def get_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch single alarm by ID with strict ownership validation."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    return alarm


@router.put("/{alarm_id}", response_model=AlarmOut)
def update_alarm(
    alarm_id: int,
    data: AlarmUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update alarm details with strict ownership check."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    if data.title is not None:
        alarm.title = data.title

    if data.alarm_time is not None:
        alarm.alarm_time = data.alarm_time

    if data.alarm_type is not None:
        alarm.alarm_type = data.alarm_type

    if data.repeat_days is not None:
        alarm.repeat_days = ",".join(data.repeat_days)

    if data.difficulty_level is not None:
        alarm.difficulty_level = data.difficulty_level

    if data.sound is not None:
        alarm.sound = data.sound

    if data.vibration is not None:
        alarm.vibration = data.vibration

    if data.is_active is not None:
        alarm.is_active = data.is_active

    db.commit()
    db.refresh(alarm)

    # Sync background job
    add_or_update_alarm_job(alarm)

    return alarm


@router.delete("/{alarm_id}")
def delete_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete alarm with strict ownership check."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    db.delete(alarm)
    db.commit()

    # Remove background job
    remove_alarm_job(alarm_id)

    return {"message": "Alarm deleted successfully", "id": alarm_id}


@router.patch("/{alarm_id}/enable", response_model=AlarmOut)
def enable_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable an alarm."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    alarm.is_active = True
    db.commit()
    db.refresh(alarm)

    # Sync background job
    add_or_update_alarm_job(alarm)

    return alarm


@router.patch("/{alarm_id}/disable", response_model=AlarmOut)
def disable_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable an alarm."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    alarm.is_active = False
    db.commit()
    db.refresh(alarm)

    # Remove background job
    remove_alarm_job(alarm_id)

    return alarm


@router.patch("/{alarm_id}/snooze", response_model=AlarmOut)
def snooze_alarm(
    alarm_id: int,
    snooze_minutes: Optional[int] = Query(default=None, ge=1, le=720),
    payload: Optional[SnoozeRequest] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Snooze an alarm for a specified duration.
    Records the snooze event for SMART_ADAPTIVE learning.

    The duration may be supplied as a query parameter or in a JSON body;
    it defaults to 5 minutes when neither is present.
    """
    if snooze_minutes is None and payload is not None:
        snooze_minutes = payload.snooze_minutes
    if snooze_minutes is None:
        snooze_minutes = DEFAULT_SNOOZE_MINUTES

    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    # Record snooze event for SMART_ADAPTIVE learning
    SmartAdaptiveAlgorithm.record_alarm_event(
        alarm_id=alarm.id,
        event_type="snooze",
        db=db,
        snooze_duration=snooze_minutes
    )

    # Calculate new alarm time
    try:
        hour, minute = map(int, alarm.alarm_time.split(":"))
        total_minutes = hour * 60 + minute + snooze_minutes
        total_minutes = total_minutes % (24 * 60)  # Handle day wrapping
        new_hour = total_minutes // 60
        new_minute = total_minutes % 60
        alarm.alarm_time = f"{new_hour:02d}:{new_minute:02d}"
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid alarm time format"
        )

    db.commit()
    db.refresh(alarm)

    # Sync background job with new time
    add_or_update_alarm_job(alarm)

    return alarm


@router.post("/{alarm_id}/dismiss")
def dismiss_alarm(
    alarm_id: int,
    seconds_to_dismiss: Optional[int] = Query(default=None, ge=0, le=86_400),
    payload: Optional[DismissRequest] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record alarm dismissal for SMART_ADAPTIVE learning.
    Disables ONE_TIME alarms after dismissal.

    The elapsed time may be supplied as a query parameter or in a JSON body;
    it defaults to 0 when neither is present.
    """
    if seconds_to_dismiss is None and payload is not None:
        seconds_to_dismiss = payload.seconds_to_dismiss
    if seconds_to_dismiss is None:
        seconds_to_dismiss = 0

    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )

    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied"
        )

    # Record dismiss event for SMART_ADAPTIVE learning
    SmartAdaptiveAlgorithm.record_alarm_event(
        alarm_id=alarm.id,
        event_type="dismiss",
        db=db,
        seconds_to_dismiss=seconds_to_dismiss
    )

    # Deactivate ONE_TIME alarms after dismissal
    if alarm.alarm_type == AlarmTypeEnum.ONE_TIME:
        alarm.is_active = False
        remove_alarm_job(alarm_id)
        db.commit()

    return {"message": "Alarm dismissed successfully", "alarm_id": alarm_id}
