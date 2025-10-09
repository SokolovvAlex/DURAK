from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

from app.payments.models import TxStatusEnum, TxTypeEnum


class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма пополнения в рублях")


class DepositResponse(BaseModel):
    tx_id: int
    pay_url: str


class PlatCallback(BaseModel):
    signature: str
    signature_v2: str
    payment_id: Optional[str] = None
    guid: str
    merchant_order_id: str
    user_id: str
    status: int  # 0 - pending, 1 - success, etc.
    amount: Decimal  # в рублях
    amount_to_pay: Optional[Decimal] = None
    amount_to_shop: Optional[Decimal] = None
    expired: Optional[str] = None


class TransactionOut(BaseModel):
    id: int
    type: TxTypeEnum
    amount: float
    status: TxStatusEnum
    plat_guid: Optional[str]
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