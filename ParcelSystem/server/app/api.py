# server/app/api.py
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel
from .db import SessionLocal, init_db
from .models import Parcel, DailyCounter, AuditLog
from .utils import next_queue_number_atomic, format_queue
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_
import io, csv
from datetime import datetime, date
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    PANDAS_AVAILABLE = False

import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="ParcelServer API")

# --- resolve project and static directories ---
# file is server/app/api.py -> parents[2] => project root (ParcelSystem)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLIENT_STATIC = PROJECT_ROOT / "client" / "static"
SERVER_STATIC = PROJECT_ROOT / "server" / "static"

# Mount client static at /static (client UI)
if CLIENT_STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(CLIENT_STATIC)), name="static")

# Also mount server static under /admin_static for admin assets (optional)
if SERVER_STATIC.exists():
    app.mount("/admin_static", StaticFiles(directory=str(SERVER_STATIC)), name="admin_static")


@app.get("/client")
def client_ui():
    client_file = CLIENT_STATIC / "client.html"
    if client_file.exists():
        return FileResponse(str(client_file))
    raise HTTPException(status_code=404, detail=f"client.html not found at {client_file}")


@app.get("/admin")
def admin_ui():
    # Prefer server/static/admin.html, fallback to client/static/admin.html
    server_admin = SERVER_STATIC / "admin.html"
    if server_admin.exists():
        return FileResponse(str(server_admin))
    client_admin = CLIENT_STATIC / "admin.html"
    if client_admin.exists():
        return FileResponse(str(client_admin))
    raise HTTPException(status_code=404, detail=f"admin.html not found (checked {server_admin} and {client_admin})")


# Startup: init DB
@app.on_event("startup")
def on_startup():
    init_db()

# Pydantic input model
class ParcelIn(BaseModel):
    tracking_number: str
    carrier: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_phone: Optional[str] = None
    provisional: bool = False   # if true -> create as PENDING (preview/reservation)

# ---------------------------
# Create parcel (check-in / provisional)
# ---------------------------
@app.post("/api/parcels")
def create_parcel(p: ParcelIn):
    db = SessionLocal()
    try:
        if not p.tracking_number:
            raise HTTPException(status_code=400, detail="missing tracking_number")

        carrier = (p.carrier or "NUD").upper()

        # Quick duplicate check
        existing = db.query(Parcel).filter(Parcel.tracking_number == p.tracking_number).first()
        if existing:
            # Already exists in DB
            raise HTTPException(status_code=409, detail="tracking_number already exists")

        # Generate queue atomically (counter separated by carrier)
        try:
            # prefix kept as 'NUD' per requirement; change to prefix=carrier if desired
            queue = next_queue_number_atomic(prefix='NUD', carrier=carrier)
        except Exception as e:
            # fail early
            raise HTTPException(status_code=500, detail=f"counter error: {e}")

        status = "PENDING" if p.provisional else "RECEIVED"

        parcel = Parcel(
            tracking_number=p.tracking_number,
            carrier=carrier,
            queue_number=queue,
            recipient_name=p.recipient_name,
            recipient_phone=p.recipient_phone,
            status=status
        )
        db.add(parcel)
        try:
            db.commit()
            db.refresh(parcel)
        except IntegrityError:
            db.rollback()
            # Unique constraint prevented duplicate from race
            raise HTTPException(status_code=409, detail="tracking_number already exists (race)")

        # Audit log (best-effort)
        try:
            al = AuditLog(entity="parcel", entity_id=parcel.id, action="create",
                          user="client", details=f"tracking={p.tracking_number}, provisional={p.provisional}")
            db.add(al)
            db.commit()
        except Exception:
            db.rollback()  # don't fail creation if audit fails

        return {"id": parcel.id, "queue_number": parcel.queue_number, "status": parcel.status}
    finally:
        db.close()

# ---------------------------
# Confirm pending -> RECEIVED
# ---------------------------
@app.post("/api/parcels/{tracking}/confirm_pending")
def confirm_pending(tracking: str):
    db = SessionLocal()
    try:
        p = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()
        if not p:
            raise HTTPException(status_code=404, detail="parcel not found")
        if p.status != "PENDING":
            return {"ok": False, "message": "parcel not pending"}
        p.status = "RECEIVED"
        db.add(p)
        db.commit()

        # audit
        try:
            al = AuditLog(entity="parcel", entity_id=p.id, action="confirm_pending", user="server_ui",
                          details=f"confirmed pending by ui")
            db.add(al)
            db.commit()
        except Exception:
            db.rollback()

        return {"ok": True, "tracking": p.tracking_number, "queue": p.queue_number}
    finally:
        db.close()

# ---------------------------
# Get single parcel
# ---------------------------
@app.get("/api/parcels/{tracking}")
def get_parcel(tracking: str):
    db = SessionLocal()
    try:
        p = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()
        if not p:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "id": p.id,
            "tracking_number": p.tracking_number,
            "queue_number": p.queue_number,
            "status": p.status,
            "recipient_name": p.recipient_name,
            "recipient_phone": p.recipient_phone,
            "created_at": p.created_at.isoformat() if p.created_at else None
        }
    finally:
        db.close()

# ---------------------------
# Pickup (confirm) endpoint (simple)
# ---------------------------
@app.post("/api/parcels/{tracking}/pickup")
def pickup_parcel(tracking: str):
    db = SessionLocal()
    try:
        p = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()
        if not p:
            raise HTTPException(status_code=404, detail="not found")
        if p.status == "PICKED_UP":
            return {"ok": True, "message": "already picked"}
        p.status = "PICKED_UP"
        db.add(p)
        db.commit()

        # audit
        try:
            al = AuditLog(entity="parcel", entity_id=p.id, action="pickup", user="server_ui",
                          details=f"pickup confirmed")
            db.add(al)
            db.commit()
        except Exception:
            db.rollback()

        return {"ok": True}
    finally:
        db.close()

# ---------------------------
# List recent parcels
# ---------------------------
@app.get("/api/parcels")
def list_parcels(limit: int = 200):
    db = SessionLocal()
    try:
        rows = db.query(Parcel).order_by(Parcel.created_at.desc()).limit(limit).all()
        out = []
        for p in rows:
            out.append({
                "id": p.id,
                "tracking_number": p.tracking_number,
                "queue_number": p.queue_number,
                "status": p.status,
                "recipient_name": p.recipient_name,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })
        return out
    finally:
        db.close()

# ---------------------------
# Search parcels (tracking or queue)
# ---------------------------
@app.get("/api/parcels/search")
def search_parcels(q: str = Query(..., min_length=1), limit: int = 200):
    db = SessionLocal()
    try:
        pattern = f"%{q}%"
        results = (db.query(Parcel)
                   .filter(or_(Parcel.tracking_number.like(pattern), Parcel.queue_number.like(pattern)))
                   .order_by(Parcel.created_at.desc())
                   .limit(limit)
                   .all())
        items = []
        for p in results:
            items.append({
                "id": p.id,
                "tracking": p.tracking_number,
                "queue": p.queue_number,
                "recipient": p.recipient_name,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })
        return {"count": len(items), "items": items}
    finally:
        db.close()

# ---------------------------
# Two-step checkout endpoints for UI double-scan
# ---------------------------
@app.post("/api/parcels/{tracking}/verify")
def verify_parcel(tracking: str):
    db = SessionLocal()
    try:
        p = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()
        if not p:
            raise HTTPException(status_code=404, detail="parcel not found")
        return {
            "tracking": p.tracking_number,
            "queue_number": p.queue_number,
            "recipient_name": p.recipient_name,
            "status": p.status
        }
    finally:
        db.close()

@app.post("/api/parcels/{tracking}/confirm_pickup")
def confirm_pickup(tracking: str, scanner_id: Optional[str] = None):
    db = SessionLocal()
    try:
        p = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()
        if not p:
            raise HTTPException(status_code=404, detail="parcel not found")
        if p.status == "PICKED_UP":
            return {"ok": False, "message": "already picked"}
        p.status = "PICKED_UP"
        db.add(p)
        db.commit()
        # audit
        try:
            al = AuditLog(entity="parcel", entity_id=p.id, action="pickup_confirm", user=scanner_id or "server_ui",
                          details=f"confirmed by {scanner_id or 'server_ui'}")
            db.add(al)
            db.commit()
        except Exception:
            db.rollback()
        return {"ok": True}
    finally:
        db.close()

# ---------------------------
# Reports: dates (for dropdown), summary, timeseries, export
# ---------------------------
@app.get("/api/reports/dates")
def get_available_periods(period: str = Query("daily", regex="^(daily|monthly|yearly)$")):
    db = SessionLocal()
    try:
        rows = db.query(Parcel).order_by(Parcel.created_at).all()
        counts = {}
        for p in rows:
            dt = p.created_at
            if not dt:
                continue
            if period == "daily":
                key = dt.strftime("%Y%m%d")
            elif period == "monthly":
                key = dt.strftime("%Y%m")
            else:
                key = dt.strftime("%Y")
            counts[key] = counts.get(key, 0) + 1
        out = [{"period": k, "count": counts[k]} for k in sorted(counts.keys(), reverse=True)]
        return out
    finally:
        db.close()

@app.get("/api/reports/summary")
def report_summary(period: str = Query("daily", regex="^(daily|monthly|yearly)$"), date: Optional[str] = None):
    db = SessionLocal()
    try:
        rows = db.query(Parcel).order_by(Parcel.created_at.desc()).all()
        checkin = 0
        checkout = 0
        items = []
        for p in rows:
            dt = p.created_at
            if date:
                if not dt:
                    continue
                if period == "daily":
                    key = dt.strftime("%Y%m%d")
                elif period == "monthly":
                    key = dt.strftime("%Y%m")
                else:
                    key = dt.strftime("%Y")
                if key != date:
                    continue
            checkin += 1
            if p.status == "PICKED_UP":
                checkout += 1
            items.append({
                "id": p.id,
                "tracking": p.tracking_number,
                "queue": p.queue_number,
                "status": p.status,
                "recipient": p.recipient_name,
                "created_at": dt.isoformat() if dt else None
            })
        remaining = checkin - checkout
        return {"period": period, "date": date, "checkin": checkin, "checkout": checkout, "remaining": remaining, "items": items[:200]}
    finally:
        db.close()

@app.get("/api/reports/timeseries")
def reports_timeseries(period: str = Query("daily", regex="^(daily|monthly|yearly)$"),
                       start: Optional[str] = None, end: Optional[str] = None, limit: int = 365):
    db = SessionLocal()
    try:
        rows = db.query(Parcel).order_by(Parcel.created_at).all()
        agg: dict[str, dict[str, int]] = {}
        for p in rows:
            dt = p.created_at
            if not dt:
                continue
            if period == "daily":
                key = dt.strftime("%Y%m%d")
            elif period == "monthly":
                key = dt.strftime("%Y%m")
            else:
                key = dt.strftime("%Y")
            if start and key < start:
                continue
            if end and key > end:
                continue
            if key not in agg:
                agg[key] = {"checkin": 0, "checkout": 0}
            agg[key]["checkin"] += 1
            if p.status == "PICKED_UP":
                agg[key]["checkout"] += 1
        keys_sorted = sorted(agg.keys())
        if len(keys_sorted) > limit:
            keys_sorted = keys_sorted[-limit:]
        labels = []
        checkin = []
        checkout = []
        for k in keys_sorted:
            labels.append(k)
            checkin.append(agg[k]["checkin"])
            checkout.append(agg[k]["checkout"])
        return {"labels": labels, "checkin": checkin, "checkout": checkout}
    finally:
        db.close()

@app.get("/api/reports/export")
def export_report(period: str = "daily", date: Optional[str] = None, fmt: str = "csv"):
    db = SessionLocal()
    try:
        q = db.query(Parcel)
        rows = []
        for p in q.order_by(Parcel.created_at).all():
            rows.append({
                "id": p.id,
                "tracking_number": p.tracking_number,
                "queue_number": p.queue_number,
                "status": p.status,
                "recipient_name": p.recipient_name,
                "recipient_phone": p.recipient_phone,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })
    finally:
        db.close()

    if fmt == "csv" or not PANDAS_AVAILABLE:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=rows[0].keys() if rows else ["id", "tracking_number"])
        writer.writeheader()
        if rows:
            writer.writerows(rows)
        return Response(content=buffer.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="parcel_report_{period}_{date or "all"}.csv"'})
    else:
        df = pd.DataFrame(rows)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="parcels")
        buffer.seek(0)
        return Response(content=buffer.read(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="parcel_report_{period}_{date or "all"}.xlsx"'})
# EOF
