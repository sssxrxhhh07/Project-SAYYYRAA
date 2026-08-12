"""Integration tests for the Module 4 challenge endpoints."""

from datetime import datetime, timedelta

import pytest

import challenge_engine as engine
from models import (
    Alarm,
    AlarmEvent,
    AlarmTypeEnum,
    ChallengeAttempt,
    ChallengeStatusEnum,
    ChallengeTypeEnum,
    DifficultyEnum,
)


def _start(client, user, auth_headers, **body):
    response = client.post("/challenges/start", headers=auth_headers(user), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _correct_answer(db, attempt_id):
    return db.get(ChallengeAttempt, attempt_id).correct_answer


def _submit(client, user, auth_headers, attempt_id, answer):
    return client.post(
        f"/challenges/{attempt_id}/submit",
        headers=auth_headers(user),
        json={"answer": answer},
    )


# ==========================================
# Auth
# ==========================================

@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/challenges/start"),
        ("get", "/challenges/history"),
        ("get", "/challenges/stats"),
        ("get", "/challenges/1"),
        ("post", "/challenges/1/submit"),
    ],
)
def test_challenge_endpoints_require_authentication(client, method, path):
    assert getattr(client, method)(path).status_code == 401


# ==========================================
# POST /challenges/start
# ==========================================

def test_start_returns_a_playable_challenge_without_the_answer(
    client, db, make_user, auth_headers
):
    user = make_user()

    body = _start(client, user, auth_headers)

    assert "correct_answer" not in body
    assert body["status"] == "IN_PROGRESS"
    assert body["attempts_used"] == 0
    assert body["prompt"]
    assert body["max_attempts"] == engine.MAX_ATTEMPTS[DifficultyEnum(body["difficulty"])]
    assert 0 < body["seconds_remaining"] <= body["time_limit_seconds"]

    stored = db.get(ChallengeAttempt, body["attempt_id"])
    assert stored.correct_answer
    assert stored.prompt_snapshot == body["prompt"]


def test_start_persists_the_generated_problem_for_validation(
    client, db, make_user, auth_headers
):
    user = make_user()

    body = _start(client, user, auth_headers, seed=42)
    stored = db.get(ChallengeAttempt, body["attempt_id"])
    regenerated = engine.generate_challenge(stored.challenge_type, stored.difficulty, seed=42)

    assert stored.prompt_snapshot == regenerated.prompt
    assert stored.correct_answer == regenerated.correct_answer


def test_start_links_the_attempt_to_an_owned_alarm(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user)

    body = _start(client, user, auth_headers, alarm_id=alarm.id)

    assert body["alarm_id"] == alarm.id
    assert db.get(ChallengeAttempt, body["attempt_id"]).alarm_id == alarm.id


def test_start_rejects_a_foreign_alarm(client, make_user, make_alarm, auth_headers):
    alarm = make_alarm(make_user())

    response = client.post(
        "/challenges/start", headers=auth_headers(make_user()), json={"alarm_id": alarm.id}
    )

    assert response.status_code == 404


def test_start_honours_a_pinned_alarm_difficulty(client, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.HARD)

    body = _start(client, user, auth_headers, alarm_id=alarm.id)

    assert body["difficulty"] == "HARD"
    assert body["max_attempts"] == 1


def test_start_without_a_body_still_works(client, make_user, auth_headers):
    response = client.post("/challenges/start", headers=auth_headers(make_user()))

    assert response.status_code == 201


def test_start_never_leaks_answer_bearing_metadata(client, db, make_user, auth_headers):
    user = make_user()

    for _ in range(10):
        body = _start(client, user, auth_headers)
        stored = db.get(ChallengeAttempt, body["attempt_id"])
        leaked = {
            key
            for key, value in body["metadata"].items()
            if str(value) == stored.correct_answer
        }

        if stored.challenge_type == ChallengeTypeEnum.MEMORY:
            # A memory test has to show the sequence it later asks for.
            assert body["metadata"]["sequence"]
        else:
            assert not leaked
        assert "accepts" not in body["metadata"]
        assert "seed" not in body["metadata"]


# ==========================================
# GET /challenges/{id}
# ==========================================

def test_get_challenge_returns_the_same_prompt(client, db, make_user, auth_headers):
    user = make_user()
    started = _start(client, user, auth_headers)

    body = client.get(f"/challenges/{started['attempt_id']}", headers=auth_headers(user)).json()

    assert body["prompt"] == started["prompt"]
    assert "correct_answer" not in body


def test_get_challenge_rejects_another_users_attempt(client, make_user, auth_headers):
    started = _start(client, make_user(), auth_headers)

    response = client.get(
        f"/challenges/{started['attempt_id']}", headers=auth_headers(make_user())
    )

    assert response.status_code == 404


def test_get_unknown_challenge_returns_404(client, make_user, auth_headers):
    assert client.get("/challenges/9999", headers=auth_headers(make_user())).status_code == 404


# ==========================================
# POST /challenges/{id}/submit
# ==========================================

def test_correct_answer_completes_the_attempt_and_scores_it(
    client, db, make_user, auth_headers
):
    user = make_user()
    started = _start(client, user, auth_headers)

    body = _submit(
        client, user, auth_headers, started["attempt_id"], _correct_answer(db, started["attempt_id"])
    ).json()

    assert body["is_correct"] is True
    assert body["status"] == "COMPLETED"
    assert body["score"] > 0
    assert body["attempts_used"] == 1
    assert body["attempts_remaining"] == 0
    assert body["fallback_available"] is False

    db.expire_all()
    stored = db.get(ChallengeAttempt, started["attempt_id"])
    assert stored.completed_at is not None
    assert stored.is_correct is True
    assert stored.time_taken_seconds is not None
    assert stored.score == body["score"]


def test_wrong_answer_leaves_retries_before_exhaustion(client, db, make_user, auth_headers):
    user = make_user()
    started = _start(client, user, auth_headers)
    db.get(ChallengeAttempt, started["attempt_id"]).max_attempts = 3
    db.commit()

    body = _submit(client, user, auth_headers, started["attempt_id"], "definitely wrong").json()

    assert body["is_correct"] is False
    assert body["status"] == "IN_PROGRESS"
    assert body["attempts_used"] == 1
    assert body["attempts_remaining"] == 2
    assert body["score"] == 0
    assert body["fallback_available"] is False


def test_exhausting_attempts_fails_the_attempt(client, db, make_user, auth_headers):
    user = make_user()
    started = _start(client, user, auth_headers)
    attempt = db.get(ChallengeAttempt, started["attempt_id"])
    attempt.max_attempts = 2
    db.commit()

    _submit(client, user, auth_headers, attempt.id, "wrong once")
    body = _submit(client, user, auth_headers, attempt.id, "wrong twice").json()

    assert body["status"] == "FAILED"
    assert body["is_correct"] is False
    assert body["score"] == 0
    assert body["attempts_used"] == 2

    db.expire_all()
    assert db.get(ChallengeAttempt, attempt.id).status == ChallengeStatusEnum.FAILED


def test_a_hard_attempt_gets_a_single_shot(client, db, make_user, make_alarm, auth_headers):
    user = make_user()
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.HARD)
    started = _start(client, user, auth_headers, alarm_id=alarm.id)

    body = _submit(client, user, auth_headers, started["attempt_id"], "wrong").json()

    assert body["status"] == "FAILED"
    assert body["attempts_remaining"] == 0


def test_submitting_after_the_time_limit_fails_the_attempt(
    client, db, make_user, auth_headers
):
    user = make_user()
    started = _start(client, user, auth_headers)
    attempt = db.get(ChallengeAttempt, started["attempt_id"])
    attempt.started_at = datetime.utcnow() - timedelta(seconds=attempt.time_limit_seconds + 5)
    db.commit()

    body = _submit(client, user, auth_headers, attempt.id, _correct_answer(db, attempt.id)).json()

    assert body["is_correct"] is False
    assert body["status"] == "FAILED"
    assert body["score"] == 0
    assert body["message"] == "Time's up on this one."


def test_elapsed_time_comes_from_the_server_not_the_client(
    client, db, make_user, auth_headers
):
    user = make_user()
    started = _start(client, user, auth_headers)
    attempt = db.get(ChallengeAttempt, started["attempt_id"])
    attempt.started_at = datetime.utcnow() - timedelta(seconds=30)
    db.commit()

    _submit(client, user, auth_headers, attempt.id, _correct_answer(db, attempt.id))

    db.expire_all()
    assert db.get(ChallengeAttempt, attempt.id).time_taken_seconds >= 30


def test_attempt_counting_ignores_client_supplied_values(
    client, db, make_user, auth_headers
):
    user = make_user()
    started = _start(client, user, auth_headers)
    attempt = db.get(ChallengeAttempt, started["attempt_id"])
    attempt.max_attempts = 3
    db.commit()

    response = client.post(
        f"/challenges/{attempt.id}/submit",
        headers=auth_headers(user),
        json={"answer": "wrong", "attempts_used": 99},
    )

    assert response.json()["attempts_used"] == 1


def test_resubmitting_a_resolved_attempt_conflicts(client, db, make_user, auth_headers):
    user = make_user()
    started = _start(client, user, auth_headers)
    _submit(client, user, auth_headers, started["attempt_id"], _correct_answer(db, started["attempt_id"]))

    response = _submit(client, user, auth_headers, started["attempt_id"], "again")

    assert response.status_code == 409


def test_submitting_another_users_attempt_is_denied(client, db, make_user, auth_headers):
    owner = make_user()
    started = _start(client, owner, auth_headers)

    response = _submit(client, make_user(), auth_headers, started["attempt_id"], "x")

    assert response.status_code == 404


def test_submit_requires_an_answer_field(client, make_user, auth_headers):
    user = make_user()
    started = _start(client, user, auth_headers)

    response = client.post(
        f"/challenges/{started['attempt_id']}/submit", headers=auth_headers(user), json={}
    )

    assert response.status_code == 422


# ==========================================
# Alarm integration
# ==========================================

def test_solving_a_challenge_records_the_alarm_dismissal(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user)
    started = _start(client, user, auth_headers, alarm_id=alarm.id)

    _submit(client, user, auth_headers, started["attempt_id"], _correct_answer(db, started["attempt_id"]))

    db.expire_all()
    events = db.query(AlarmEvent).filter(AlarmEvent.alarm_id == alarm.id).all()
    assert [e.event_type for e in events] == ["dismiss"]
    assert db.get(Alarm, alarm.id).trigger_count == 1


def test_solving_a_challenge_deactivates_a_one_time_alarm(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, alarm_type=AlarmTypeEnum.ONE_TIME)
    started = _start(client, user, auth_headers, alarm_id=alarm.id)

    _submit(client, user, auth_headers, started["attempt_id"], _correct_answer(db, started["attempt_id"]))

    db.expire_all()
    assert db.get(Alarm, alarm.id).is_active is False


def test_failing_a_challenge_leaves_the_alarm_ringing(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.HARD)
    started = _start(client, user, auth_headers, alarm_id=alarm.id)

    _submit(client, user, auth_headers, started["attempt_id"], "nope")

    db.expire_all()
    assert db.query(AlarmEvent).filter(AlarmEvent.alarm_id == alarm.id).count() == 0
    assert db.get(Alarm, alarm.id).is_active is True


def test_deleting_an_alarm_removes_its_attempts(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user)
    started = _start(client, user, auth_headers, alarm_id=alarm.id)

    assert client.delete(f"/alarms/{alarm.id}", headers=auth_headers(user)).status_code == 200

    db.expire_all()
    assert db.get(ChallengeAttempt, started["attempt_id"]) is None


# ==========================================
# Fallback / escalation
# ==========================================

def test_fallback_unlocks_after_three_consecutive_failures(
    client, db, make_user, make_alarm, auth_headers
):
    user = make_user()
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.HARD)

    results = []
    for _ in range(engine.FALLBACK_AFTER_CONSECUTIVE_FAILURES):
        started = _start(client, user, auth_headers, alarm_id=alarm.id)
        results.append(_submit(client, user, auth_headers, started["attempt_id"], "nope").json())

    assert [r["fallback_available"] for r in results] == [False, False, True]
    # Difficulty was walked back down on the way, so the alarm stayed beatable.
    assert results[-1]["next_difficulty"] == "EASY"


def test_a_success_relocks_the_fallback(client, db, make_user, auth_headers):
    user = make_user()
    for _ in range(engine.FALLBACK_AFTER_CONSECUTIVE_FAILURES):
        started = _start(client, user, auth_headers)
        db.get(ChallengeAttempt, started["attempt_id"]).max_attempts = 1
        db.commit()
        _submit(client, user, auth_headers, started["attempt_id"], "nope")

    started = _start(client, user, auth_headers)
    body = _submit(
        client, user, auth_headers, started["attempt_id"], _correct_answer(db, started["attempt_id"])
    ).json()

    assert body["fallback_available"] is False


# ==========================================
# Difficulty progression through the API
# ==========================================

def test_a_streak_of_fast_wins_raises_the_users_level(client, db, make_user, auth_headers):
    user = make_user()
    user_id = user.id

    for _ in range(engine.MIN_ATTEMPTS_BEFORE_ADJUST):
        started = _start(client, user, auth_headers)
        _submit(
            client, user, auth_headers, started["attempt_id"], _correct_answer(db, started["attempt_id"])
        )

    db.expire_all()
    assert db.get(type(user), user_id).current_difficulty == DifficultyEnum.MEDIUM
    assert _start(client, user, auth_headers)["difficulty"] == "MEDIUM"


def test_repeated_failures_lower_the_users_level(client, db, make_user, auth_headers):
    user = make_user()
    user.current_difficulty = DifficultyEnum.HARD
    db.commit()
    user_id = user.id

    levels = []
    for _ in range(3):
        started = _start(client, user, auth_headers)
        db.get(ChallengeAttempt, started["attempt_id"]).max_attempts = 1
        db.commit()
        levels.append(
            _submit(client, user, auth_headers, started["attempt_id"], "nope").json()["next_difficulty"]
        )

    # One failure is noise; the second and third each cost a level.
    assert levels == ["HARD", "MEDIUM", "EASY"]
    db.expire_all()
    assert db.get(type(user), user_id).current_difficulty == DifficultyEnum.EASY


# ==========================================
# GET /challenges/history and /stats
# ==========================================

def test_history_is_newest_first_and_paginated(client, make_user, make_attempt, auth_headers):
    user = make_user()
    for index in range(3):
        make_attempt(user, prompt_snapshot=f"q{index}")

    all_rows = client.get("/challenges/history", headers=auth_headers(user)).json()
    page = client.get("/challenges/history?limit=1&offset=1", headers=auth_headers(user)).json()

    assert [row["prompt_snapshot"] for row in all_rows] == ["q2", "q1", "q0"]
    assert [row["prompt_snapshot"] for row in page] == ["q1"]


def test_history_excludes_other_users_attempts(client, make_user, make_attempt, auth_headers):
    mine, theirs = make_user(), make_user()
    make_attempt(mine, prompt_snapshot="mine")
    make_attempt(theirs, prompt_snapshot="theirs")

    rows = client.get("/challenges/history", headers=auth_headers(mine)).json()

    assert [row["prompt_snapshot"] for row in rows] == ["mine"]


def test_history_rejects_an_oversized_limit(client, make_user, auth_headers):
    response = client.get("/challenges/history?limit=500", headers=auth_headers(make_user()))

    assert response.status_code == 422


def test_stats_are_empty_for_a_new_user(client, make_user, auth_headers):
    body = client.get("/challenges/stats", headers=auth_headers(make_user())).json()

    assert body == {
        "total_attempts": 0,
        "completed": 0,
        "failed": 0,
        "accuracy": None,
        "average_time_seconds": None,
        "total_score": 0,
        "current_difficulty": "EASY",
        "current_streak": 0,
        "per_type": [],
    }


def test_stats_aggregate_accuracy_streak_and_breakdown(
    client, make_user, make_attempt, auth_headers
):
    user = make_user()
    make_attempt(
        user,
        challenge_type=ChallengeTypeEnum.MATH,
        status=ChallengeStatusEnum.FAILED,
        is_correct=False,
        time_taken_seconds=60,
        score=0,
    )
    make_attempt(user, challenge_type=ChallengeTypeEnum.MATH, time_taken_seconds=20, score=10)
    make_attempt(user, challenge_type=ChallengeTypeEnum.RIDDLE, time_taken_seconds=40, score=15)

    body = client.get("/challenges/stats", headers=auth_headers(user)).json()

    assert body["total_attempts"] == 3
    assert body["completed"] == 2
    assert body["failed"] == 1
    assert body["accuracy"] == pytest.approx(2 / 3)
    assert body["average_time_seconds"] == pytest.approx(40)
    assert body["total_score"] == 25
    assert body["current_streak"] == 2

    breakdown = {row["challenge_type"]: row for row in body["per_type"]}
    assert breakdown["MATH"]["attempts"] == 2
    assert breakdown["MATH"]["accuracy"] == pytest.approx(0.5)
    assert breakdown["MATH"]["average_time_seconds"] == pytest.approx(40)
    assert breakdown["RIDDLE"]["accuracy"] == 1.0
    assert "QUICK_QUIZ" not in breakdown


def test_stats_ignore_in_progress_attempts(client, db, make_user, auth_headers):
    user = make_user()
    _start(client, user, auth_headers)

    body = client.get("/challenges/stats", headers=auth_headers(user)).json()

    assert body["total_attempts"] == 1
    assert body["completed"] == 0
    assert body["failed"] == 0
    assert body["accuracy"] is None
