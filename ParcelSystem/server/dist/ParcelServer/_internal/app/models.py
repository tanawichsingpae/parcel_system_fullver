# server/app/models.py
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from .db import Base

class Parcel(Base):
    __tablename__ = 'parcels'
    id = Column(Integer, primary_key=True, index=True)
    tracking_number = Column(String, unique=True, index=True)
    carrier = Column(String, index=True)
    queue_number = Column(String, index=True)
    status = Column(String, default='RECEIVED')
    recipient_name = Column(String)
    recipient_phone = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DailyCounter(Base):
    __tablename__ = 'daily_counters'
    id = Column(Integer, primary_key=True)
    carrier = Column(String, index=True)
    date = Column(String, index=True)  # YYYYMMDD
    last_seq = Column(Integer, default=0)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    entity = Column(String)
    entity_id = Column(Integer)
    action = Column(String)
    user = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())