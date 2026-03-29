import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_tenant, get_optional_tenant
from .database import Base, engine, get_db
from .models import ActivationCode, Alert, Camera, Device, Tenant
from .push import send_alert_push
from .schemas import (
    ActivateRequest,
    ActivateResponse,
    ActivationCodeAdminListResponse,
    AlertCreateRequest,
    AlertListResponse,
    AlertResponse,
    CameraCreateRequest,
    CameraListResponse,
    CameraResponse,
    DeviceRegisterRequest,
    DeviceResponse,
    TenantAdminListResponse,
)


Base.metadata.create_all(bind=engine)

router = APIRouter()


@router.post("/cameras", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> CameraResponse:
    cam = Camera(
        tenant_id=tenant.id,
        name=payload.name.strip(),
        location=payload.location,
        is_active=True if payload.is_active is None else payload.is_active,
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


@router.get("/cameras", response_model=CameraListResponse)
def list_cameras(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> CameraListResponse:
    cameras = db.query(Camera).filter(Camera.tenant_id == tenant.id).order_by(Camera.id.asc()).all()
    return CameraListResponse(cameras=cameras)


@router.post("/activate", response_model=ActivateResponse)
def activate(payload: ActivateRequest, db: Session = Depends(get_db)) -> ActivateResponse:
    code_value = payload.code.strip()
    code = db.query(ActivationCode).filter(ActivationCode.code == code_value).first()
    if not code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
    now = datetime.now(timezone.utc)
    if code.expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code expired")

    # Якщо код вже використали — повертаємо той самий tenant api_token (щоб можна було "зайти знову")
    if code.used_at is not None:
        if code.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code already used")
        tenant = db.query(Tenant).filter(Tenant.id == code.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code already used")
        return ActivateResponse(api_token=tenant.api_token, active=tenant.active, paid_until=tenant.paid_until)

    token = secrets.token_urlsafe(32)
    tenant = Tenant(api_token=token, active=True, paid_until=None)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    code.used_at = now
    code.tenant_id = tenant.id
    db.commit()

    return ActivateResponse(api_token=tenant.api_token, active=True, paid_until=tenant.paid_until)


@router.post("/device/register", response_model=DeviceResponse)
def register_device(
    payload: DeviceRegisterRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = (
        db.query(Device)
        .filter(Device.fcm_token == payload.fcm_token, Device.tenant_id == tenant.id)
        .first()
    )
    if device:
        device.name = payload.name
    else:
        device = Device(tenant_id=tenant.id, fcm_token=payload.fcm_token, name=payload.name)
        db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/device/tokens", response_model=List[str])
def get_device_tokens(db: Session = Depends(get_db)) -> List[str]:
    devices = db.query(Device).all()
    return [d.fcm_token for d in devices]


@router.post("/alerts", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
def create_alert(
    payload: AlertCreateRequest,
    tenant: Optional[Tenant] = Depends(get_optional_tenant),
    db: Session = Depends(get_db),
) -> AlertResponse:
    tenant_id = tenant.id if tenant else getattr(payload, "tenant_id", None)
    if tenant_id is not None:
        exists = db.query(Tenant.id).filter(Tenant.id == tenant_id).first()
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tenant_id",
            )

    # Якщо задано camera_id — перевіряємо, що камера існує і належить цьому tenant (коли tenant_id відомий)
    if payload.camera_id is not None:
        cam = db.query(Camera).filter(Camera.id == payload.camera_id).first()
        if not cam:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid camera_id",
            )
        if tenant_id is not None and cam.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="camera_id does not belong to this tenant",
            )

    alert = Alert(
        # якщо є Bearer token — прив'язуємо до цього tenant
        tenant_id=tenant_id,
        camera_id=payload.camera_id,
        threat_type=payload.threat_type,
        detected_at=payload.detected_at,
        video_path=payload.video_path,
        preview_image_path=payload.preview_image_path,
        status=payload.status or "new",
    )
    db.add(alert)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid foreign key value",
        )
    db.refresh(alert)

    # Push only to devices of this tenant (if configured)
    if tenant_id is not None:
        tokens = [d.fcm_token for d in db.query(Device).filter(Device.tenant_id == tenant_id).all()]
        send_alert_push(
            tokens,
            alert_id=alert.id,
            threat_type=alert.threat_type,
            detected_at_iso=alert.detected_at.isoformat(),
        )
    return alert


@router.get("/alerts", response_model=AlertListResponse)
def list_alerts(
    from_datetime: Optional[datetime] = None,
    to_datetime: Optional[datetime] = None,
    threat_type: Optional[str] = None,
    status: Optional[str] = None,
    camera_id: Optional[int] = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> AlertListResponse:
    query = db.query(Alert).filter(Alert.tenant_id == tenant.id)

    if from_datetime:
        query = query.filter(Alert.detected_at >= from_datetime)
    if to_datetime:
        query = query.filter(Alert.detected_at <= to_datetime)
    if threat_type:
        query = query.filter(Alert.threat_type == threat_type)
    if status:
        query = query.filter(Alert.status == status)
    if camera_id is not None:
        # камера_id фільтрує тільки в межах tenant (бо query вже tenant-scoped)
        query = query.filter(Alert.camera_id == camera_id)

    alerts = query.order_by(Alert.detected_at.desc()).all()
    return AlertListResponse(alerts=alerts)


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> AlertResponse:
    alert = db.query(Alert).filter(Alert.id == alert_id, Alert.tenant_id == tenant.id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    return alert


@router.get("/alerts/{alert_id}/video")
def get_alert_video(
    alert_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    alert = db.query(Alert).filter(Alert.id == alert_id, Alert.tenant_id == tenant.id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    video_path = Path(alert.video_path)
    if not video_path.is_absolute():
        base_dir = Path(__file__).resolve().parents[1]
        video_path = base_dir / alert.video_path

    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found",
        )

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=video_path.name,
    )


@router.get("/admin/tenants", response_model=TenantAdminListResponse)
def admin_list_tenants(db: Session = Depends(get_db)) -> TenantAdminListResponse:
    rows = db.query(Tenant).order_by(Tenant.id.asc()).all()
    return TenantAdminListResponse(tenants=rows)


@router.get("/admin/activation-codes", response_model=ActivationCodeAdminListResponse)
def admin_list_activation_codes(db: Session = Depends(get_db)) -> ActivationCodeAdminListResponse:
    rows = db.query(ActivationCode).order_by(ActivationCode.created_at.desc()).all()
    return ActivationCodeAdminListResponse(activation_codes=rows)

