from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Message, User, as_utc
from app.schemas import MessageIn, MessageOut

router = APIRouter(prefix="/api/chat", tags=["chat"])

# How many messages the panel loads when it first opens.
PAGE_SIZE = 50


def _out(m: Message, u: User | None) -> MessageOut:
    return MessageOut(
        id=m.id,
        user_id=m.user_id,
        full_name=u.full_name if u else None,
        role=u.role if u else None,
        body=m.body,
        created_at=as_utc(m.created_at),
    )


@router.get("", response_model=list[MessageOut])
def list_messages(
    after: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """One shared team room, oldest-first. Any role may read it — same reasoning as
    /api/meta/online. `after` is the poll path (usually returns []); omitting it
    loads the tail. get_current_user also refreshes the presence heartbeat, so a
    client polling the chat keeps itself on the online list.
    """
    stmt = select(Message, User).outerjoin(User, Message.user_id == User.id)
    if after is not None:
        rows = db.execute(stmt.where(Message.id > after).order_by(Message.id)).all()
    else:
        # Tail is cheapest DESC; flip it so the client always appends.
        rows = db.execute(stmt.order_by(Message.id.desc()).limit(PAGE_SIZE)).all()[::-1]
    return [_out(m, u) for m, u in rows]


@router.post("", response_model=MessageOut)
def post_message(
    payload: MessageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Author comes from the token, never from the body."""
    msg = Message(user_id=user.id, body=payload.body)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _out(msg, user)
