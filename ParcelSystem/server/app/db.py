# server/app/db.py
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

BASE_DIR = os.getenv('PARCEL_BASE_DIR') or os.path.join(os.getenv('PROGRAMDATA') or '.', 'ParcelSystem')
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, 'parcel.db')
SQLITE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

def init_db():
    from .models import Parcel, DailyCounter, AuditLog
    Base.metadata.create_all(bind=engine)