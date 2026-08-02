from ..core.database import Base
from sqlalchemy import Integer, String, DateTime, func, ForeignKey, CheckConstraint, Index, text
from datetime import datetime
from sqlalchemy.orm import mapped_column, Mapped
import uuid

class User(Base):
    __tablename__ = "users"

    id:Mapped[int] = mapped_column(Integer,
                       primary_key=True)

    name:Mapped[str] = mapped_column(String(100), unique=True)
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

class Space(Base):
    __tablename__ = "spaces"

    id:Mapped[int] = mapped_column(Integer,primary_key=True)
    name:Mapped[str] = mapped_column(String(100))
    agent_instruction:Mapped[str | None] 
    invite_code:Mapped[str] =mapped_column(unique=True, index=True)
    created_at:Mapped[datetime] = mapped_column(server_default=func.now())
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"))

class SpaceMember(Base):
    __tablename__ = "space_members"

    space_id:Mapped[int] = mapped_column(ForeignKey("spaces.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role:Mapped[str] = mapped_column(default="member")
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('member', 'admin')",
            name="ck_space_member_role",
        ),
    )

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="AI")
    model: Mapped[str | None]        # overrides settings.agent_model if set
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Message(Base):
    __tablename__="messages"
    id:Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id"))
    sender_user_id:Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sender_agent_id:Mapped[int | None]  = mapped_column(ForeignKey("agents.id"))
    content: Mapped[str]
    message_type :Mapped[str] = mapped_column(default="text")
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_messages_space_created", "space_id", "created_at"),
        CheckConstraint(
            "(sender_user_id IS NULL) != (sender_agent_id IS NULL)",
            name="ck_messages_exactly_one_sender")
    )

Index(
    "ix_messages_content_fts",
    text("to_tsvector('simple', content)"),
    postgresql_using="gin",
)
    

