from pydantic import BaseModel


class IncomingChatMessage(BaseModel):
    type: str
    receiverId: str
    text: str