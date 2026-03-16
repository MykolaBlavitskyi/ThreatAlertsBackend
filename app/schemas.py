from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DeviceRegisterRequest(BaseModel):
    fcm_token: str
    name: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    fcm_token: str
    name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AlertCreateRequest(BaseModel):
    threat_type: str
    detected_at: datetime
    video_path: str


class AlertResponse(BaseModel):
    id: int
    threat_type: str
    detected_at: datetime
    video_path: str
    created_at: datetime

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    alerts: List[AlertResponse]

