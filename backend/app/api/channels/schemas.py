from pydantic import BaseModel, EmailStr
from typing import Optional, Any, Dict, List


class ChannelCreateRequest(BaseModel):
    receiver_name: str
    receiver_company: Optional[str]
    receiver_email: Optional[EmailStr]
    receiver_phone: Optional[str]


class ChannelCreateResponse(BaseModel):
    id: str
    public_link: str


class ChannelListItem(BaseModel):
    id: str
    receiver_name: str
    receiver_email: Optional[str]
    status: str
    created_at: str
    has_unread: bool = False


class MessageIn(BaseModel):
    message_type: str
    data: Dict[str, Any]


class MessageOut(BaseModel):
    id: str
    sender_role: str
    type: str
    payload: Dict[str, Any]
    created_at: str
