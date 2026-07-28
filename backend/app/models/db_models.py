from ..core.database import Base
from sqlalchemy import Integer, String, DateTime, func
from datetime import datetime
from sqlalchemy.orm import mapped_column, Mapped

class User(Base):
    __tablename__ = "users"

    id:Mapped[int] = mapped_column(Integer,
                       primary_key=True)
    
    name:Mapped[str] = mapped_column(String(100))
    email:Mapped[str] = mapped_column(String(200),unique=True)
    password_hash:Mapped[str] = mapped_column(String)
    created_at:Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                server_default=func.now(),
                                                nullable=False)
    role:Mapped[str] = mapped_column(
        String(20),
        default="USER",
        nullable=False
    )
