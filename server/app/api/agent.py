from fastapi import APIRouter, Depends

from ..agents import assistant
from ..auth import User
from ..models import ChatIn
from ..ratelimit import chat_limit, default_limit

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", dependencies=[Depends(default_limit)])
def chat(body: ChatIn, user: User = Depends(chat_limit)):
    return assistant.chat(user, body.message, body.conversation_id)
