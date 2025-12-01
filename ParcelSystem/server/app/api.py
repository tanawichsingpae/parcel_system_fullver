# server/app/api.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from .db import SessionLocal, init_db
from .models import Parcel, DailyCounter, AuditLog
from .utils import today_str
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

app = FastAPI()

class ParcelIn(BaseModel):
    tracking_number: str
    carrier: str = None
    recipient_name: str = None
    recipient_phone: str = None

@app.on_event('startup')
def startup():
    init_db()

@app.post('/api/parcels')
def create_parcel(p: ParcelIn):
    db = SessionLocal()
    try:
        # check duplicate tracking
        existing = db.query(Parcel).filter(Parcel.tracking_number==p.tracking_number).first()
        if existing:
            return {'id': existing.id, 'queue_number': existing.queue_number}

        # atomic sequence increment (simple UPSERT emulation)
        today = today_str()
        counter = db.query(DailyCounter).filter(DailyCounter.carrier==p.carrier, DailyCounter.date==today).first()
        if not counter:
            counter = DailyCounter(carrier=p.carrier, date=today, last_seq=0)
            db.add(counter)
            db.commit()
            db.refresh(counter)

        # increment
        # reload with lock-ish behaviour: re-query and update
        db.execute(update(DailyCounter).where(DailyCounter.id==counter.id).values(last_seq=DailyCounter.last_seq+1))
        db.commit()
        db.refresh(counter)
        # get fresh value
        new_counter = db.query(DailyCounter).filter(DailyCounter.id==counter.id).first()
        seq = new_counter.last_seq
        queue = f"{p.carrier}{seq:03d}-{today}"

        parcel = Parcel(tracking_number=p.tracking_number, carrier=p.carrier, queue_number=queue,
                        recipient_name=p.recipient_name, recipient_phone=p.recipient_phone)
        db.add(parcel)
        db.commit()
        db.refresh(parcel)

        # audit
        al = AuditLog(entity='parcel', entity_id=parcel.id, action='create', user='client', details=f"tracking={p.tracking_number}")
        db.add(al)
        db.commit()

        return {'id': parcel.id, 'queue_number': parcel.queue_number}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail='Integrity error')
    finally:
        db.close()

@app.get('/api/parcels/{tracking}')
def get_parcel(tracking: str):
    db = SessionLocal()
    p = db.query(Parcel).filter(Parcel.tracking_number==tracking).first()
    db.close()
    if not p:
        raise HTTPException(status_code=404, detail='not found')
    return {
        'id': p.id,
        'tracking_number': p.tracking_number,
        'queue_number': p.queue_number,
        'status': p.status,
        'recipient_name': p.recipient_name
    }

@app.post('/api/parcels/{tracking}/pickup')
def pickup_parcel(tracking: str):
    db = SessionLocal()
    p = db.query(Parcel).filter(Parcel.tracking_number==tracking).first()
    if not p:
        db.close()
        raise HTTPException(status_code=404)
    p.status = 'PICKED_UP'
    db.add(p)
    db.commit()
    db.close()
    return {'ok': True}

@app.get('/api/parcels')
def list_parcels(limit: int = 200):
    db = SessionLocal()
    try:
        q = db.query(Parcel).order_by(Parcel.created_at.desc()).limit(limit).all()
        return [
            {
                "id": p.id,
                "tracking_number": p.tracking_number,
                "queue_number": p.queue_number,
                "status": p.status,
                "recipient_name": p.recipient_name,
                "created_at": p.created_at.isoformat() if p.created_at else None
            } for p in q
        ]
    finally:
        db.close()
