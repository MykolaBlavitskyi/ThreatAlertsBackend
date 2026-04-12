import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_tenant, get_optional_tenant
from .database import Base, engine, get_db
from .models import ActivationCode, Alert, Camera, Device, Tenant
from .push import send_alert_push
from .schemas import (
    ActivateRequest,
    ActivateResponse,
    ActivationCodeAdminItem,
    ActivationCodeAdminListResponse,
    ActivationCodeAdminUpdateRequest,
    ActivationCodeCreateRequest,
    ActivationCodeDeleteRequest,
    AlertAdminListResponse,
    AlertCreateRequest,
    AlertListResponse,
    AlertResponse,
    CameraCreateRequest,
    CameraListResponse,
    CameraResponse,
    CameraUpdateRequest,
    DeviceAdminListResponse,
    DeviceRegisterRequest,
    DeviceResponse,
    TenantAdminItem,
    TenantAdminListResponse,
    TenantAdminUpdateRequest,
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


@router.patch("/cameras/{camera_id}", response_model=CameraResponse)
def update_camera(
    camera_id: int,
    payload: CameraUpdateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> CameraResponse:
    cam = db.query(Camera).filter(Camera.id == camera_id, Camera.tenant_id == tenant.id).first()
    if not cam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    if payload.name is not None:
        cam.name = payload.name.strip()
    if payload.location is not None:
        cam.location = payload.location
    if payload.is_active is not None:
        cam.is_active = payload.is_active
    db.commit()
    db.refresh(cam)
    return cam


@router.delete("/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    cam = db.query(Camera).filter(Camera.id == camera_id, Camera.tenant_id == tenant.id).first()
    if not cam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    db.delete(cam)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    # fcm_token унікальний глобально в БД — шукаємо лише по токену, інакше INSERT дублює ключ
    device = db.query(Device).filter(Device.fcm_token == payload.fcm_token).first()
    if device:
        device.tenant_id = tenant.id
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


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(
    alert_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    alert = db.query(Alert).filter(Alert.id == alert_id, Alert.tenant_id == tenant.id).first()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    db.delete(alert)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Admin (потрібен Authorization: Bearer <api_token>) ---


@router.get("/admin/tenants", response_model=TenantAdminListResponse)
def admin_list_tenants(
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> TenantAdminListResponse:
    rows = db.query(Tenant).order_by(Tenant.id.asc()).all()
    return TenantAdminListResponse(tenants=rows)


@router.patch("/admin/tenants/{tenant_id}", response_model=TenantAdminItem)
def admin_patch_tenant(
    tenant_id: int,
    payload: TenantAdminUpdateRequest,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> TenantAdminItem:
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if payload.active is not None:
        t.active = payload.active
    if payload.paid_until is not None:
        t.paid_until = payload.paid_until
    db.commit()
    db.refresh(t)
    return t


@router.delete("/admin/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_tenant(
    tenant_id: int,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    db.delete(t)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/activation-codes", response_model=ActivationCodeAdminListResponse)
def admin_list_activation_codes(
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> ActivationCodeAdminListResponse:
    rows = db.query(ActivationCode).order_by(ActivationCode.created_at.desc()).all()
    return ActivationCodeAdminListResponse(activation_codes=rows)


def _generate_unique_activation_code(db: Session) -> str:
    for _ in range(32):
        candidate = f"ACT-{secrets.token_hex(4).upper()}"
        if db.query(ActivationCode.code).filter(ActivationCode.code == candidate).first() is None:
            return candidate
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate unique activation code",
    )


@router.post(
    "/admin/activation-codes",
    response_model=ActivationCodeAdminItem,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/activation-codes",
    response_model=ActivationCodeAdminItem,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/activation_codes",
    response_model=ActivationCodeAdminItem,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_activation_code(
    payload: ActivationCodeCreateRequest,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> ActivationCodeAdminItem:
    tid = payload.tenant_id
    if tid == 0:
        tid = None
    if tid is not None:
        if not db.query(Tenant).filter(Tenant.id == tid).first():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid tenant_id",
            )

    if payload.code is not None:
        code_value = payload.code.strip()
        if not code_value:
            code_value = _generate_unique_activation_code(db)
    else:
        code_value = _generate_unique_activation_code(db)

    row = ActivationCode(
        code=code_value,
        expires_at=payload.expires_at,
        used_at=None,
        tenant_id=tid,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Activation code already exists",
        )
    db.refresh(row)
    return row


def _delete_activation_code(db: Session, raw_code: str) -> None:
    code_value = raw_code.strip()
    row = db.query(ActivationCode).filter(ActivationCode.code == code_value).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activation code not found")
    db.delete(row)
    db.commit()


@router.post(
    "/admin/activation-codes/delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_delete_activation_code_post(
    payload: ActivationCodeDeleteRequest,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    _delete_activation_code(db, payload.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/activation-codes/remove",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_remove_activation_code_post(
    payload: ActivationCodeDeleteRequest,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    _delete_activation_code(db, payload.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/activation-codes/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_revoke_activation_code_post(
    payload: ActivationCodeDeleteRequest,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    _delete_activation_code(db, payload.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/admin/activation-codes", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_activation_code_query(
    code: str = Query(..., description="Activation code to delete"),
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    _delete_activation_code(db, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/admin/activation-codes/{code}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_activation_code_path(
    code: str,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    _delete_activation_code(db, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/admin/activation-codes/{code}", response_model=ActivationCodeAdminItem)
def admin_patch_activation_code(
    code: str,
    payload: ActivationCodeAdminUpdateRequest,
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> ActivationCodeAdminItem:
    code_value = code.strip()
    row = db.query(ActivationCode).filter(ActivationCode.code == code_value).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activation code not found")
    if payload.expires_at is not None:
        row.expires_at = payload.expires_at
    if payload.used_at is not None:
        row.used_at = payload.used_at
    if payload.tenant_id is not None:
        row.tenant_id = payload.tenant_id
    db.commit()
    db.refresh(row)
    return row


def _list_all_devices(db: Session) -> DeviceAdminListResponse:
    rows = db.query(Device).order_by(Device.id.asc()).all()
    return DeviceAdminListResponse(devices=rows)


@router.get("/admin/devices", response_model=DeviceAdminListResponse)
def admin_list_devices(
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> DeviceAdminListResponse:
    return _list_all_devices(db)


@router.get("/devices", response_model=DeviceAdminListResponse)
def list_devices_alias(
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> DeviceAdminListResponse:
    """Той самий JSON, що /api/admin/devices — для fallback у фронті."""
    return _list_all_devices(db)


@router.delete("/admin/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_device(
    device_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device does not belong to this tenant",
        )
    db.delete(device)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/alerts", response_model=AlertAdminListResponse)
def admin_list_alerts(
    from_datetime: Optional[datetime] = None,
    to_datetime: Optional[datetime] = None,
    threat_type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    camera_id: Optional[int] = None,
    tenant_id: Optional[int] = Query(None, description="Filter by tenant (admin)"),
    _tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> AlertAdminListResponse:
    query = db.query(Alert)
    if tenant_id is not None:
        query = query.filter(Alert.tenant_id == tenant_id)
    if from_datetime:
        query = query.filter(Alert.detected_at >= from_datetime)
    if to_datetime:
        query = query.filter(Alert.detected_at <= to_datetime)
    if threat_type:
        query = query.filter(Alert.threat_type == threat_type)
    if status_filter:
        query = query.filter(Alert.status == status_filter)
    if camera_id is not None:
        query = query.filter(Alert.camera_id == camera_id)
    alerts = query.order_by(Alert.detected_at.desc()).all()
    return AlertAdminListResponse(alerts=alerts)

