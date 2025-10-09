import hashlib
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from sqlalchemy import select
from starlette import status
from starlette.responses import HTMLResponse

from app.database import SessionDep
from app.payments.dao import PaymentTransactionDAO, TransactionDAO
from app.payments.models import TxStatusEnum, TxTypeEnum, PaymentTransaction
from app.payments.schemas import TransactionStatsOut, UserTransactionsOut, TransactionOut, DepositResponse, \
    DepositRequest
from app.users.auth import get_current_user
from app.users.dao import UserDAO
from app.users.models import User
from app.config import settings
from app.payments.utils.plat_client import PlatClient, PlatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])

PLAT_SHOP_ID = settings.PLAT_SHOP_ID
PLAT_SECRET_KEY = settings.PLAT_SECRET_KEY


# def get_plat_client() -> PlatClient:
#     return PlatClient(
#         shop_id=settings.PLAT_SHOP_ID,
#         secret_key=settings.PLAT_SECRET_KEY,
#     )


@router.post("/deposit", response_model=DepositResponse)
async def create_deposit(
    body: DepositRequest,
    session: SessionDep,
    method: str = Query("alfa", description="Метод оплаты (например, alfa)"),
    user = Depends(get_current_user)
):
    """
    Создание депозита через redirect/sign (сумма в РУБЛЯХ):
    1) создаём PENDING-транзакцию;
    2) сохраняем наш merchant_order_id (временно в plat_guid);
    3) запрашиваем у PLAT redirect URL;
    4) возвращаем ссылку оплаты.
    """
    # 1. ищем пользователя

    if not user:
        raise HTTPException(404, detail="Пользователь не найден")

    # 2. создаём транзакцию (RUB!)
    amount_rub = int(Decimal(body.amount))
    logger.info(f"[DEPOSIT] start tg_id={user.tg_id} amount_rub={amount_rub} method={method}")

    tx = await PaymentTransactionDAO.create_deposit_transaction(session, user_id=user.id, amount_rub=float(amount_rub))

    # 3. merchant_order_id — наш стабильный идентификатор (на базе tx.id)
    merchant_order_id = f"tx_{tx.id}"
    await PaymentTransactionDAO.save_initial_order_id(session, tx_id=tx.id, merchant_order_id=merchant_order_id)

    await session.commit()
    logger.info(f"[DEPOSIT] database committed for tx_id={tx.id}")

    # 4. создаём платёж в PLAT (redirect URL)
    try:
        pay_url = await PlatService.create_payment_with_sign(
            merchant_order_id=merchant_order_id,
            user_id=user.tg_id,
            amount_rub=amount_rub,
            method=method,
        )
    except Exception as e:
        # отметить транзакцию как FAILED
        tx.status = TxStatusEnum.FAILED
        await session.commit()
        logger.exception(f"[DEPOSIT] PLAT sign create failed tx_id={tx.id}")
        raise HTTPException(502, detail=f"PLAT error: {e}")

    logger.info(f"[DEPOSIT] ok tx_id={tx.id} order_id={merchant_order_id} pay_url={pay_url}")
    return DepositResponse(tx_id=tx.id, pay_url=pay_url)


@router.post("/callback")
async def plat_callback(payload: dict, session: SessionDep):
    """
    Callback от PLAT:
      - проверяем signature_v2 (MD5);
      - ищем транзакцию по merchant_order_id (временно хранится в plat_guid) или по guid;
      - при успехе (status == 1) зачисляем сумму 1:1 в РУБЛЯХ и ставим POSTED.
    """
    logger.info(f"[PLAT CALLBACK] payload={payload}")

    if not PlatService.verify_callback_md5_v2(payload):
        raise HTTPException(403, detail="Invalid signature")

    status = int(payload.get("status", 0))
    merchant_order_id = str(payload.get("merchant_id", "") or payload.get("merchant_order_id", ""))
    guid = payload.get("guid")
    # важное: amount в РУБЛЯХ
    try:
        amount_rub = float(payload.get("amount", 0))
    except Exception:
        amount_rub = 0.0

    # найдём транзакцию
    tx = await PaymentTransactionDAO.find_deposit_by_order_or_guid(session, merchant_order_id=merchant_order_id, guid=guid)
    if not tx:
        logger.error(f"[PLAT CALLBACK] tx not found by order={merchant_order_id} guid={guid}")
        raise HTTPException(404, detail="Transaction not found")

    # уже обработана?
    if tx.status == TxStatusEnum.POSTED:
        logger.info(f"[PLAT CALLBACK] tx_id={tx.id} already POSTED — skip")
        return {"ok": True}

    if status == 1:
        # кредиты 1:1, фиксируем реальный guid
        balance = await PaymentTransactionDAO.finalize_successful_deposit(
            session=session,
            tx=tx,
            real_guid=guid,
            real_amount_rub=amount_rub if amount_rub > 0 else None,
        )
        return {"ok": True, "tx_id": tx.id, "credited": float(tx.amount), "balance": balance}

    # иначе — помечаем FAIL
    tx.status = TxStatusEnum.FAILED
    await session.commit()
    logger.info(f"[PLAT CALLBACK] tx_id={tx.id} FAILED status={status}")
    return {"ok": True, "status": "failed", "tx_id": tx.id}


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


# @router.post("/create_test_transaction")
# async def create_transaction(
#     session: SessionDep,
#     amount: float = Body(..., embed=True, description="Сумма транзакции"),
#     tx_type: TxTypeEnum = Body(..., embed=True, description="Тип транзакции"),
#     user=Depends(get_current_user)
# ):
#     """
#     Тестовый эндпоинт для создания транзакции.
#     Поддерживает типы: deposit, withdraw, referral_reward, payout, loss, admin_adjust.
#     """
#
#     if not user:
#         raise HTTPException(status_code=404, detail="Пользователь не найден")
#
#     # 2. Создаём транзакцию
#     tx = await PaymentTransactionDAO.create_transaction(
#         session,
#         user_id=user.id,
#         tx_type=tx_type,
#         amount=amount,
#         status=TxStatusEnum.POSTED  # тестовый кейс → сразу "проведена"
#     )
#
#     return {
#         "id": tx.id,
#         "user_id": tx.user_id,
#         "type": tx.type,
#         "amount": float(tx.amount),
#         "status": tx.status,
#         "created_at": tx.created_at.isoformat()
#     }