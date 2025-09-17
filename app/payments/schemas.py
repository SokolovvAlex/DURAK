from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

from app.payments.models import TxStatusEnum, TxTypeEnum


# ==== ЗАПРОСЫ ====

class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма пополнения")


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма вывода")
    card: str = Field(..., min_length=12, max_length=19, description="Номер карты/кошелька")


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


class TransactionOut(BaseModel):
    id: int
    type: TxTypeEnum
    amount: float
    status: TxStatusEnum
    created_at: datetime

    class Config:
        from_attributes = True

class TransactionStatsOut(BaseModel):
    total_transactions: int
    total_deposits: float
    total_withdrawals: float
    total_earned: float
    total_lost: float
    net_flow: float

class UserTransactionsOut(BaseModel):
    transactions: List[TransactionOut]
    stats: TransactionStatsOut