from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.config import Base


class AiChatModel(Base):
    __tablename__= "chats"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #user_id: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())