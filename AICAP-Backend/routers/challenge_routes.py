"""
Cognitive Challenge Routes — Module 4
=====================================
Start, validate and report on the challenges that gate alarm dismissal.

The correct answer never leaves the server: it is stored on the attempt row
and compared against submissions there. Timing and attempt counting are
enforced from server-side state only — the client's timer is UX.
"""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import challenge_engine as engine
from auth import get_current_user
from database import get_db
from models import (
    Alarm,
    AlarmTypeEnum,
    ChallengeAttempt,
    ChallengeStatusEnum,
    ChallengeTypeEnum,
    User,
)
from schemas import (
    AttemptOut,
    ChallengeOut,
    ChallengeStatsOut,
    StartChallengeRequest,
    SubmitAnswerRequest,
    SubmitResultOut,
    TypeBreakdown,
)
from scheduler import remove_alarm_job
from smart_adaptive import SmartAdaptiveAlgorithm

router = APIRouter(
    prefix="/challenges",
    tags=["Challenges"],
)


# ==========================================
# Helpers
# ==========================================

def _elapsed_seconds(attempt: ChallengeAttempt, now: datetime) -> int:
    return max(0, int((now - attempt.started_at).total_seconds()))


def _seconds_remaining(attempt: ChallengeAttempt, now: datetime) -> int:
    return max(0, attempt.time_limit_seconds - _elapsed_seconds(attempt, now))


def _load_attempt(attempt_id: int, user: User, db: Session) -> ChallengeAttempt:
    attempt = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.id == attempt_id, ChallengeAttempt.user_id == user.id)
        .first()
    )
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge attempt not found or access denied",
        )
    return attempt


def _public_metadata(attempt: ChallengeAttempt) -> dict:
    """Attempt metadata minus anything that would give the answer away."""
    metadata = json.loads(attempt.metadata_json) if attempt.metadata_json else {}
    for revealing_key in ("accepts", "order", "rule", "expression", "scrambled", "seed"):
        metadata.pop(revealing_key, None)
    return metadata


def _to_challenge_out(attempt: ChallengeAttempt, now: datetime) -> ChallengeOut:
    return ChallengeOut(
        attempt_id=attempt.id,
        alarm_id=attempt.alarm_id,
        challenge_type=attempt.challenge_type,
        difficulty=attempt.difficulty,
        prompt=attempt.prompt_snapshot,
        options=json.loads(attempt.options_json) if attempt.options_json else None,
        answer_format=attempt.answer_format,
        metadata=_public_metadata(attempt),
        time_limit_seconds=attempt.time_limit_seconds,
        seconds_remaining=_seconds_remaining(attempt, now),
        max_attempts=attempt.max_attempts,
        attempts_used=attempt.attempts_used,
        status=attempt.status,
        started_at=attempt.started_at,
    )


def _owned_alarm(alarm_id: int, user: User, db: Session) -> Alarm:
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found or access denied",
        )
    return alarm


def _resolve_attempt(
    attempt: ChallengeAttempt,
    user: User,
    db: Session,
    is_correct: bool,
    now: datetime,
) -> tuple[bool, int]:
    """
    Write the terminal state of an attempt and re-derive the user's level.

    Returns (fallback_available, consecutive_failures).
    """
    attempt.status = ChallengeStatusEnum.COMPLETED if is_correct else ChallengeStatusEnum.FAILED
    attempt.is_correct = is_correct
    attempt.completed_at = now
    attempt.time_taken_seconds = _elapsed_seconds(attempt, now)
    attempt.score = engine.calculate_score(
        difficulty=attempt.difficulty,
        time_taken=attempt.time_taken_seconds,
        time_limit=attempt.time_limit_seconds,
        attempts_used=attempt.attempts_used,
        is_correct=is_correct,
    )
    db.commit()

    # Re-run the rolling-window rules against the updated history.
    history = engine.recent_attempts(user.id, db)
    user.current_difficulty = engine.evaluate_difficulty(user.current_difficulty, history)
    db.commit()

    failures = engine.consecutive_failures(history)
    return failures >= engine.FALLBACK_AFTER_CONSECUTIVE_FAILURES, failures


# ==========================================
# Endpoints
# ==========================================

@router.post("/start", response_model=ChallengeOut, status_code=status.HTTP_201_CREATED)
def start_challenge(
    data: Optional[StartChallengeRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Select and generate a challenge, then open an attempt for it."""
    data = data or StartChallengeRequest()

    alarm = _owned_alarm(data.alarm_id, current_user, db) if data.alarm_id else None

    challenge_type, difficulty = engine.select_next_challenge(current_user, db, alarm)
    generated = engine.generate_challenge(challenge_type, difficulty, seed=data.seed)

    attempt = ChallengeAttempt(
        user_id=current_user.id,
        alarm_id=alarm.id if alarm else None,
        challenge_type=generated.type,
        difficulty=generated.difficulty,
        prompt_snapshot=generated.prompt,
        options_json=json.dumps(generated.options) if generated.options else None,
        metadata_json=json.dumps(generated.metadata) if generated.metadata else None,
        answer_format=generated.answer_format,
        correct_answer=generated.correct_answer,
        status=ChallengeStatusEnum.IN_PROGRESS,
        attempts_used=0,
        max_attempts=generated.max_attempts,
        time_limit_seconds=generated.time_limit_seconds,
        started_at=datetime.utcnow(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return _to_challenge_out(attempt, datetime.utcnow())


@router.get("/history", response_model=List[AttemptOut])
def challenge_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated attempt history for the current user, newest first."""
    return (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .order_by(ChallengeAttempt.started_at.desc(), ChallengeAttempt.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/stats", response_model=ChallengeStatsOut)
def challenge_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate performance: accuracy, average time, difficulty, streak."""
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .order_by(ChallengeAttempt.started_at.desc(), ChallengeAttempt.id.desc())
        .all()
    )
    resolved = [a for a in attempts if a.status != ChallengeStatusEnum.IN_PROGRESS]

    streak = 0
    for attempt in resolved:
        if attempt.status == ChallengeStatusEnum.COMPLETED:
            streak += 1
        else:
            break

    per_type = []
    for challenge_type in ChallengeTypeEnum:
        of_type = [a for a in resolved if a.challenge_type == challenge_type]
        if not of_type:
            continue
        times = [a.time_taken_seconds for a in of_type if a.time_taken_seconds is not None]
        per_type.append(
            TypeBreakdown(
                challenge_type=challenge_type,
                attempts=len(of_type),
                accuracy=engine.accuracy(of_type),
                average_time_seconds=sum(times) / len(times) if times else None,
            )
        )

    all_times = [a.time_taken_seconds for a in resolved if a.time_taken_seconds is not None]

    return ChallengeStatsOut(
        total_attempts=len(attempts),
        completed=sum(1 for a in resolved if a.status == ChallengeStatusEnum.COMPLETED),
        failed=sum(1 for a in resolved if a.status == ChallengeStatusEnum.FAILED),
        accuracy=engine.accuracy(resolved),
        average_time_seconds=sum(all_times) / len(all_times) if all_times else None,
        total_score=sum(a.score for a in attempts),
        current_difficulty=current_user.current_difficulty,
        current_streak=streak,
        per_type=per_type,
    )


@router.get("/{attempt_id}", response_model=ChallengeOut)
def get_challenge(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-fetch an attempt (for reload/reconnect) without revealing the answer."""
    attempt = _load_attempt(attempt_id, current_user, db)
    return _to_challenge_out(attempt, datetime.utcnow())


@router.post("/{attempt_id}/submit", response_model=SubmitResultOut)
def submit_answer(
    attempt_id: int,
    data: SubmitAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Validate an answer against server-side state.

    A correct answer resolves the attempt and records the alarm's "dismiss"
    event, so `seconds_to_dismiss` fed to SMART_ADAPTIVE is the time the user
    actually took to become alert rather than the time to tap a button.
    """
    attempt = _load_attempt(attempt_id, current_user, db)
    now = datetime.utcnow()

    if attempt.status != ChallengeStatusEnum.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Challenge already {attempt.status.value.lower()}",
        )

    # Time limit is enforced from the stored start timestamp, never from the client.
    if _elapsed_seconds(attempt, now) > attempt.time_limit_seconds:
        fallback_available, _ = _resolve_attempt(attempt, current_user, db, False, now)
        return SubmitResultOut(
            attempt_id=attempt.id,
            status=attempt.status,
            is_correct=False,
            attempts_used=attempt.attempts_used,
            attempts_remaining=0,
            time_taken_seconds=attempt.time_taken_seconds,
            score=attempt.score,
            difficulty=attempt.difficulty,
            next_difficulty=current_user.current_difficulty,
            fallback_available=fallback_available,
            message="Time's up on this one.",
        )

    attempt.attempts_used += 1
    is_correct = engine.is_answer_correct(attempt, data.answer)
    attempts_exhausted = attempt.attempts_used >= attempt.max_attempts

    if not is_correct and not attempts_exhausted:
        db.commit()
        remaining = attempt.max_attempts - attempt.attempts_used
        return SubmitResultOut(
            attempt_id=attempt.id,
            status=attempt.status,
            is_correct=False,
            attempts_used=attempt.attempts_used,
            attempts_remaining=remaining,
            time_taken_seconds=None,
            score=0,
            difficulty=attempt.difficulty,
            next_difficulty=current_user.current_difficulty,
            fallback_available=False,
            message=f"Not quite — {remaining} attempt{'s' if remaining != 1 else ''} left.",
        )

    fallback_available, _ = _resolve_attempt(attempt, current_user, db, is_correct, now)

    if is_correct and attempt.alarm_id:
        _record_dismissal(attempt, db)

    return SubmitResultOut(
        attempt_id=attempt.id,
        status=attempt.status,
        is_correct=is_correct,
        attempts_used=attempt.attempts_used,
        attempts_remaining=0,
        time_taken_seconds=attempt.time_taken_seconds,
        score=attempt.score,
        difficulty=attempt.difficulty,
        next_difficulty=current_user.current_difficulty,
        fallback_available=fallback_available,
        message="Solved — alarm off. Good morning." if is_correct else "Out of attempts on this one.",
    )


def _record_dismissal(attempt: ChallengeAttempt, db: Session) -> None:
    """Record the alarm dismissal that a passed challenge earns."""
    SmartAdaptiveAlgorithm.record_alarm_event(
        alarm_id=attempt.alarm_id,
        event_type="dismiss",
        db=db,
        seconds_to_dismiss=attempt.time_taken_seconds,
    )

    alarm = db.query(Alarm).filter(Alarm.id == attempt.alarm_id).first()
    if alarm and alarm.alarm_type == AlarmTypeEnum.ONE_TIME:
        alarm.is_active = False
        remove_alarm_job(alarm.id)
        db.commit()
