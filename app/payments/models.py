from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TxTypeEnum(str, Enum):
    DEPOSIT = "deposit"             # пополнение
    WITHDRAW = "withdraw"           # вывод
    REFERRAL_REWARD = "referral_reward"  # реферальная выплата
    PAYOUT = "payout"               # выплата выигрыша
    LOSS = "loss"                   # списание за проигрыш
    ADMIN_ADJUST = "admin_adjust"   # ручная корректировка


class TxStatusEnum(str, Enum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    REVERSED = "reversed"


class PaymentTransaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    type: Mapped[TxTypeEnum] = mapped_column(SQLEnum(TxTypeEnum, name="txtypeenum"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[TxStatusEnum] = mapped_column(
        SQLEnum(TxStatusEnum, name="txstatusenum"),
        default=TxStatusEnum.PENDING,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship back to User
    user = relationship("User", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} user_id={self.user_id} type={self.type} amount={self.amount}>"
