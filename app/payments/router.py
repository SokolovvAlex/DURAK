import hashlib
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

import aiohttp
import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from sqlalchemy import select
from starlette import status
from starlette.responses import HTMLResponse

from app.database import SessionDep
from app.payments.dao import PaymentTransactionDAO, TransactionDAO
from app.payments.models import TxStatusEnum, TxTypeEnum, PaymentTransaction
from app.payments.schemas import TransactionStatsOut, UserTransactionsOut, TransactionOut, DepositResponse, \
    DepositRequest, WithdrawResponse, WithdrawRequest
from app.users.auth import get_current_user
from app.users.dao import UserDAO
from app.users.models import User
from app.config import settings
from app.payments.utils.plat_client import PlatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])

PLAT_SHOP_ID = settings.PLAT_SHOP_ID
PLAT_SECRET_KEY = settings.PLAT_SECRET_KEY


def get_plat_client() -> PlatClient:
    """Dependency для PlatClient"""
    return PlatClient(
        shop_id=settings.PLAT_SHOP_ID,
        secret_key=settings.PLAT_SECRET_KEY,
    )


@router.post("/deposit", response_model=DepositResponse)
async def create_deposit(
        body: DepositRequest,
        session: SessionDep,
        plat_client: PlatClient = Depends(get_plat_client),
        method: str = Query("alfa", description="Метод оплаты"),
        user: User = Depends(get_current_user)
):
    """
    Создание депозита с СИНХРОННЫМИ вызовами Plat API
    """

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user_id = user.id
    user_tg_id = user.tg_id
    amount_rub = int(Decimal(body.amount))
    logger.info(f"Creating deposit: user_id={user.id}, amount={amount_rub} rub")

    try:
        # 1. Генерируем уникальный merchant_order_id
        timestamp = int(datetime.utcnow().timestamp())
        merchant_order_id = f"tx_{user_id}_{timestamp}"

        # 2. Создаем транзакцию в БД
        tx_id = await PaymentTransactionDAO.create_deposit_transaction(
            session=session,
            user_id=user_id,
            amount_rub=float(amount_rub),
            merchant_order_id=merchant_order_id
        )



        # print(111)
        # print(user_id)
        # print(222)
        # print(merchant_order_id)
        # print(333)

        # 4. СИНХРОННЫЙ вызов Plat API (после коммита БД - безопасно)
        pay_url = plat_client.create_payment(
            merchant_order_id=merchant_order_id,
            user_id=user_tg_id,
            amount=amount_rub,  # в рублях
            method=method
        )

        await session.commit()
        logger.info(f"Transaction committed: id={tx_id}")

        logger.info(f"Deposit created successfully: tx_id={tx_id}, pay_url={pay_url}")
        return DepositResponse(tx_id=tx_id, pay_url=pay_url)

    except Exception as e:
        await session.rollback()
        logger.error(f"Deposit creation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка создания платежа: {str(e)}"
        )


@router.post("/callback")
async def plat_callback(
        payload: dict,
        session: SessionDep,
        plat_client: PlatClient = Depends(get_plat_client)
):
    """
    Callback от Plat для обработки статусов платежей
    """
    logger.info(f"Received Plat callback: {payload}")

    # 1. Проверяем подпись
    if not plat_client.verify_callback(payload):
        logger.error("Invalid callback signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # 2. Извлекаем данные
    status = int(payload.get("status", 0))
    merchant_order_id = str(payload.get("merchant_id", ""))
    plat_guid = payload.get("guid", "")
    amount_rub = float(payload.get("amount", 0))

    logger.info(f"Callback details: status={status}, order_id={merchant_order_id}, amount={amount_rub}")

    # 3. Обрабатываем только успешные платежи
    if status != 1:
        logger.info(f"Ignoring callback with status: {status}")
        return {"status": "ignored"}

    try:
        # 4. Обрабатываем успешный платеж
        success = await PaymentTransactionDAO.process_successful_deposit(
            session=session,
            merchant_order_id=merchant_order_id,
            plat_guid=plat_guid,
            amount_rub=amount_rub
        )

        if success:
            # 5. Коммитим изменения баланса
            await session.commit()
            logger.info(f"Callback processed successfully: order_id={merchant_order_id}")
            return {"status": "ok"}
        else:
            await session.rollback()
            logger.error(f"Failed to process callback: order_id={merchant_order_id}")
            return {"status": "error"}, 500

    except Exception as e:
        await session.rollback()
        logger.error(f"Callback processing error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка обработки платежа")


@router.get("/withdraw/methods")
async def get_withdraw_methods(
        plat_client: PlatClient = Depends(get_plat_client)
):
    """
    Получение доступных методов для вывода средств
    """
    try:
        methods_data = plat_client.get_withdraw_methods()
        return methods_data
    except Exception as e:
        logger.error(f"Failed to get withdraw methods: {e}")
        raise HTTPException(status_code=500, detail="Ошибка получения методов вывода")


@router.post("/withdraw", response_model=WithdrawResponse)
async def create_withdraw(
        body: WithdrawRequest,
        session: SessionDep,
        plat_client: PlatClient = Depends(get_plat_client),
        user: User = Depends(get_current_user)
):
    """
    Создание заявки на вывод средств
    """
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    amount_rub = int(Decimal(body.amount))
    logger.info(f"Creating withdraw: user_id={user.id}, amount={amount_rub}")

    try:
        # 1. Резервируем средства
        await PaymentTransactionDAO.reserve_funds_for_withdraw(
            session=session,
            user_id=user.id,
            amount_rub=float(amount_rub)
        )

        # 2. Генерируем уникальный merchant_id для выплаты
        timestamp = int(datetime.utcnow().timestamp())
        merchant_id = f"withdraw_{user.id}_{timestamp}"

        # 3. Создаем выплату в Plat
        # TODO: Нужно определить method_id для банковской карты
        method_id = 4  # Заменить на реальный method_id из get_withdraw_methods()

        withdraw_data = plat_client.create_withdraw(
            merchant_id=merchant_id,
            amount=amount_rub,
            method_id=method_id,
            purse=body.card_number,
            bank=body.bank_name
        )

        plat_withdraw_id = str(withdraw_data['withdraw']['id'])

        # 4. Создаем транзакцию вывода
        tx_id = await PaymentTransactionDAO.create_withdraw_transaction(
            session=session,
            user_id=user.id,
            amount_rub=float(amount_rub),
            card_number=body.card_number,
            plat_withdraw_id=plat_withdraw_id
        )

        # 5. Коммитим все изменения
        await session.commit()

        logger.info(f"Withdraw created successfully: tx_id={tx_id}, plat_withdraw_id={plat_withdraw_id}")
        return WithdrawResponse(
            withdraw_id=tx_id,
            status=TxStatusEnum.PENDING,
            message="Заявка на вывод создана"
        )

    except ValueError as e:
        await session.rollback()
        if "Insufficient funds" in str(e):
            raise HTTPException(status_code=400, detail="Недостаточно средств")
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        logger.error(f"Withdraw creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания вывода: {str(e)}")


@router.post("/withdraw/callback")
async def withdraw_callback(
        payload: dict,
        session: SessionDep,
        plat_client: PlatClient = Depends(get_plat_client)
):
    """
    Callback от Plat для обработки статусов выплат
    """
    logger.info(f"Received withdraw callback: {payload}")

    # TODO: Добавить проверку подписи
    # if not plat_client.verify_callback(payload):
    #     raise HTTPException(status_code=403, detail="Invalid signature")

    # Извлекаем данные
    withdraw_id = str(payload.get("withdraw_id", ""))
    status = int(payload.get("status", 0))

    logger.info(f"Withdraw callback details: withdraw_id={withdraw_id}, status={status}")

    try:
        # Обрабатываем выплату
        success = await PaymentTransactionDAO.process_successful_withdraw(
            session=session,
            plat_withdraw_id=withdraw_id,
            status=status
        )

        if success:
            await session.commit()
            logger.info(f"Withdraw callback processed successfully: {withdraw_id}")
            return {"status": "ok"}
        else:
            await session.rollback()
            logger.error(f"Failed to process withdraw callback: {withdraw_id}")
            return {"status": "error"}, 500

    except Exception as e:
        await session.rollback()
        logger.error(f"Withdraw callback processing error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка обработки выплаты")


@router.get("/withdraw/{withdraw_id}/status")
async def get_withdraw_status(
        withdraw_id: int,
        session: SessionDep,
        plat_client: PlatClient = Depends(get_plat_client)
):
    """
    Получение статуса вывода
    """
    tx = await PaymentTransactionDAO.get_transaction_by_id(session, withdraw_id)

    if not tx or tx.type != TxTypeEnum.WITHDRAW:
        raise HTTPException(status_code=404, detail="Withdraw not found")

    # Если есть plat_withdraw_id, получаем актуальный статус из Plat
    plat_status = None
    if tx.plat_guid:
        try:
            withdraw_info = plat_client.get_withdraw_info(int(tx.plat_guid))
            plat_status = withdraw_info['withdraw']['status']
        except Exception as e:
            logger.warning(f"Could not get Plat status: {e}")

    return {
        "withdraw_id": tx.id,
        "status": tx.status,
        "plat_status": plat_status,
        "amount": float(abs(tx.amount)),  # абсолютное значение
        "created_at": tx.created_at.isoformat()
    }


@router.get("/check-connection")
async def check_connection(plat_client: PlatClient = Depends(get_plat_client)):
    """Проверка подключения к Plat"""
    is_connected = plat_client.check_connection()  # Синхронный вызов
    return {"connected": is_connected}


@router.get("/transaction/{tx_id}/status")
async def get_transaction_status(
        tx_id: int,
        session: SessionDep
):
    """Получить статус транзакции"""
    tx = await PaymentTransactionDAO.get_transaction_by_id(session, tx_id)

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    user = await session.scalar(select(User).where(User.id == tx.user_id))

    return {
        "transaction_id": tx.id,
        "status": tx.status,
        "amount": float(tx.amount),
        "plat_guid": tx.plat_guid,
        "user_balance": float(user.balance) if user else 0,
        "created_at": tx.created_at.isoformat()
    }

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