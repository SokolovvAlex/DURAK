
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GameResultEnum(str, Enum):
    WIN = "win"
    LOSS = "loss"
    LOSS_BY_LEAVE = "loss_by_leave"  # Проигрыш из-за лива из игры


class GameResult(Base):
    __tablename__ = "game_results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    result: Mapped[GameResultEnum] = mapped_column(SQLEnum(GameResultEnum, name="gameresultenum"), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship back to User
    user: Mapped["User"] = relationship("User", back_populates="game_results")

    def __repr__(self) -> str:
        return f"<GameResult id={self.id} user_id={self.user_id} result={self.result}>"


class GameType(Base):
    __tablename__ = "game_types"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rules: Mapped[str] = mapped_column(Text, nullable=False)
    max_users: Mapped[int] = mapped_column(nullable=False)
    min_users: Mapped[int] = mapped_column(nullable=False)
    max_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    min_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    def __repr__(self) -> str:
        return f"<GameType id={self.id} name={self.name!r}>"

