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
    tenant_id: Optional[int] = None
    camera_id: Optional[int] = None
    threat_type: str
    detected_at: datetime
    video_path: str
    preview_image_path: Optional[str] = None
    status: Optional[str] = "new"


class AlertResponse(BaseModel):
    id: int
    camera_id: Optional[int]
    threat_type: str
    detected_at: datetime
    video_path: str
    preview_image_path: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    alerts: List[AlertResponse]


class ActivateRequest(BaseModel):
    code: str


class ActivateResponse(BaseModel):
    api_token: str
    active: bool
    paid_until: Optional[datetime] = None

