from fastapi import APIRouter, Depends, HTTPException, Request, Body

from app.database import SessionDep
from app.payments.dao import PaymentTransactionDAO, TransactionDAO
from app.payments.models import TxStatusEnum, TxTypeEnum
from app.payments.schemas import TransactionStatsOut, UserTransactionsOut, TransactionOut
from app.users.auth import get_current_user
from app.users.dao import UserDAO
from app.users.models import User
from app.config import settings
from app.payments.utils.plat_client import PlatClient

router = APIRouter(prefix="/payments", tags=["Payments"])


def get_plat_client() -> PlatClient:
    return PlatClient(
        shop_id=settings.PLAT_SHOP_ID,
        secret_key=settings.PLAT_SECRET_KEY,
    )


# ---- 1. Создание платежа ----
@router.post("/paycash")
async def paycash(
    amount: int,
    current_user: User = Depends(get_current_user),
):
    plat = get_plat_client()
    # ⚠️ amount: проверить — в копейках или рублях (100₽ = 10000 ?)
    guid, pay_url, payment_data = await plat.create_payment(
        merchant_order_id="ORDER123",  # тут обычно id транзакции из БД
        user_id=current_user.id,
        amount=amount,
        method="card",
    )

    return {"guid": guid, "pay_url": pay_url, "payment": payment_data}


# ---- 2. Callback от PLAT ----
@router.post("/callback")
async def plat_callback(request: Request):
    data = await request.json()

    plat = get_plat_client()
    if not plat.verify_callback(data):
        raise HTTPException(status_code=403, detail="Invalid signature")

    status = data.get("status")
    merchant_order_id = data.get("merchant_order_id")  # если передают обратно
    amount = data.get("amount")

    # 👉 тут ты обновляешь транзакцию в БД
    # if status == 1: # success
    #     update_transaction(merchant_order_id, posted=True)

    return {"ok": True}


@router.get("/transactions/{tg_id}")
async def get_user_transactions(
        tg_id: int,
        session: SessionDep
):
    """Получить все транзакции пользователя по tg_id с статистикой"""
    transactions = await TransactionDAO.get_user_transactions(session, tg_id)
    stats = await TransactionDAO.get_user_transactions_stats(session, tg_id)

    if not transactions:
        raise HTTPException(status_code=404, detail="No transactions found for user")

    return UserTransactionsOut(
        transactions=[TransactionOut.model_validate(tx) for tx in transactions],
        stats=TransactionStatsOut(**stats)
    )


@router.post("/create_test_transaction")
async def create_transaction(
    session: SessionDep,
    amount: float = Body(..., embed=True, description="Сумма транзакции"),
    tx_type: TxTypeEnum = Body(..., embed=True, description="Тип транзакции"),
    user=Depends(get_current_user)
):
    """
    Тестовый эндпоинт для создания транзакции.
    Поддерживает типы: deposit, withdraw, referral_reward, payout, loss, admin_adjust.
    """

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # 2. Создаём транзакцию
    tx = await PaymentTransactionDAO.create_transaction(
        session,
        user_id=user.id,
        tx_type=tx_type,
        amount=amount,
        status=TxStatusEnum.POSTED  # тестовый кейс → сразу "проведена"
    )

    return {
        "id": tx.id,
        "user_id": tx.user_id,
        "type": tx.type,
        "amount": float(tx.amount),
        "status": tx.status,
        "created_at": tx.created_at.isoformat()
    }