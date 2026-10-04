"""Scheduled scans while the app runs: daily or weekly at a set time. A time missed while the computer was off is
caught up once, when the app starts again. For scans while the app is closed, the OS task scheduler can run
'python -m part_audit rescan' (see README)."""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Callable

DEFAULT_SCHEDULE = {"enabled": False, "frequency": "weekly", "weekday": 0, "time": "06:00", "since": ""}
DAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]      # weekday 0 = Sunday (the Israeli week)


def _hhmm(s: str) -> tuple[int, int]:
    try:
        h, m = (int(x) for x in str(s or "06:00").split(":")[:2])
        return min(max(h, 0), 23), min(max(m, 0), 59)
    except ValueError:
        return 6, 0


def last_slot(sched: dict, now: dt.datetime) -> dt.datetime:
    """The latest scheduled time that is not after now."""
    h, m = _hhmm(sched.get("time"))
    today = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if sched.get("frequency") == "daily":
        return today if today <= now else today - dt.timedelta(days=1)
    want = int(sched.get("weekday") or 0) % 7                    # 0 = Sunday
    have = (now.weekday() + 1) % 7                               # Python: Monday = 0
    slot = today - dt.timedelta(days=(have - want) % 7)
    return slot if slot <= now else slot - dt.timedelta(days=7)


def next_slot(sched: dict, now: dt.datetime) -> dt.datetime:
    step = dt.timedelta(days=1 if sched.get("frequency") == "daily" else 7)
    return last_slot(sched, now) + step


def is_due(sched: dict, last_started: str | None, now: dt.datetime) -> bool:
    """A scan is due when a scheduled time has passed since the last scheduled scan (and since the schedule was set)."""
    if not sched.get("enabled"):
        return False
    slot = last_slot(sched, now)
    for mark in (last_started, sched.get("since")):
        if mark:
            try:
                if dt.datetime.fromisoformat(mark) >= slot:
                    return False
            except ValueError:
                pass
    return True


def describe(sched: dict, now: dt.datetime | None = None) -> str:
    """'כל יום ראשון בשעה 06:00' / 'כל יום בשעה 06:00'."""
    h, m = _hhmm(sched.get("time"))
    when = "כל יום" if sched.get("frequency") == "daily" else f"כל יום {DAYS_HE[int(sched.get('weekday') or 0) % 7]}"
    return f"{when} בשעה {h:02d}:{m:02d}"


class Scheduler:
    """Checks every ``every`` seconds whether a scheduled scan is due; ``start_scan()`` returns False when a scan
    is already running (it is tried again on the next check)."""

    def __init__(self, get_schedule: Callable[[], dict], get_last: Callable[[], str | None],
                 set_last: Callable[[str], None], start_scan: Callable[[], bool], every: float = 30.0):
        self.get_schedule, self.get_last, self.set_last, self.start_scan = get_schedule, get_last, set_last, start_scan
        self.every = every
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="scan-scheduler")

    def start(self) -> "Scheduler":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def tick(self, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now()
        if is_due(self.get_schedule(), self.get_last(), now) and self.start_scan():
            self.set_last(now.isoformat(timespec="seconds"))
            return True
        return False

    def _loop(self) -> None:
        time.sleep(min(self.every, 5.0))
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:          # a scheduler must never take the app down
                pass
            self._stop.wait(self.every)
