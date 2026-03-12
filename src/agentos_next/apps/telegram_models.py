from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass(frozen=True)
class TelegramUser:
    id: int
    is_bot: bool
    first_name: str
    username: Optional[str] = None
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramUser":
        return cls(
            id=d.get("id", 0),
            is_bot=d.get("is_bot", False),
            first_name=d.get("first_name", ""),
            username=d.get("username")
        )

@dataclass(frozen=True)
class TelegramChat:
    id: int
    type: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramChat":
        return cls(
            id=d.get("id", 0),
            type=d.get("type", "")
        )


@dataclass(frozen=True)
class TelegramPhotoSize:
    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramPhotoSize":
        return cls(
            file_id=str(d.get("file_id") or ""),
            file_unique_id=str(d.get("file_unique_id") or ""),
            width=int(d.get("width", 0) or 0),
            height=int(d.get("height", 0) or 0),
            file_size=(int(d.get("file_size")) if d.get("file_size") is not None else None),
        )


@dataclass(frozen=True)
class TelegramDocument:
    file_id: str
    file_unique_id: str
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramDocument":
        return cls(
            file_id=str(d.get("file_id") or ""),
            file_unique_id=str(d.get("file_unique_id") or ""),
            file_name=(str(d.get("file_name")) if d.get("file_name") is not None else None),
            mime_type=(str(d.get("mime_type")) if d.get("mime_type") is not None else None),
            file_size=(int(d.get("file_size")) if d.get("file_size") is not None else None),
        )


@dataclass(frozen=True)
class TelegramVoice:
    file_id: str
    file_unique_id: str
    duration: int
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramVoice":
        return cls(
            file_id=str(d.get("file_id") or ""),
            file_unique_id=str(d.get("file_unique_id") or ""),
            duration=int(d.get("duration", 0) or 0),
            mime_type=(str(d.get("mime_type")) if d.get("mime_type") is not None else None),
            file_size=(int(d.get("file_size")) if d.get("file_size") is not None else None),
        )


@dataclass(frozen=True)
class TelegramVideo:
    file_id: str
    file_unique_id: str
    width: int
    height: int
    duration: int
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramVideo":
        return cls(
            file_id=str(d.get("file_id") or ""),
            file_unique_id=str(d.get("file_unique_id") or ""),
            width=int(d.get("width", 0) or 0),
            height=int(d.get("height", 0) or 0),
            duration=int(d.get("duration", 0) or 0),
            mime_type=(str(d.get("mime_type")) if d.get("mime_type") is not None else None),
            file_size=(int(d.get("file_size")) if d.get("file_size") is not None else None),
        )


@dataclass(frozen=True)
class TelegramMessage:
    message_id: int
    date: int
    chat: TelegramChat
    from_user: Optional[TelegramUser] = None
    text: Optional[str] = None
    caption: Optional[str] = None
    media_group_id: Optional[str] = None
    photo: tuple[TelegramPhotoSize, ...] = ()
    document: Optional[TelegramDocument] = None
    voice: Optional[TelegramVoice] = None
    video: Optional[TelegramVideo] = None

    @property
    def effective_text(self) -> str:
        value = str(self.text or "").strip()
        if value:
            return value
        return str(self.caption or "").strip()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramMessage":
        from_user = TelegramUser.from_dict(d["from"]) if "from" in d else None
        photo = tuple(
            TelegramPhotoSize.from_dict(item)
            for item in (d.get("photo") or [])
            if isinstance(item, dict)
        )
        document = TelegramDocument.from_dict(d["document"]) if isinstance(d.get("document"), dict) else None
        voice = TelegramVoice.from_dict(d["voice"]) if isinstance(d.get("voice"), dict) else None
        video = TelegramVideo.from_dict(d["video"]) if isinstance(d.get("video"), dict) else None
        return cls(
            message_id=d.get("message_id", 0),
            date=d.get("date", 0),
            chat=TelegramChat.from_dict(d.get("chat", {})),
            from_user=from_user,
            text=d.get("text"),
            caption=d.get("caption"),
            media_group_id=(str(d.get("media_group_id")) if d.get("media_group_id") is not None else None),
            photo=photo,
            document=document,
            voice=voice,
            video=video,
        )

@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    message: Optional[TelegramMessage] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelegramUpdate":
        if "update_id" not in d:
            raise ValueError("Missing update_id")
            
        message = TelegramMessage.from_dict(d["message"]) if "message" in d else None
        return cls(
            update_id=d["update_id"],
            message=message
        )
