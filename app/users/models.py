from datetime import datetime
from typing import Optional, List

from sqlalchemy import BigInteger, String, Numeric, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.payments.models import PaymentTransaction

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    balance: Mapped[float] = mapped_column(Numeric(10, 2), default=0.00, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    login: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships (based on schema refs)
    game_results = relationship("GameResult", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("PaymentTransaction", back_populates="user", cascade="all, delete-orphan")


    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} balance={self.balance}>"

