"""
Background Scheduler Service — AICAP-Backend
============================================
Module 3 (Alarm Scheduling System) background service powered by APScheduler.
Schedules jobs for DAILY, WEEKDAY, WEEKEND, ONE_TIME, and SMART_ADAPTIVE alarms,
and invokes push notification / FCM hooks when alarms fire.
"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Alarm, AlarmTypeEnum
from smart_adaptive import SmartAdaptiveAlgorithm

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)

scheduler = BackgroundScheduler()


# ==========================================
# Notification & Job Hooks
# ==========================================

def send_push_notification(user_id: int, alarm_id: int, title: str):
    """
    Hook function for Firebase Cloud Messaging (FCM) or Web Push notifications.
    In production, this dispatches real FCM push payload to client devices.
    """
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info(
        f"[PUSH NOTIFICATION HOOK] Fired for User ID={user_id} | "
        f"Alarm ID={alarm_id} | Title='{title}' at {now_str}"
    )
    print(
        f"🔔 [ALARM TRIGGERED] User: {user_id} | Alarm #{alarm_id}: '{title}' at {now_str}"
    )


def trigger_alarm_job(alarm_id: int, title: str, user_id: int):
    """Callback function executed by APScheduler when an alarm triggers."""
    db: Session = SessionLocal()
    try:
        alarm = db.query(Alarm).filter(Alarm.id == alarm_id).first()
        if not alarm or not alarm.is_active:
            logger.info(f"Skipping trigger for inactive/deleted alarm #{alarm_id}")
            return

        # Execute push notification hook
        send_push_notification(user_id=user_id, alarm_id=alarm_id, title=title)

        # Deactivate ONE_TIME alarms after triggering
        if alarm.alarm_type == AlarmTypeEnum.ONE_TIME:
            alarm.is_active = False
            db.commit()
            logger.info(f"Deactivated ONE_TIME alarm #{alarm_id}")

    except Exception as err:
        logger.error(f"Error executing job for alarm #{alarm_id}: {err}")
    finally:
        db.close()


# ==========================================
# Scheduler Logic & Triggers
# ==========================================

def add_or_update_alarm_job(alarm: Alarm):
    """
    Configures or updates an APScheduler job for a given Alarm entity.
    """
    job_id = f"alarm_{alarm.id}"

    # Remove existing job if already scheduled
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not alarm.is_active:
        return

    try:
        # Parse HH:MM from alarm_time string
        hour, minute = map(int, alarm.alarm_time.split(":"))
    except ValueError:
        logger.error(f"Invalid alarm_time format for alarm #{alarm.id}: {alarm.alarm_time}")
        return

    trigger = None

    if alarm.alarm_type == AlarmTypeEnum.DAILY:
        trigger = CronTrigger(hour=hour, minute=minute)

    elif alarm.alarm_type == AlarmTypeEnum.WEEKDAY:
        # Monday - Friday
        trigger = CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute)

    elif alarm.alarm_type == AlarmTypeEnum.WEEKEND:
        # Saturday, Sunday
        trigger = CronTrigger(day_of_week="sat,sun", hour=hour, minute=minute)

    elif alarm.alarm_type == AlarmTypeEnum.ONE_TIME:
        # Run once at next matching time
        trigger = CronTrigger(hour=hour, minute=minute)

    elif alarm.alarm_type == AlarmTypeEnum.SMART_ADAPTIVE:
        # Smart adaptive alarm: use adaptive time offset
        adaptive_time = SmartAdaptiveAlgorithm.get_adaptive_alarm_time(alarm)
        adaptive_hour, adaptive_minute = map(int, adaptive_time.split(":"))
        trigger = CronTrigger(hour=adaptive_hour, minute=adaptive_minute)

    if trigger:
        scheduler.add_job(
            func=trigger_alarm_job,
            trigger=trigger,
            id=job_id,
            args=[alarm.id, alarm.title, alarm.user_id],
            replace_existing=True,
        )
        logger.info(f"Scheduled job '{job_id}' ({alarm.alarm_type}) for time {alarm.alarm_time}")


def remove_alarm_job(alarm_id: int):
    """Removes a scheduled job when an alarm is deleted or disabled."""
    job_id = f"alarm_{alarm_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Removed job '{job_id}'")


def sync_all_active_alarms(db: Optional[Session] = None):
    """Loads all active alarms from DB on application startup and registers them."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        active_alarms = db.query(Alarm).filter(Alarm.is_active == True).all()
        for alarm in active_alarms:
            add_or_update_alarm_job(alarm)
        logger.info(f"Synchronized {len(active_alarms)} active alarm jobs with scheduler.")
    finally:
        if close_db:
            db.close()


def start_scheduler():
    """Starts the APScheduler background daemon."""
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler background service started successfully.")
        sync_all_active_alarms()


def stop_scheduler():
    """Shuts down the APScheduler service gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler background service stopped.")
