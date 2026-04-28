"""
scheduler.py  –  eiot background schedule runner
────────────────────────────────────────────────────────────────
Polls the `schedules` table every 60 s and fires device/group
state changes at the right IST time.

Can be used in two ways:

  A) Embedded in Streamlit (app.py calls start_scheduler() once):
         import scheduler
         scheduler.start_scheduler()

  B) Standalone process (keeps running even if Streamlit restarts):
         python scheduler.py
"""

import time
import logging
import threading
import datetime

import utils   # your existing utils.py

log = logging.getLogger("eiot.scheduler")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
POLL_INTERVAL = 10   # seconds between polls


# ─── DB HELPERS ───────────────────────────────────────────────────────────────

def get_active_schedules() -> list[dict]:
    conn = cursor = None
    try:
        conn = utils.get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute(
            """
            SELECT id, created_by, target_type, target_id,
                   action, mode, run_at, run_date, weekday, last_fired
            FROM schedules
            WHERE active = 1
            """
        )
        return cursor.fetchall()
    except Exception as e:
        log.error("get_active_schedules error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def mark_fired(schedule_id: int, today: datetime.date, mode: str):
    conn = cursor = None
    try:
        conn = utils.get_connection()
        cursor = conn.cursor(buffered=True)
        
        if mode == 'once':
            # Delete one-time schedules after firing
            cursor.execute(
                "DELETE FROM schedules WHERE id = %s",
                (schedule_id,)
            )
            log.info("Deleted one-time schedule #%s after firing", schedule_id)
        else:
            # For recurring schedules, just update last_fired
            cursor.execute(
                "UPDATE schedules SET last_fired = %s WHERE id = %s",
                (today, schedule_id)
            )
        conn.commit()
    except Exception as e:
        log.error("mark_fired error: %s", e)
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── FIRE ACTION ──────────────────────────────────────────────────────────────

def fire(schedule: dict):
    action     = schedule["action"]          # 'on' or 'off'
    new_state  = 1 if action == "on" else 0
    ttype      = schedule["target_type"]     # 'device' or 'group'
    tid        = schedule["target_id"]
    owner      = schedule["created_by"]

    log.info("Firing schedule #%s: %s %s %s → %s",
             schedule["id"], ttype, tid, owner, action)

    try:
        if ttype == "device":
            success = utils.update_device_state(owner, tid, new_state)
            if success:
                log.info("Successfully updated device %s to state %s", tid, new_state)
            else:
                log.error("Failed to update device %s to state %s", tid, new_state)
        else:
            success = utils.update_group_state(owner, tid, bool(new_state))
            if success:
                log.info("Successfully updated group %s to state %s", tid, new_state)
            else:
                log.error("Failed to update group %s to state %s", tid, new_state)
    except Exception as e:
        log.error("Exception while firing schedule #%s: %s", schedule["id"], e)


# ─── SHOULD IT FIRE NOW? ──────────────────────────────────────────────────────

def should_fire(schedule: dict, now_ist: datetime.datetime) -> bool:
    today     = now_ist.date()
    now_time  = now_ist.time()

    # run_at comes back as timedelta from mysql-connector
    run_at_td = schedule["run_at"]
    if isinstance(run_at_td, datetime.timedelta):
        run_at = (datetime.datetime.min + run_at_td).time()
    else:
        run_at = run_at_td   # already a time object

    # Must be within the current minute window
    window_start = datetime.time(run_at.hour, run_at.minute, 0)
    window_end   = (
        datetime.datetime.combine(today, window_start)
        + datetime.timedelta(minutes=1)
    ).time()

    if not (window_start <= now_time < window_end):
        return False

    # Don't re-fire on same day
    if schedule["last_fired"] == today:
        return False

    mode = schedule["mode"]

    if mode == "once":
        return schedule["run_date"] == today

    if mode == "daily":
        return True

    if mode == "weekly":
        return schedule["weekday"] == today.weekday()

    return False


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

def _run():
    log.info("Scheduler started (poll every %d s)", POLL_INTERVAL)
    while True:
        try:
            now_ist   = datetime.datetime.now(IST)
            today_ist = now_ist.date()
            schedules = get_active_schedules()
            log.debug("Polled %d active schedules at %s IST",
                      len(schedules), now_ist.strftime("%H:%M:%S"))

            for s in schedules:
                if should_fire(s, now_ist):
                    fire(s)
                    mark_fired(s["id"], today_ist, s["mode"])

        except Exception as e:
            log.error("Scheduler loop error: %s", e)

        time.sleep(POLL_INTERVAL)


_scheduler_thread: threading.Thread | None = None


def start_scheduler():
    """Call once from app.py to embed the scheduler in Streamlit."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_thread = threading.Thread(
        target=_run, daemon=True, name="eiot-scheduler"
    )
    _scheduler_thread.start()
    log.info("Scheduler thread launched.")


# ─── STANDALONE ENTRY ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _run()   # blocking — run with: python scheduler.py