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

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ParcelServer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

class ConfirmPickupIn(BaseModel):
    recipient_name: Optional[str] = None
    scanner_id: Optional[str] = None

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
# parcel search (tracking or queue)
# ---------------------------
# --- resilient search endpoints: /api/parcels/search , /api/parcels/search/ , /api/parcels/find
from typing import Optional
from fastapi import Query
from sqlalchemy import or_, func

def _search_parcels_impl(q: str, limit: int = 200):
    db = SessionLocal()
    try:
        pattern = f"%{q}%"
        try:
            filt = or_(Parcel.tracking_number.ilike(pattern), Parcel.queue_number.ilike(pattern))
        except Exception:
            filt = or_(func.lower(Parcel.tracking_number).like(pattern.lower()),
                       func.lower(Parcel.queue_number).like(pattern.lower()))

        results = (
            db.query(Parcel)
            .filter(filt)
            .order_by(Parcel.created_at.desc())
            .limit(limit)
            .all()
        )

        items = []
        for p in results:
            items.append({
                "id": p.id,
                "tracking": p.tracking_number,
                "queue": p.queue_number,
                "status": p.status,
                "recipient": p.recipient_name,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })
        return {"count": len(items), "items": items}
    finally:
        db.close()

# main route (existing)
@app.get("/api/parcels/search", summary="Search Parcels")
def search_parcels(q: Optional[str] = Query(None, min_length=1), limit: int = 200):
    if not q:
        return {"count": 0, "items": []}
    return _search_parcels_impl(q, limit)

# trailing-slash alias
@app.get("/api/parcels/search/", include_in_schema=False)
def search_parcels_slash(q: Optional[str] = Query(None, min_length=1), limit: int = 200):
    if not q:
        return {"count": 0, "items": []}
    return _search_parcels_impl(q, limit)

# short alias "find" to be safe if client uses different URL
@app.get("/api/parcels/find", include_in_schema=False)
def search_parcels_find(q: Optional[str] = Query(None, min_length=1), limit: int = 200):
    if not q:
        return {"count": 0, "items": []}
    return _search_parcels_impl(q, limit)


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
def confirm_pickup(tracking: str, payload: ConfirmPickupIn):
    db = SessionLocal()
    try:
        p = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()
        if not p:
            raise HTTPException(status_code=404, detail="parcel not found")

        if p.status == "PICKED_UP":
            # already picked — but still allow updating recipient_name if provided?
            if payload.recipient_name and p.recipient_name != payload.recipient_name:
                p.recipient_name = payload.recipient_name
                db.add(p)
                db.commit()
            return {"ok": False, "message": "already picked"}

        # (optional) Verify that tracking matches the queue or other checks can go here

        # update recipient name if provided
        if payload.recipient_name:
            p.recipient_name = payload.recipient_name

        p.status = "PICKED_UP"
        db.add(p)
        db.commit()

        # audit
        try:
            al = AuditLog(entity="parcel", entity_id=p.id, action="pickup_confirm",
                          user=payload.scanner_id or "server_ui",
                          details=f"confirmed by {payload.scanner_id or 'server_ui'}; recipient={p.recipient_name}")
            db.add(al)
            db.commit()
        except Exception:
            db.rollback()

        return {"ok": True, "tracking": p.tracking_number, "queue": p.queue_number, "recipient": p.recipient_name}
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
    """
    Export report filtered by period/date into CSV or XLSX.
    - period: daily|monthly|yearly
    - date: for daily -> 'YYYYMMDD', monthly -> 'YYYYMM', yearly -> 'YYYY'
    - fmt: 'csv' or 'xlsx'
    The exported file will contain 3 summary rows at the top:
      Check-in: N
      Check-out: M
      Remaining: K
    then an empty line, then the table with columns:
      id, tracking_number, queue_number, status, recipient_name, recipient_phone, created_at
    """
    db = SessionLocal()
    try:
        # load and filter same as report_summary logic
        rows = db.query(Parcel).order_by(Parcel.created_at.desc()).all()

        items = []
        checkin = 0
        checkout = 0

        for p in rows:
            dt = p.created_at
            # if date filter provided, compute key and compare
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
                "tracking_number": p.tracking_number,
                "queue_number": p.queue_number,
                "status": p.status,
                "recipient_name": p.recipient_name,
                "recipient_phone": p.recipient_phone,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })

        remaining = checkin - checkout

    finally:
        db.close()

    # Prepare filename
    safe_date = date or "all"
    fname_base = f"parcel_report_{period}_{safe_date}"
    # CSV branch (or fallback if pandas not available)
    if fmt == "csv" or not PANDAS_AVAILABLE:
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        # write summary rows first
        writer.writerow(["Check-in", str(checkin)])
        writer.writerow(["Check-out", str(checkout)])
        writer.writerow(["Remaining", str(remaining)])
        writer.writerow([])  # blank line

        # write header + rows
        fieldnames = ["id", "tracking_number", "queue_number", "status", "recipient_name", "recipient_phone", "created_at"]
        writer.writerow(fieldnames)
        for r in items:
            writer.writerow([r.get(f) for f in fieldnames])

        content = buffer.getvalue()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.csv"'}
        )

    # XLSX branch using pandas -> openpyxl engine
    # We'll write the summary in the top rows and the dataframe starting at row 5 (index 4)
    df = pd.DataFrame(items)
    # Ensure all columns exist in DataFrame (in correct order)
    cols = ["id", "tracking_number", "queue_number", "status", "recipient_name",  "created_at"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # write dataframe starting at row index 4 (Excel row 5) so we have room for 3 summary rows + blank line
        df.to_excel(writer, index=False, sheet_name="parcels", startrow=4)

        # write summary on top-left of the same sheet
        ws = writer.sheets["parcels"]
        # Excel rows are 1-indexed
        ws.cell(row=1, column=1, value="Check-in")
        ws.cell(row=1, column=2, value=checkin)
        ws.cell(row=2, column=1, value="Check-out")
        ws.cell(row=2, column=2, value=checkout)
        ws.cell(row=3, column=1, value="Remaining")
        ws.cell(row=3, column=2, value=remaining)

        # optionally freeze panes so header is visible
        ws.freeze_panes = "A6"

    buffer.seek(0)
    return Response(
        content=buffer.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname_base}.xlsx"'}
    )


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
