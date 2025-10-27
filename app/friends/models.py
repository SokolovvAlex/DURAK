from datetime import datetime
from sqlalchemy import Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.database import Base


class Friend(Base):
    __tablename__ = "friends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    friend_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 🔗 связи
    inviter = relationship("User", foreign_keys="Friend.user_id", back_populates="invited_friends")
    invited = relationship("User", foreign_keys="Friend.friend_id", back_populates="invited_by")

    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uq_user_friend"),)

