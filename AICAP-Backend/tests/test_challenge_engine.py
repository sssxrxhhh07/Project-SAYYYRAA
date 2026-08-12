"""Unit tests for the Module 4 cognitive challenge engine."""

import json
import random

import pytest

import challenge_engine as engine
from models import ChallengeStatusEnum, ChallengeTypeEnum, DifficultyEnum

ALL_TYPES = list(ChallengeTypeEnum)
ALL_DIFFICULTIES = list(DifficultyEnum)
REPEATS = 100

VALID_FORMATS = {"text", "number", "mcq", "sequence"}


# ==========================================
# evaluate_arithmetic
# ==========================================

@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 3", 5),
        ("10 − 4", 6),
        ("6 × 7", 42),
        ("2 × 3 + 4", 10),
        ("2 + 3 × 4", 14),
        ("5 × (4 − 1) + 2 × 3", 21),
        ("-7 + 10", 3),
    ],
)
def test_evaluate_arithmetic(expression, expected):
    assert engine.evaluate_arithmetic(expression) == expected


@pytest.mark.parametrize("expression", ["8 / 2", "__import__('os')", "2 ** 8"])
def test_evaluate_arithmetic_rejects_unsupported_expressions(expression):
    with pytest.raises(ValueError):
        engine.evaluate_arithmetic(expression)


# ==========================================
# generate_challenge — shape contract
# ==========================================

@pytest.mark.parametrize("challenge_type", ALL_TYPES)
@pytest.mark.parametrize("difficulty", ALL_DIFFICULTIES)
def test_generator_contract_holds_across_repeats(challenge_type, difficulty):
    for seed in range(REPEATS):
        challenge = engine.generate_challenge(challenge_type, difficulty, seed=seed)

        assert challenge.type == challenge_type
        assert challenge.difficulty == difficulty
        assert challenge.prompt.strip()
        assert str(challenge.correct_answer).strip()
        assert challenge.answer_format in VALID_FORMATS
        assert challenge.time_limit_seconds > 0
        assert challenge.max_attempts == engine.MAX_ATTEMPTS[difficulty]
        assert isinstance(challenge.metadata, dict)

        if challenge.answer_format == "mcq":
            assert challenge.options
            assert challenge.correct_answer in challenge.options
            assert len(set(challenge.options)) == len(challenge.options)
        else:
            assert challenge.options is None

        # The answer travels in its own field only, never inside metadata.
        assert "correct_answer" not in challenge.metadata


def test_generate_challenge_is_deterministic_for_a_seed():
    for challenge_type in ALL_TYPES:
        first = engine.generate_challenge(challenge_type, DifficultyEnum.MEDIUM, seed=99)
        second = engine.generate_challenge(challenge_type, DifficultyEnum.MEDIUM, seed=99)

        assert (first.prompt, first.correct_answer, first.options) == (
            second.prompt,
            second.correct_answer,
            second.options,
        )


def test_generate_challenge_varies_without_a_shared_seed():
    prompts = {
        engine.generate_challenge(ChallengeTypeEnum.MATH, DifficultyEnum.HARD, seed=seed).prompt
        for seed in range(30)
    }

    assert len(prompts) > 1


def test_generate_challenge_rejects_unknown_type():
    with pytest.raises(ValueError):
        engine.generate_challenge("SUDOKU", DifficultyEnum.EASY)


# ==========================================
# Difficulty actually changes the problem
# ==========================================

def test_math_difficulty_scales_operation_count():
    counts = {}
    for difficulty in ALL_DIFFICULTIES:
        prompt = engine.generate_challenge(ChallengeTypeEnum.MATH, difficulty, seed=3).prompt
        counts[difficulty] = sum(prompt.count(op) for op in ("+", "−", "×"))

    assert counts[DifficultyEnum.EASY] < counts[DifficultyEnum.MEDIUM] < counts[DifficultyEnum.HARD]


def test_logic_puzzle_difficulty_scales_clue_count():
    sizes = [
        len(engine.generate_challenge(ChallengeTypeEnum.LOGIC_PUZZLE, difficulty, seed=1).options)
        for difficulty in ALL_DIFFICULTIES
    ]

    assert sizes == [3, 5, 7]


def test_memory_difficulty_scales_sequence_length_and_display_time():
    for difficulty in ALL_DIFFICULTIES:
        challenge = engine.generate_challenge(ChallengeTypeEnum.MEMORY, difficulty, seed=1)

        assert len(challenge.metadata["sequence"]) == engine.MEMORY_SEQUENCE_LENGTH[difficulty]
        assert challenge.metadata["display_seconds"] == engine.MEMORY_DISPLAY_SECONDS[difficulty]
        assert challenge.time_limit_seconds == engine.MEMORY_TIME_LIMIT_SECONDS[difficulty]


def test_word_game_difficulty_scales_word_length():
    lengths = [
        len(engine.generate_challenge(ChallengeTypeEnum.WORD_GAME, difficulty, seed=2).correct_answer)
        for difficulty in ALL_DIFFICULTIES
    ]

    assert lengths[0] < lengths[1] < lengths[2]


def test_word_game_scramble_differs_from_the_answer():
    for seed in range(REPEATS):
        challenge = engine.generate_challenge(ChallengeTypeEnum.WORD_GAME, DifficultyEnum.EASY, seed=seed)

        assert challenge.metadata["scrambled"] != challenge.correct_answer
        assert sorted(challenge.metadata["scrambled"]) == sorted(challenge.correct_answer)


def test_pattern_answers_continue_the_generated_rule():
    challenge = engine.generate_challenge(
        ChallengeTypeEnum.PATTERN_RECOGNITION, DifficultyEnum.EASY, seed=4
    )
    shown = challenge.metadata["sequence"]
    step = shown[1] - shown[0]

    assert int(challenge.correct_answer) == shown[-1] + step


def test_riddle_and_quiz_come_from_the_static_bank():
    riddle = engine.generate_challenge(ChallengeTypeEnum.RIDDLE, DifficultyEnum.HARD, seed=5)
    quiz = engine.generate_challenge(ChallengeTypeEnum.QUICK_QUIZ, DifficultyEnum.HARD, seed=5)

    bank_answers = {entry["answer"] for entry in engine.CONTENT_BANK["riddles"]["HARD"]}
    quiz_answers = {entry["answer"] for entry in engine.CONTENT_BANK["quiz"]["HARD"]}

    assert riddle.correct_answer in bank_answers
    assert quiz.correct_answer in quiz_answers


# ==========================================
# Validation / normalization
# ==========================================

class _FakeAttempt:
    def __init__(self, answer_format, correct_answer, metadata=None):
        self.answer_format = answer_format
        self.correct_answer = correct_answer
        self.metadata_json = json.dumps(metadata) if metadata else None


@pytest.mark.parametrize("submitted", ["42", " 42 ", "42.0"])
def test_numeric_answers_accept_equivalent_forms(submitted):
    assert engine.is_answer_correct(_FakeAttempt("number", "42"), submitted)


@pytest.mark.parametrize("submitted", ["43", "", "forty-two", None])
def test_numeric_answers_reject_wrong_or_unparseable_input(submitted):
    assert not engine.is_answer_correct(_FakeAttempt("number", "42"), submitted)


@pytest.mark.parametrize("submitted", ["Clock", " clock ", "CLOCK!"])
def test_text_answers_ignore_case_punctuation_and_whitespace(submitted):
    assert engine.is_answer_correct(_FakeAttempt("text", "clock"), submitted)


def test_text_answers_accept_bank_alternates():
    attempt = _FakeAttempt("text", "echo", {"accepts": ["an echo"]})

    assert engine.is_answer_correct(attempt, "An Echo")
    assert not engine.is_answer_correct(attempt, "shadow")


@pytest.mark.parametrize("submitted", ["4-7-2", "472", "4 7 2", "4, 7, 2"])
def test_sequence_answers_ignore_separators(submitted):
    assert engine.is_answer_correct(_FakeAttempt("sequence", "4-7-2"), submitted)


def test_sequence_answers_require_the_right_order():
    assert not engine.is_answer_correct(_FakeAttempt("sequence", "4-7-2"), "2-7-4")


def test_mcq_answers_require_the_exact_option():
    attempt = _FakeAttempt("mcq", "Melatonin")

    assert engine.is_answer_correct(attempt, "melatonin")
    assert not engine.is_answer_correct(attempt, "Melatonin is the one")


# ==========================================
# Scoring
# ==========================================

@pytest.mark.parametrize(
    "difficulty,expected",
    [(DifficultyEnum.EASY, 10), (DifficultyEnum.MEDIUM, 20), (DifficultyEnum.HARD, 35)],
)
def test_base_score_per_difficulty(difficulty, expected):
    assert engine.calculate_score(difficulty, 80, 100, 1) == expected


def test_speed_bonus_applies_below_half_the_limit():
    assert engine.calculate_score(DifficultyEnum.MEDIUM, 40, 100, 1) == 30
    assert engine.calculate_score(DifficultyEnum.MEDIUM, 50, 100, 1) == 20


def test_retry_penalty_scales_with_extra_attempts():
    assert engine.calculate_score(DifficultyEnum.EASY, 80, 100, 2) == 8
    assert engine.calculate_score(DifficultyEnum.EASY, 80, 100, 3) == 6


def test_failed_attempts_score_zero():
    assert engine.calculate_score(DifficultyEnum.HARD, 10, 100, 1, is_correct=False) == 0


def test_scoring_is_deterministic():
    scores = {engine.calculate_score(DifficultyEnum.HARD, 30, 150, 1) for _ in range(20)}

    assert len(scores) == 1


def test_score_never_drops_below_one_for_a_correct_answer():
    assert engine.calculate_score(DifficultyEnum.EASY, 89, 90, 12) == 1


# ==========================================
# History statistics
# ==========================================

def test_accuracy_and_time_ratio_ignore_in_progress_attempts(make_user, make_attempt):
    user = make_user()
    make_attempt(user, status=ChallengeStatusEnum.COMPLETED, is_correct=True, time_taken_seconds=30)
    make_attempt(user, status=ChallengeStatusEnum.FAILED, is_correct=False, time_taken_seconds=90)
    make_attempt(
        user,
        status=ChallengeStatusEnum.IN_PROGRESS,
        is_correct=None,
        time_taken_seconds=None,
        completed_at=None,
    )

    attempts = [user.challenge_attempts[i] for i in range(3)]

    assert engine.accuracy(attempts) == 0.5
    assert engine.average_time_ratio(attempts) == pytest.approx((30 / 90 + 90 / 90) / 2)


def test_stats_helpers_return_none_without_resolved_history():
    assert engine.accuracy([]) is None
    assert engine.average_time_ratio([]) is None
    assert engine.consecutive_failures([]) == 0


def test_recent_attempts_is_newest_first_and_limited(db, make_user, make_attempt):
    user = make_user()
    for index in range(4):
        make_attempt(user, prompt_snapshot=f"q{index}")

    newest_two = engine.recent_attempts(user.id, db, limit=2)

    assert [a.prompt_snapshot for a in newest_two] == ["q3", "q2"]


def test_recent_attempts_can_filter_by_type(db, make_user, make_attempt):
    user = make_user()
    make_attempt(user, challenge_type=ChallengeTypeEnum.MATH)
    make_attempt(user, challenge_type=ChallengeTypeEnum.RIDDLE)

    of_type = engine.recent_attempts(user.id, db, challenge_type=ChallengeTypeEnum.RIDDLE)

    assert [a.challenge_type for a in of_type] == [ChallengeTypeEnum.RIDDLE]


def test_recent_attempts_excludes_other_users(db, make_user, make_attempt):
    mine, theirs = make_user(), make_user()
    make_attempt(mine)
    make_attempt(theirs)

    assert len(engine.recent_attempts(mine.id, db)) == 1


# ==========================================
# Difficulty adaptation
# ==========================================

def _history(make_attempt, user, results, **overrides):
    """Create attempts oldest-first, then hand back newest-first history."""
    attempts = []
    for correct in results:
        attempts.append(
            make_attempt(
                user,
                status=ChallengeStatusEnum.COMPLETED if correct else ChallengeStatusEnum.FAILED,
                is_correct=correct,
                **overrides,
            )
        )
    return list(reversed(attempts))


def test_difficulty_is_stable_on_a_cold_start():
    assert engine.evaluate_difficulty(DifficultyEnum.MEDIUM, []) == DifficultyEnum.MEDIUM


def test_difficulty_is_stable_with_insufficient_history(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [True, True, True], time_taken_seconds=5)

    assert engine.evaluate_difficulty(DifficultyEnum.EASY, history) == DifficultyEnum.EASY


def test_fast_and_accurate_history_promotes_difficulty(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [True] * 5, time_taken_seconds=20)

    assert engine.evaluate_difficulty(DifficultyEnum.EASY, history) == DifficultyEnum.MEDIUM
    assert engine.evaluate_difficulty(DifficultyEnum.MEDIUM, history) == DifficultyEnum.HARD


def test_promotion_stops_at_hard(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [True] * 5, time_taken_seconds=20)

    assert engine.evaluate_difficulty(DifficultyEnum.HARD, history) == DifficultyEnum.HARD


def test_correct_but_slow_history_does_not_promote(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [True] * 5, time_taken_seconds=80)

    assert engine.evaluate_difficulty(DifficultyEnum.EASY, history) == DifficultyEnum.EASY


def test_low_accuracy_demotes_difficulty(make_user, make_attempt):
    user = make_user()
    history = _history(
        make_attempt, user, [False, True, False, False, False], time_taken_seconds=80
    )

    assert engine.evaluate_difficulty(DifficultyEnum.HARD, history) == DifficultyEnum.MEDIUM


def test_low_accuracy_demotes_even_after_a_recent_win(make_user, make_attempt):
    user = make_user()
    history = _history(
        make_attempt, user, [False, False, False, False, True], time_taken_seconds=80
    )

    assert engine.consecutive_failures(history) == 0
    assert engine.evaluate_difficulty(DifficultyEnum.MEDIUM, history) == DifficultyEnum.EASY


def test_two_consecutive_failures_demote_immediately(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [True, False, False], time_taken_seconds=30)

    assert engine.evaluate_difficulty(DifficultyEnum.HARD, history) == DifficultyEnum.MEDIUM


def test_demotion_stops_at_easy(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [False, False], time_taken_seconds=30)

    assert engine.evaluate_difficulty(DifficultyEnum.EASY, history) == DifficultyEnum.EASY


def test_mixed_history_keeps_difficulty_stable(make_user, make_attempt):
    user = make_user()
    history = _history(
        make_attempt, user, [True, False, True, False, True], time_taken_seconds=70
    )

    assert engine.evaluate_difficulty(DifficultyEnum.MEDIUM, history) == DifficultyEnum.MEDIUM


def test_consecutive_failures_counts_only_the_newest_run(make_user, make_attempt):
    user = make_user()
    history = _history(make_attempt, user, [False, True, False, False])

    assert engine.consecutive_failures(history) == 2


# ==========================================
# Type selection
# ==========================================

def test_cold_start_selection_returns_a_valid_pair(db, make_user):
    user = make_user()

    challenge_type, difficulty = engine.select_next_challenge(user, db)

    assert challenge_type in ALL_TYPES
    assert difficulty == DifficultyEnum.EASY


def test_selection_avoids_repeating_the_last_type(db, make_user, make_attempt):
    user = make_user()
    make_attempt(user, challenge_type=ChallengeTypeEnum.MATH)

    for seed in range(20):
        challenge_type, _ = engine.select_next_challenge(user, db, rng=random.Random(seed))
        assert challenge_type != ChallengeTypeEnum.MATH


def test_selection_avoids_types_with_two_consecutive_failures(db, make_user, make_attempt):
    user = make_user()
    for _ in range(2):
        make_attempt(
            user,
            challenge_type=ChallengeTypeEnum.RIDDLE,
            status=ChallengeStatusEnum.FAILED,
            is_correct=False,
        )
    make_attempt(user, challenge_type=ChallengeTypeEnum.MATH)

    for seed in range(20):
        challenge_type, _ = engine.select_next_challenge(user, db, rng=random.Random(seed))
        assert challenge_type not in {ChallengeTypeEnum.RIDDLE, ChallengeTypeEnum.MATH}


def test_selection_recovers_a_type_after_a_success(db, make_user, make_attempt):
    user = make_user()
    for _ in range(2):
        make_attempt(
            user,
            challenge_type=ChallengeTypeEnum.RIDDLE,
            status=ChallengeStatusEnum.FAILED,
            is_correct=False,
        )
    make_attempt(user, challenge_type=ChallengeTypeEnum.RIDDLE)

    attempts = engine.recent_attempts(user.id, db)

    assert ChallengeTypeEnum.RIDDLE not in engine._types_to_avoid(attempts)


def test_selection_falls_back_when_every_type_is_avoided(db, make_user, make_attempt):
    user = make_user()
    for challenge_type in ALL_TYPES:
        for _ in range(2):
            make_attempt(
                user,
                challenge_type=challenge_type,
                status=ChallengeStatusEnum.FAILED,
                is_correct=False,
            )

    attempts = engine.recent_attempts(user.id, db, limit=len(ALL_TYPES) * 2)
    assert engine._types_to_avoid(attempts) == set(ALL_TYPES)

    assert engine.select_challenge_type(attempts, rng=random.Random(0)) in ALL_TYPES


def test_selection_never_repeats_a_type_three_times_in_a_row(db, make_user, make_attempt):
    """Rotation is enforced per pick, so a third repeat is impossible."""
    user = make_user()
    picks = []
    for seed in range(3):
        challenge_type, _ = engine.select_next_challenge(user, db, rng=random.Random(seed))
        picks.append(challenge_type)
        make_attempt(user, challenge_type=challenge_type)

    assert len(set(picks[-2:])) == 2


# ==========================================
# Difficulty resolution & fallback
# ==========================================

def test_alarm_difficulty_overrides_the_user_level(db, make_user, make_alarm):
    user = make_user()
    user.current_difficulty = DifficultyEnum.EASY
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.HARD)

    _, difficulty = engine.select_next_challenge(user, db, alarm)

    assert difficulty == DifficultyEnum.HARD


def test_easy_alarm_defers_to_the_adaptive_user_level(db, make_user, make_alarm):
    user = make_user()
    user.current_difficulty = DifficultyEnum.MEDIUM
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.EASY)

    _, difficulty = engine.select_next_challenge(user, db, alarm)

    assert difficulty == DifficultyEnum.MEDIUM


def test_repeated_failures_force_easy_even_on_a_pinned_alarm(
    db, make_user, make_alarm, make_attempt
):
    user = make_user()
    alarm = make_alarm(user, difficulty_level=DifficultyEnum.HARD)
    for _ in range(engine.FALLBACK_AFTER_CONSECUTIVE_FAILURES):
        make_attempt(user, status=ChallengeStatusEnum.FAILED, is_correct=False)

    _, difficulty = engine.select_next_challenge(user, db, alarm)

    assert difficulty == DifficultyEnum.EASY
