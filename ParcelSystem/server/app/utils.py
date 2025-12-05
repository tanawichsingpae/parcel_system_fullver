# server/app/utils.py
from datetime import date
from .models import DailyCounter
from .db import SessionLocal
from sqlalchemy import and_

def format_queue(prefix: str, seq: int, datestr: str) -> str:
    return f"{prefix}{seq:04d}-{datestr}"

def next_queue_number_atomic(prefix='NUD', today: date | None = None, carrier: str | None = None):
    """
    Create/commit its own DB session, atomically increment counter row and return queue.
    Using an internal session avoids transaction nesting issues on caller side.
    """
    if today is None:
        today = date.today()
    datestr = today.strftime("%Y%m%d")

    db = SessionLocal()
    try:
        # use transaction block on this new session
        with db.begin():
            q = db.query(DailyCounter).filter(and_(DailyCounter.date == datestr,
                                                   DailyCounter.carrier == carrier))
            try:
                counter = q.with_for_update(nowait=True).one_or_none()
            except Exception:
                # some dialects will ignore/raise with_for_update -> fallback gracefully
                counter = q.one_or_none()

            if counter is None:
                counter = DailyCounter(carrier=carrier, date=datestr, last_seq=1)
                db.add(counter)
                seq = 1
            else:
                counter.last_seq += 1
                seq = counter.last_seq
            # commit happens at context exit
        return format_queue(prefix, seq, datestr)
    finally:
        db.close()
