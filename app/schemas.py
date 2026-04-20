from datetime import datetime
from typing import List, Literal, Optional

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
    tenant_id: Optional[int] = None
    camera_id: Optional[int]
    threat_type: str
    detected_at: datetime
    video_path: str
    preview_image_path: Optional[str]
    status: Optional[str] = "new"
    created_at: Optional[datetime] = None

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


class CameraCreateRequest(BaseModel):
    name: str
    location: Optional[str] = None
    is_active: Optional[bool] = True


class CameraResponse(BaseModel):
    id: int
    tenant_id: Optional[int] = None
    name: str
    location: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CameraListResponse(BaseModel):
    cameras: List[CameraResponse]


class TenantAdminItem(BaseModel):
    id: int
    api_token: str
    active: bool
    paid_until: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TenantAdminListResponse(BaseModel):
    tenants: List[TenantAdminItem]


class ActivationCodeAdminItem(BaseModel):
    code: str
    expires_at: datetime
    used_at: Optional[datetime] = None
    tenant_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ActivationCodeAdminListResponse(BaseModel):
    activation_codes: List[ActivationCodeAdminItem]


class DeviceAdminItem(BaseModel):
    id: int
    tenant_id: Optional[int] = None
    fcm_token: str
    name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeviceAdminListResponse(BaseModel):
    devices: List[DeviceAdminItem]


class AlertAdminItem(BaseModel):
    id: int
    tenant_id: Optional[int] = None
    camera_id: Optional[int] = None
    threat_type: str
    detected_at: datetime
    video_path: str
    preview_image_path: Optional[str] = None
    status: Optional[str] = "new"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AlertAdminListResponse(BaseModel):
    alerts: List[AlertAdminItem]


class AlertStatusUpdateRequest(BaseModel):
    status: Literal["new", "acknowledged", "resolved"]


class TenantAdminUpdateRequest(BaseModel):
    active: Optional[bool] = None
    paid_until: Optional[datetime] = None


class ActivationCodeAdminUpdateRequest(BaseModel):
    expires_at: Optional[datetime] = None
    used_at: Optional[datetime] = None
    tenant_id: Optional[int] = None


class ActivationCodeDeleteRequest(BaseModel):
    code: str


class ActivationCodeCreateRequest(BaseModel):
    """Тіло POST /api/admin/activation-codes — створення коду активації."""

    expires_at: datetime
    code: Optional[str] = None
    tenant_id: Optional[int] = None


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None

