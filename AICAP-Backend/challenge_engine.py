"""
Cognitive Challenge Engine — AICAP-Backend (Module 4)
=====================================================
Generation, personalized selection, validation and scoring for the
cognitive challenges a user must solve to dismiss a ringing alarm.

Design decisions (Module 4 Guide §7):

1. Difficulty is tracked **per user** in ``User.current_difficulty``.
   ``Alarm.difficulty_level`` acts as an explicit per-alarm override: an
   alarm left at the EASY default follows the adaptive per-user level,
   while deliberately choosing MEDIUM or HARD pins that alarm.

2. Fallback for a user who genuinely cannot solve anything: after
   ``FALLBACK_AFTER_CONSECUTIVE_FAILURES`` consecutive failed attempts on
   an alarm, the challenge is escalated back down to EASY and the alarm
   exposes a manual-dismiss path, so an alarm can always be silenced.

3. RIDDLE and QUICK_QUIZ content comes from a static seeded bank
   (``challenge_bank.json``) shipped with the repo — no admin CRUD.

4. Rolling window sizes and thresholds live in the constants below.

Generation is seedable (``random.Random(seed)``); the resolved prompt and
answer are persisted on the attempt row, so validating a submission never
regenerates — and therefore never re-randomizes — the problem.
"""

from __future__ import annotations

import ast
import json
import operator
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models import (
    Alarm,
    ChallengeAttempt,
    ChallengeStatusEnum,
    ChallengeTypeEnum,
    DifficultyEnum,
    User,
)

# ==========================================
# Tunable constants
# ==========================================

TIME_LIMIT_SECONDS = {
    DifficultyEnum.EASY: 90,
    DifficultyEnum.MEDIUM: 120,
    DifficultyEnum.HARD: 150,
}

# Memory challenges are recall-under-pressure, so they get a tighter clock.
MEMORY_TIME_LIMIT_SECONDS = {
    DifficultyEnum.EASY: 45,
    DifficultyEnum.MEDIUM: 60,
    DifficultyEnum.HARD: 75,
}

MEMORY_DISPLAY_SECONDS = {
    DifficultyEnum.EASY: 5,
    DifficultyEnum.MEDIUM: 7,
    DifficultyEnum.HARD: 10,
}

MEMORY_SEQUENCE_LENGTH = {
    DifficultyEnum.EASY: 3,
    DifficultyEnum.MEDIUM: 5,
    DifficultyEnum.HARD: 8,
}

MAX_ATTEMPTS = {
    DifficultyEnum.EASY: 3,
    DifficultyEnum.MEDIUM: 2,
    DifficultyEnum.HARD: 1,
}

BASE_SCORE = {
    DifficultyEnum.EASY: 10,
    DifficultyEnum.MEDIUM: 20,
    DifficultyEnum.HARD: 35,
}

SPEED_BONUS_RATIO = 0.5       # solve under 50% of the limit …
SPEED_BONUS_MULTIPLIER = 0.5  # … for a 50% bonus on the base score
RETRY_PENALTY_PER_ATTEMPT = 0.2

# Rolling-window controls (mirrors SMART_ADAPTIVE's stability gating)
HISTORY_WINDOW = 10           # attempts fetched for stats/selection
DECISION_WINDOW = 5           # attempts the difficulty rules look at
MIN_ATTEMPTS_BEFORE_ADJUST = 5
PROMOTE_ACCURACY = 0.8
PROMOTE_TIME_RATIO = 0.6
DEMOTE_ACCURACY = 0.4
CONSECUTIVE_FAILURES_TO_DEMOTE = 2
CONSECUTIVE_FAILURES_TO_AVOID_TYPE = 2
FALLBACK_AFTER_CONSECUTIVE_FAILURES = 3

DIFFICULTY_LADDER = [DifficultyEnum.EASY, DifficultyEnum.MEDIUM, DifficultyEnum.HARD]

_BANK_PATH = Path(__file__).with_name("challenge_bank.json")

with _BANK_PATH.open(encoding="utf-8") as _bank_file:
    CONTENT_BANK = json.load(_bank_file)


# ==========================================
# Normalized generator output
# ==========================================

@dataclass
class GeneratedChallenge:
    type: ChallengeTypeEnum
    difficulty: DifficultyEnum
    prompt: str
    correct_answer: str
    answer_format: str  # "text" | "number" | "mcq" | "sequence"
    time_limit_seconds: int
    options: Optional[list[str]] = None
    metadata: dict = field(default_factory=dict)

    @property
    def max_attempts(self) -> int:
        return MAX_ATTEMPTS[self.difficulty]


# ==========================================
# Arithmetic helpers
# ==========================================

_AST_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
}


def evaluate_arithmetic(expression: str) -> int:
    """Evaluate a generated integer arithmetic expression without `eval`."""
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _AST_OPERATORS:
            return _AST_OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError(f"unsupported expression element: {ast.dump(node)}")

    tree = ast.parse(expression.replace("×", "*").replace("−", "-"), mode="eval")
    return _eval(tree)


# ==========================================
# Generators (one per ChallengeTypeEnum)
# ==========================================

def _time_limit(challenge_type: ChallengeTypeEnum, difficulty: DifficultyEnum) -> int:
    if challenge_type == ChallengeTypeEnum.MEMORY:
        return MEMORY_TIME_LIMIT_SECONDS[difficulty]
    return TIME_LIMIT_SECONDS[difficulty]


def generate_math(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Arithmetic. Difficulty scales operand size and operation count."""
    if difficulty == DifficultyEnum.EASY:
        left, right = rng.randint(2, 20), rng.randint(2, 20)
        expression = f"{left} {rng.choice(['+', '−'])} {right}"
    elif difficulty == DifficultyEnum.MEDIUM:
        expression = (
            f"{rng.randint(6, 20)} × {rng.randint(6, 15)} "
            f"{rng.choice(['+', '−'])} {rng.randint(10, 60)}"
        )
    else:
        expression = (
            f"{rng.randint(11, 30)} × {rng.randint(4, 12)} "
            f"{rng.choice(['+', '−'])} ({rng.randint(20, 90)} − {rng.randint(5, 19)}) "
            f"+ {rng.randint(3, 12)} × {rng.randint(3, 9)}"
        )

    answer = evaluate_arithmetic(expression)
    return GeneratedChallenge(
        type=ChallengeTypeEnum.MATH,
        difficulty=difficulty,
        prompt=f"What is {expression}?",
        correct_answer=str(answer),
        answer_format="number",
        time_limit_seconds=_time_limit(ChallengeTypeEnum.MATH, difficulty),
        metadata={"expression": expression},
    )


def generate_logic_puzzle(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Transitive-ordering deduction. Difficulty scales the number of clues."""
    subject_count = {DifficultyEnum.EASY: 3, DifficultyEnum.MEDIUM: 5, DifficultyEnum.HARD: 7}[difficulty]
    subjects = rng.sample(CONTENT_BANK["logic_subjects"], subject_count)

    # subjects[0] is tallest by construction; clues are consecutive pairs,
    # shuffled so the chain has to be reassembled.
    clues = [f"{taller} is taller than {shorter}" for taller, shorter in zip(subjects, subjects[1:])]
    rng.shuffle(clues)

    clue_text = "\n".join(f"- {clue}." for clue in clues)
    options = sorted(subjects)

    return GeneratedChallenge(
        type=ChallengeTypeEnum.LOGIC_PUZZLE,
        difficulty=difficulty,
        prompt=f"Who is the tallest?\n{clue_text}",
        correct_answer=subjects[0],
        answer_format="mcq",
        options=options,
        time_limit_seconds=_time_limit(ChallengeTypeEnum.LOGIC_PUZZLE, difficulty),
        metadata={"order": subjects, "clues": clues},
    )


def generate_memory(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Recall a shown sequence. Difficulty scales length and display time."""
    length = MEMORY_SEQUENCE_LENGTH[difficulty]
    use_colors = difficulty != DifficultyEnum.EASY
    pool = CONTENT_BANK["memory_colors"] if use_colors else [str(d) for d in range(10)]
    sequence = [rng.choice(pool) for _ in range(length)]

    return GeneratedChallenge(
        type=ChallengeTypeEnum.MEMORY,
        difficulty=difficulty,
        prompt=(
            f"Memorize this sequence, then type it back in order "
            f"(you have {MEMORY_DISPLAY_SECONDS[difficulty]}s to look at it)."
        ),
        correct_answer="-".join(sequence),
        answer_format="sequence",
        time_limit_seconds=_time_limit(ChallengeTypeEnum.MEMORY, difficulty),
        metadata={
            "sequence": sequence,
            "display_seconds": MEMORY_DISPLAY_SECONDS[difficulty],
        },
    )


def generate_word_game(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Anagram. Difficulty scales word length and obscurity."""
    word = rng.choice(CONTENT_BANK["words"][difficulty.value])

    scrambled = word
    letters = list(word)
    for _ in range(20):
        rng.shuffle(letters)
        scrambled = "".join(letters)
        if scrambled != word:
            break

    return GeneratedChallenge(
        type=ChallengeTypeEnum.WORD_GAME,
        difficulty=difficulty,
        prompt=f"Unscramble this word: {scrambled.upper()}",
        correct_answer=word,
        answer_format="text",
        time_limit_seconds=_time_limit(ChallengeTypeEnum.WORD_GAME, difficulty),
        metadata={"scrambled": scrambled},
    )


def generate_pattern_recognition(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Complete a numeric sequence. Difficulty scales the rule's complexity."""
    if difficulty == DifficultyEnum.EASY:
        start, step = rng.randint(1, 9), rng.randint(2, 6)
        values = [start + step * i for i in range(5)]
        rule = f"arithmetic +{step}"
    elif difficulty == DifficultyEnum.MEDIUM:
        first, second = rng.randint(1, 5), rng.randint(2, 7)
        values = [first, second]
        for _ in range(4):
            values.append(values[-1] + values[-2])
        rule = "fibonacci-like"
    else:
        # Two interleaved arithmetic progressions — solvable, but only once
        # you notice every other term belongs to its own run.
        first, first_step = rng.randint(2, 9), rng.randint(3, 8)
        second, second_step = rng.randint(20, 40), rng.randint(2, 7)
        values = []
        for index in range(3):
            values.append(first + first_step * index)
            values.append(second + second_step * index)
        rule = f"interleaved +{first_step} / +{second_step}"

    shown, answer = values[:-1], values[-1]
    return GeneratedChallenge(
        type=ChallengeTypeEnum.PATTERN_RECOGNITION,
        difficulty=difficulty,
        prompt="What number comes next? " + ", ".join(str(v) for v in shown) + ", __",
        correct_answer=str(answer),
        answer_format="number",
        time_limit_seconds=_time_limit(ChallengeTypeEnum.PATTERN_RECOGNITION, difficulty),
        metadata={"sequence": shown, "rule": rule},
    )


def generate_riddle(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Text riddle drawn from the difficulty-tagged static bank."""
    entry = rng.choice(CONTENT_BANK["riddles"][difficulty.value])
    return GeneratedChallenge(
        type=ChallengeTypeEnum.RIDDLE,
        difficulty=difficulty,
        prompt=entry["prompt"],
        correct_answer=entry["answer"],
        answer_format="text",
        time_limit_seconds=_time_limit(ChallengeTypeEnum.RIDDLE, difficulty),
        metadata={"accepts": entry.get("accepts", [])},
    )


def generate_quick_quiz(difficulty: DifficultyEnum, rng: random.Random) -> GeneratedChallenge:
    """Multiple-choice trivia drawn from the difficulty-tagged static bank."""
    entry = rng.choice(CONTENT_BANK["quiz"][difficulty.value])
    options = list(entry["options"])
    rng.shuffle(options)

    return GeneratedChallenge(
        type=ChallengeTypeEnum.QUICK_QUIZ,
        difficulty=difficulty,
        prompt=entry["prompt"],
        correct_answer=entry["answer"],
        answer_format="mcq",
        options=options,
        time_limit_seconds=_time_limit(ChallengeTypeEnum.QUICK_QUIZ, difficulty),
    )


GENERATORS = {
    ChallengeTypeEnum.MATH: generate_math,
    ChallengeTypeEnum.LOGIC_PUZZLE: generate_logic_puzzle,
    ChallengeTypeEnum.MEMORY: generate_memory,
    ChallengeTypeEnum.WORD_GAME: generate_word_game,
    ChallengeTypeEnum.PATTERN_RECOGNITION: generate_pattern_recognition,
    ChallengeTypeEnum.RIDDLE: generate_riddle,
    ChallengeTypeEnum.QUICK_QUIZ: generate_quick_quiz,
}


def generate_challenge(
    challenge_type: ChallengeTypeEnum,
    difficulty: DifficultyEnum,
    seed: Optional[int] = None,
) -> GeneratedChallenge:
    """Dispatch to the generator for `challenge_type` at `difficulty`."""
    generator = GENERATORS.get(challenge_type)
    if generator is None:
        raise ValueError(f"unsupported challenge type: {challenge_type}")

    rng = random.Random(seed)
    generated = generator(difficulty, rng)
    generated.metadata["seed"] = seed
    return generated


# ==========================================
# Personalized selection
# ==========================================

def recent_attempts(
    user_id: int,
    db: Session,
    limit: int = HISTORY_WINDOW,
    challenge_type: Optional[ChallengeTypeEnum] = None,
) -> list[ChallengeAttempt]:
    """Most recent resolved-or-not attempts for a user, newest first."""
    query = db.query(ChallengeAttempt).filter(ChallengeAttempt.user_id == user_id)
    if challenge_type is not None:
        query = query.filter(ChallengeAttempt.challenge_type == challenge_type)
    return query.order_by(ChallengeAttempt.started_at.desc(), ChallengeAttempt.id.desc()).limit(limit).all()


def _resolved(attempts: list[ChallengeAttempt]) -> list[ChallengeAttempt]:
    return [a for a in attempts if a.status != ChallengeStatusEnum.IN_PROGRESS]


def accuracy(attempts: list[ChallengeAttempt]) -> Optional[float]:
    """Share of resolved attempts that were answered correctly."""
    resolved = _resolved(attempts)
    if not resolved:
        return None
    return sum(1 for a in resolved if a.is_correct) / len(resolved)


def average_time_ratio(attempts: list[ChallengeAttempt]) -> Optional[float]:
    """Mean solve time as a fraction of each attempt's own time limit."""
    ratios = [
        a.time_taken_seconds / a.time_limit_seconds
        for a in _resolved(attempts)
        if a.time_taken_seconds is not None and a.time_limit_seconds
    ]
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def consecutive_failures(attempts: list[ChallengeAttempt]) -> int:
    """Length of the newest unbroken run of failed attempts."""
    streak = 0
    for attempt in _resolved(attempts):
        if attempt.status == ChallengeStatusEnum.FAILED:
            streak += 1
        else:
            break
    return streak


def evaluate_difficulty(
    current: DifficultyEnum,
    attempts: list[ChallengeAttempt],
) -> DifficultyEnum:
    """
    Apply the rolling-window difficulty rules (Module 4 Guide §2.2).

    `attempts` is newest-first history for the user. Difficulty only moves
    once there is a full decision window of resolved attempts, so a single
    good or bad morning cannot make it oscillate.
    """
    window = _resolved(attempts)[:DECISION_WINDOW]
    index = DIFFICULTY_LADDER.index(current)

    if consecutive_failures(attempts) >= CONSECUTIVE_FAILURES_TO_DEMOTE:
        return DIFFICULTY_LADDER[max(0, index - 1)]

    if len(window) < MIN_ATTEMPTS_BEFORE_ADJUST:
        return current

    window_accuracy = accuracy(window)
    time_ratio = average_time_ratio(window)

    if (
        window_accuracy is not None
        and window_accuracy >= PROMOTE_ACCURACY
        and time_ratio is not None
        and time_ratio < PROMOTE_TIME_RATIO
    ):
        return DIFFICULTY_LADDER[min(len(DIFFICULTY_LADDER) - 1, index + 1)]

    if window_accuracy is not None and window_accuracy <= DEMOTE_ACCURACY:
        return DIFFICULTY_LADDER[max(0, index - 1)]

    return current


def _types_to_avoid(attempts: list[ChallengeAttempt]) -> set[ChallengeTypeEnum]:
    """Types whose newest resolved attempts are an unbroken run of failures."""
    avoid: set[ChallengeTypeEnum] = set()
    for challenge_type in ChallengeTypeEnum:
        of_type = [a for a in _resolved(attempts) if a.challenge_type == challenge_type]
        if len(of_type) < CONSECUTIVE_FAILURES_TO_AVOID_TYPE:
            continue
        newest = of_type[:CONSECUTIVE_FAILURES_TO_AVOID_TYPE]
        if all(a.status == ChallengeStatusEnum.FAILED for a in newest):
            avoid.add(challenge_type)
    return avoid


def select_challenge_type(
    attempts: list[ChallengeAttempt],
    rng: Optional[random.Random] = None,
) -> ChallengeTypeEnum:
    """Rotate types, skipping the last one used and any repeatedly failed one."""
    rng = rng or random.Random()
    candidates = set(ChallengeTypeEnum) - _types_to_avoid(attempts)

    if attempts:
        without_last = candidates - {attempts[0].challenge_type}
        if without_last:
            candidates = without_last

    if not candidates:
        candidates = set(ChallengeTypeEnum)

    return rng.choice(sorted(candidates, key=lambda t: t.value))


def resolve_difficulty(user: User, alarm: Optional[Alarm] = None) -> DifficultyEnum:
    """
    Difficulty for the next challenge.

    An alarm pinned to MEDIUM or HARD overrides the adaptive per-user
    level; the EASY default means "let AICAP adapt".
    """
    if alarm is not None and alarm.difficulty_level != DifficultyEnum.EASY:
        return alarm.difficulty_level
    return user.current_difficulty or DifficultyEnum.EASY


def select_next_challenge(
    user: User,
    db: Session,
    alarm: Optional[Alarm] = None,
    rng: Optional[random.Random] = None,
) -> tuple[ChallengeTypeEnum, DifficultyEnum]:
    """Pick the (type, difficulty) pair to present next. Cold-start safe."""
    attempts = recent_attempts(user.id, db)
    difficulty = resolve_difficulty(user, alarm)

    # A user stuck in a failure run gets dropped to EASY regardless of the
    # alarm's pinned difficulty, so the alarm stays solvable.
    if consecutive_failures(attempts) >= FALLBACK_AFTER_CONSECUTIVE_FAILURES:
        difficulty = DifficultyEnum.EASY

    return select_challenge_type(attempts, rng), difficulty


# ==========================================
# Validation
# ==========================================

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_answer(answer_format: str, value: str) -> str:
    """Normalize a submitted answer for comparison against the stored one."""
    text = str(value or "").strip().lower()
    if answer_format == "sequence":
        return _NON_ALNUM.sub("", text)
    return _NON_ALNUM.sub(" ", text).strip()


def is_answer_correct(attempt: ChallengeAttempt, submitted: str) -> bool:
    """Per-type answer comparison (numeric tolerance, alternates, exact MCQ)."""
    if attempt.answer_format == "number":
        try:
            return abs(float(submitted) - float(attempt.correct_answer)) < 1e-6
        except (TypeError, ValueError):
            return False

    normalized = normalize_answer(attempt.answer_format, submitted)
    accepted = {normalize_answer(attempt.answer_format, attempt.correct_answer)}

    metadata = json.loads(attempt.metadata_json) if attempt.metadata_json else {}
    for alternate in metadata.get("accepts", []):
        accepted.add(normalize_answer(attempt.answer_format, alternate))

    return normalized in accepted


# ==========================================
# Scoring
# ==========================================

def calculate_score(
    difficulty: DifficultyEnum,
    time_taken: Optional[int],
    time_limit: int,
    attempts_used: int,
    is_correct: bool = True,
) -> int:
    """Base score by difficulty, plus a speed bonus, minus a retry penalty."""
    if not is_correct:
        return 0

    base = BASE_SCORE[difficulty]
    score = float(base)

    if time_taken is not None and time_limit and time_taken < time_limit * SPEED_BONUS_RATIO:
        score += base * SPEED_BONUS_MULTIPLIER

    retries = max(0, attempts_used - 1)
    score *= max(0.0, 1 - RETRY_PENALTY_PER_ATTEMPT * retries)

    return max(1, int(round(score)))
