import json
import os
from typing import Iterable, Optional

import firebase_admin
from firebase_admin import credentials, messaging


_app: Optional[firebase_admin.App] = None


def _get_app() -> Optional[firebase_admin.App]:
    """
    Initializes Firebase Admin lazily.
    If FIREBASE_SERVICE_ACCOUNT_JSON is not set, returns None (push disabled).
    """
    global _app
    if _app is not None:
        return _app

    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None

    info = json.loads(raw)
    cred = credentials.Certificate(info)
    _app = firebase_admin.initialize_app(cred)
    return _app


def send_alert_push(tokens: Iterable[str], *, alert_id: int, threat_type: str, detected_at_iso: str) -> None:
    app = _get_app()
    if app is None:
        return

    token_list = [t for t in tokens if t]
    if not token_list:
        return

    message = messaging.MulticastMessage(
        data={
            "alert_id": str(alert_id),
            "threat_type": threat_type,
            "detected_at": detected_at_iso,
        },
        tokens=token_list,
    )

    # We intentionally don't raise: alert creation shouldn't fail because of push issues.
    try:
        messaging.send_multicast(message, app=app)
    except Exception:
        return
