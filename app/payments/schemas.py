from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ==== ENUMS (синхронизированы с моделями) ====

class TxTypeEnum(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    REFERRAL_REWARD = "referral_reward"
    BET = "bet"
    PAYOUT = "payout"
    ADMIN_ADJUST = "admin_adjust"


class TxStatusEnum(str, Enum):
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    REVERSED = "reversed"


# ==== ЗАПРОСЫ ====

class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма пополнения")


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма вывода")
    card: str = Field(..., min_length=12, max_length=19, description="Номер карты/кошелька")


# ==== ОТВЕТЫ ====

class TransactionOut(BaseModel):
    id: int
    user_id: int
    type: TxTypeEnum
    amount: Decimal
    status: TxStatusEnum
    created_at: datetime
    ext_ref: Optional[str] = None

    class Config:
        from_attributes = True


class DepositResponse(BaseModel):
    tx_id: int
    pay_url: str


class WithdrawResponse(BaseModel):
    tx_id: int
    status: TxStatusEnum


# ==== CALLBACK от PLAT ====

class PlatCallback(BaseModel):
    shop_id: str
    order_id: str            # наш tx_id
    payment_id: Optional[str] = None
    payout_id: Optional[str] = None
    amount: Decimal
    status: str              # "success" / "failed"
    time: int
    sign: str