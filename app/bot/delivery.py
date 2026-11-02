"""Доставка уведомлений в MAX. Билет здесь не создаётся."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthIdentity, OutboundNotice
from app.max_client.base import OutboundButton
from app.max_client.client import DeliveryBlocked, DeliveryRetry


async def send_pending_notices(session: AsyncSession, sender: object, *, limit: int = 20) -> int:
    rows = list(
        await session.scalars(
            select(OutboundNotice)
            .where(OutboundNotice.status == "pending")
            .order_by(OutboundNotice.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    sent = 0
    for row in rows:
        identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == row.user_id,
                AuthIdentity.provider == "max",
                AuthIdentity.revoked_at.is_(None),
            )
        )
        if identity is None:
            row.status = "failed"
            row.last_error = "no_max"
            row.attempts += 1
            continue
        buttons: list[OutboundButton] = []
        if row.button_text and row.button_payload:
            buttons.append(OutboundButton(row.button_text, row.button_payload))
        try:
            await sender.send_text(
                user_id=identity.external_id,
                chat_id=None,
                text=row.body,
                buttons=buttons,
            )
        except DeliveryBlocked:
            row.status = "failed"
            row.last_error = "blocked"
            row.attempts += 1
            continue
        except DeliveryRetry:
            row.attempts += 1
            row.last_error = "retry"
            if row.attempts >= 5:
                row.status = "failed"
            continue
        except Exception:
            row.attempts += 1
            row.last_error = "error"
            if row.attempts >= 5:
                row.status = "failed"
            continue
        row.status = "sent"
        row.sent_at = datetime.now(UTC)
        row.last_error = None
        sent += 1
    return sent
