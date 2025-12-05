# server/app/models.py
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from .db import Base

# พาร्सเซลหลัก
class Parcel(Base):
    __tablename__ = "parcels"
    id = Column(Integer, primary_key=True)
    tracking_number = Column(String, unique=True, index=True, nullable=False)
    carrier = Column(String, index=True, nullable=True)
    queue_number = Column(String, index=True, nullable=True)
    status = Column(String, default="IN")
    recipient_name = Column(String, nullable=True)
    recipient_phone = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# ตัวนับรายวัน (DailyCounter) — ใช้เก็บเลขลำดับต่อวันแยกตาม carrier
class DailyCounter(Base):
    __tablename__ = "daily_counters"
    id = Column(Integer, primary_key=True, autoincrement=True)
    carrier = Column(String, index=True, nullable=True)
    date = Column(String, index=True, nullable=False)  # 'YYYYMMDD'
    last_seq = Column(Integer, nullable=False, default=0)

# บันทึก audit
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    entity = Column(String)
    entity_id = Column(Integer)
    action = Column(String)
    user = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
