# server/app/utils.py
from datetime import date
from .models import DailyCounter
from .db import SessionLocal
from sqlalchemy import and_
from .models import DailyCounter, RecycledQueue


def format_queue(prefix: str, seq: int, datestr: str) -> str:
    return f"{prefix}{seq:04d}-{datestr}"

def next_queue_number_atomic(prefix='NUD', today: date | None = None, carrier: str | None = None):
    if today is None:
        today = date.today()
    datestr = today.strftime("%Y%m%d")

    db = SessionLocal()
    try:
        with db.begin():

            # ✅ 1) ใช้คิวที่ถูกคืนก่อน
            recycled = (
                db.query(RecycledQueue)
                .filter(
                    RecycledQueue.date == datestr,
                    RecycledQueue.carrier == carrier
                )
                .order_by(RecycledQueue.queue_number.asc())
                .with_for_update()
                .first()
            )

            if recycled:
                queue = recycled.queue_number
                db.delete(recycled)
                return queue

            # ✅ 2) ถ้าไม่มี → ใช้ DailyCounter (ของเดิม)
            q = db.query(DailyCounter).filter(
                DailyCounter.date == datestr,
                DailyCounter.carrier == carrier
            )

            counter = q.with_for_update().one_or_none()

            if counter is None:
                counter = DailyCounter(
                    carrier=carrier,
                    date=datestr,
                    last_seq=1
                )
                db.add(counter)
                seq = 1
            else:
                counter.last_seq += 1
                seq = counter.last_seq

        return format_queue(prefix, seq, datestr)

    finally:
        db.close()
