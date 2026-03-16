from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from .database import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    fcm_token = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    threat_type = Column(String, index=True, nullable=False)
    detected_at = Column(DateTime, nullable=False)
    video_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

