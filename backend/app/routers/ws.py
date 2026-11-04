"""WebSocket endpoint for live violation, camera status, and finish alerts."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status

from backend.app.db.repository import Repository
from backend.app.deps import get_repository, get_user_from_token_str
from backend.app.services.alert_service import alert_broadcaster

logger = logging.getLogger("traffic_ai.ws")
router = APIRouter(tags=["alerts"])


@router.websocket("/ws/alerts")
async def websocket_alerts(
    websocket: WebSocket,
    token: str | None = Query(None),
    repo: Repository = Depends(get_repository),
) -> None:
    # Verify token BEFORE accepting connection
    user = get_user_from_token_str(token or "", repo)
    if user is None:
        logger.warning("Rejecting unauthorized WebSocket connection attempt.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await alert_broadcaster.connect(websocket)
    try:
        while True:
            # Keep alive and receive any pings/messages from client
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        await alert_broadcaster.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket connection closed with exception: %s", exc)
        await alert_broadcaster.disconnect(websocket)
