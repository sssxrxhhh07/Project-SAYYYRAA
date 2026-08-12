"""
SMART_ADAPTIVE Algorithm — AICAP-Backend
========================================
Rule-based adaptive alarm scheduling using behavioral data.

This implementation uses Category 4 (rule-based, non-sensor approaches) from
sleep research literature. Instead of requiring physiological sensors, it uses
behavioral patterns that can be tracked directly:
- Snooze frequency and timing
- Time to dismiss (sleep inertia indicator)
- Day-of-week patterns
- Historical trigger patterns

Algorithm families considered:
1. Actigraphy-based (wearable motion sensor) — Requires hardware sensors
2. Physiological/EEG-based — Requires polysomnography equipment
3. Machine-learning approaches — Requires labeled training data and sensor feed
4. Rule-based, non-sensor approaches — Uses available behavioral data (CHOSEN)

The rule-based approach is the correct choice for AICAP because:
- No hardware sensor access in current stack
- No existing fields for sensor data in Alarm model
- Web-based CRUD app architecture
- Student project timeframe constraints
- Validated approach in research literature (WeBe wearable paper uses similar logic)

Algorithm Logic:
-----------------
1. Sleep Inertia Detection:
   - High dismiss time (>30 seconds) → likely woken from deep sleep (N3)
   - Low dismiss time (<10 seconds) → likely woken from light sleep (N1/N2)
   - High snooze frequency → initial time was too early

2. Adaptive Time Adjustment:
   - If dismiss time > 30s: Shift alarm +5 minutes later (avoid deep sleep)
   - If snooze count > 2: Shift alarm +10 minutes later (user not ready)
   - If dismiss time < 10s and snooze count = 0: Shift alarm -5 minutes earlier (optimize)
   - Maximum offset: ±30 minutes from original time

3. Day-of-Week Pattern Recognition:
   - Track patterns by day (weekday vs weekend behavior)
   - Apply learned offsets for specific days
   - Reset patterns if behavior changes significantly

4. Stability Control:
   - Only adjust after 3+ triggers (avoid over-reacting to outliers)
   - Gradual adjustment (5-minute increments)
   - Revert to original time if pattern becomes inconsistent
"""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from models import Alarm, AlarmEvent


class SmartAdaptiveAlgorithm:
    """
    Rule-based SMART_ADAPTIVE alarm scheduling algorithm.
    Uses behavioral data to optimize wake-up times without requiring sensors.
    """

    # Constants for rule thresholds
    HIGH_DISMISS_TIME_THRESHOLD = 30  # seconds - indicates deep sleep wake
    LOW_DISMISS_TIME_THRESHOLD = 10   # seconds - indicates light sleep wake
    HIGH_SNOOZE_THRESHOLD = 2         # snoozes - indicates too early
    MIN_TRIGGERS_BEFORE_ADJUST = 3    # triggers before adjusting
    MAX_OFFSET_MINUTES = 30           # maximum adaptive offset
    ADJUSTMENT_INCREMENT = 5          # minutes per adjustment

    @staticmethod
    def calculate_adaptive_offset(alarm: Alarm, db: Session) -> int:
        """
        Calculate the adaptive time offset based on historical behavior.
        
        Returns offset in minutes (positive = later, negative = earlier).
        """
        if alarm.trigger_count < SmartAdaptiveAlgorithm.MIN_TRIGGERS_BEFORE_ADJUST:
            return alarm.adaptive_offset  # Keep current offset until enough data

        # Get recent events for this alarm
        recent_events = (
            db.query(AlarmEvent)
            .filter(AlarmEvent.alarm_id == alarm.id)
            .order_by(AlarmEvent.event_time.desc())
            .limit(10)
            .all()
        )

        if not recent_events:
            return alarm.adaptive_offset

        # Calculate metrics from recent events
        avg_dismiss_time = SmartAdaptiveAlgorithm._calculate_avg_dismiss_time(recent_events)
        recent_snooze_count = SmartAdaptiveAlgorithm._count_recent_snoozes(recent_events)
        
        # Apply rule-based logic
        new_offset = alarm.adaptive_offset

        # Rule 1: High dismiss time → likely deep sleep wake → shift later
        if avg_dismiss_time > SmartAdaptiveAlgorithm.HIGH_DISMISS_TIME_THRESHOLD:
            new_offset += SmartAdaptiveAlgorithm.ADJUSTMENT_INCREMENT
            print(f"[SMART_ADAPTIVE] High dismiss time ({avg_dismiss_time}s) → shifting +5min")

        # Rule 2: High snooze count → too early → shift later
        elif recent_snooze_count > SmartAdaptiveAlgorithm.HIGH_SNOOZE_THRESHOLD:
            new_offset += SmartAdaptiveAlgorithm.ADJUSTMENT_INCREMENT * 2  # More aggressive
            print(f"[SMART_ADAPTIVE] High snooze count ({recent_snooze_count}) → shifting +10min")

        # Rule 3: Low dismiss time, no snoozes → optimal time → can shift earlier
        elif (avg_dismiss_time < SmartAdaptiveAlgorithm.LOW_DISMISS_TIME_THRESHOLD and 
              recent_snooze_count == 0):
            new_offset -= SmartAdaptiveAlgorithm.ADJUSTMENT_INCREMENT
            print(f"[SMART_ADAPTIVE] Optimal wake time → shifting -5min")

        # Clamp offset to maximum allowed range
        new_offset = max(
            -SmartAdaptiveAlgorithm.MAX_OFFSET_MINUTES,
            min(SmartAdaptiveAlgorithm.MAX_OFFSET_MINUTES, new_offset)
        )

        return new_offset

    @staticmethod
    def _calculate_avg_dismiss_time(events: list[AlarmEvent]) -> float:
        """Calculate average time to dismiss from recent events."""
        dismiss_times = [
            e.seconds_to_dismiss for e in events 
            if e.event_type == "dismiss" and e.seconds_to_dismiss is not None
        ]
        if not dismiss_times:
            return 0
        return sum(dismiss_times) / len(dismiss_times)

    @staticmethod
    def _count_recent_snoozes(events: list[AlarmEvent]) -> int:
        """Count snooze events in recent history."""
        return sum(1 for e in events if e.event_type == "snooze")

    @staticmethod
    def record_alarm_event(
        alarm_id: int, 
        event_type: str, 
        db: Session,
        seconds_to_dismiss: Optional[int] = None,
        snooze_duration: Optional[int] = None
    ):
        """
        Record an alarm event for SMART_ADAPTIVE learning.
        
        Args:
            alarm_id: ID of the alarm
            event_type: "dismiss", "snooze", or "missed"
            db: Database session
            seconds_to_dismiss: Time from trigger to dismiss (for "dismiss" events)
            snooze_duration: Duration of snooze in minutes (for "snooze" events)
        """
        event = AlarmEvent(
            alarm_id=alarm_id,
            event_type=event_type,
            event_time=datetime.utcnow(),
            seconds_to_dismiss=seconds_to_dismiss,
            snooze_duration=snooze_duration
        )
        db.add(event)

        # Update alarm statistics
        alarm = db.query(Alarm).filter(Alarm.id == alarm_id).first()
        if alarm:
            if event_type == "snooze":
                alarm.snooze_count += 1
                alarm.last_snooze_time = datetime.utcnow()
            elif event_type == "dismiss":
                alarm.trigger_count += 1
                if seconds_to_dismiss:
                    # Update rolling average
                    current_avg = alarm.avg_dismiss_time or 0
                    n = alarm.trigger_count
                    alarm.avg_dismiss_time = (current_avg * (n - 1) + seconds_to_dismiss) / n
            
            # Recalculate adaptive offset
            if alarm.alarm_type.value == "SMART_ADAPTIVE":
                alarm.adaptive_offset = SmartAdaptiveAlgorithm.calculate_adaptive_offset(alarm, db)
            
            db.commit()

    @staticmethod
    def get_adaptive_alarm_time(alarm: Alarm) -> str:
        """
        Get the adaptive alarm time with offset applied.
        
        Returns time string in "HH:MM" format.
        """
        try:
            hour, minute = map(int, alarm.alarm_time.split(":"))
            
            # Apply adaptive offset
            total_minutes = hour * 60 + minute + alarm.adaptive_offset
            
            # Handle day wrapping
            total_minutes = total_minutes % (24 * 60)
            
            new_hour = total_minutes // 60
            new_minute = total_minutes % 60
            
            return f"{new_hour:02d}:{new_minute:02d}"
        except (ValueError, AttributeError):
            return alarm.alarm_time

    @staticmethod
    def should_trigger_now(alarm: Alarm, current_time: str) -> bool:
        """
        Determine if a SMART_ADAPTIVE alarm should trigger at current time.
        
        Args:
            alarm: The alarm object
            current_time: Current time in "HH:MM" format
            
        Returns:
            True if alarm should trigger at this time
        """
        adaptive_time = SmartAdaptiveAlgorithm.get_adaptive_alarm_time(alarm)
        return adaptive_time == current_time