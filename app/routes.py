from datetime import datetime
import secrets
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import ActivationCode, Alert, Device, Tenant
from .schemas import (
    ActivateRequest,
    ActivateResponse,
    AlertCreateRequest,
    AlertListResponse,
    AlertResponse,
    DeviceRegisterRequest,
    DeviceResponse,
)


Base.metadata.create_all(bind=engine)

router = APIRouter()


@router.post("/activate", response_model=ActivateResponse)
def activate(payload: ActivateRequest, db: Session = Depends(get_db)) -> ActivateResponse:
    code_value = payload.code.strip()
    code = db.query(ActivationCode).filter(ActivationCode.code == code_value).first()
    if not code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
    if code.used_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code already used")
    if code.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code expired")

    token = secrets.token_urlsafe(32)
    tenant = Tenant(api_token=token, active=1, paid_until=None)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    code.used_at = datetime.utcnow()
    code.tenant_id = tenant.id
    db.commit()

    return ActivateResponse(api_token=tenant.api_token, active=True, paid_until=tenant.paid_until)


@router.post("/device/register", response_model=DeviceResponse)
def register_device(
    payload: DeviceRegisterRequest,
    db: Session = Depends(get_db),
) -> DeviceResponse:
    device = db.query(Device).filter(Device.fcm_token == payload.fcm_token).first()
    if device:
        device.name = payload.name
    else:
        device = Device(fcm_token=payload.fcm_token, name=payload.name)
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
    db: Session = Depends(get_db),
) -> AlertResponse:
    alert = Alert(
        camera_id=payload.camera_id,
        threat_type=payload.threat_type,
        detected_at=payload.detected_at,
        video_path=payload.video_path,
        preview_image_path=payload.preview_image_path,
        status=payload.status or "new",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/alerts", response_model=AlertListResponse)
def list_alerts(
    from_datetime: Optional[datetime] = None,
    to_datetime: Optional[datetime] = None,
    threat_type: Optional[str] = None,
    status: Optional[str] = None,
    camera_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> AlertListResponse:
    query = db.query(Alert)

    if from_datetime:
        query = query.filter(Alert.detected_at >= from_datetime)
    if to_datetime:
        query = query.filter(Alert.detected_at <= to_datetime)
    if threat_type:
        query = query.filter(Alert.threat_type == threat_type)
    if status:
        query = query.filter(Alert.status == status)
    if camera_id is not None:
        query = query.filter(Alert.camera_id == camera_id)

    alerts = query.order_by(Alert.detected_at.desc()).all()
    return AlertListResponse(alerts=alerts)


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
) -> AlertResponse:
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    return alert


@router.get("/alerts/{alert_id}/video")
def get_alert_video(
    alert_id: int,
    db: Session = Depends(get_db),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
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

