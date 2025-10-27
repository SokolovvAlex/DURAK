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
    DepositRequest, WithdrawResponse, WithdrawRequest, WithdrawMethodsResponse
from app.users.auth import get_current_user
from app.users.dao import UserDAO
from app.users.models import User
from app.config import settings
from app.payments.utils.plat_client import PlatClient
from decimal import Decimal

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
    # if not plat_client.verify_callback(payload):
    #     logger.error("Invalid callback signature")
    #     raise HTTPException(status_code=403, detail="Invalid signature")

    # 2. Извлекаем данные
    status = int(payload.get("status", 0))
    merchant_order_id = str(payload.get("merchant_id", ""))
    plat_guid = payload.get("guid", "")
    amount_rub = float(payload.get("amount", 0))

    logger.info(f"Callback details: status={status}, order_id={merchant_order_id}, amount={amount_rub}")

    # 3. Обрабатываем только успешные платежи
    # if status != 1:
    #     logger.info(f"Ignoring callback with status: {status}")
    #     return {"status": "ignored"}

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


@router.get("/withdraw/methods", response_model=WithdrawMethodsResponse)
async def get_withdraw_methods(
        plat_client: PlatClient = Depends(get_plat_client)
):
    """
    Получение доступных методов и банков для вывода средств
    """
    try:
        methods_data = plat_client.get_withdraw_methods()

        if methods_data.get("success"):
            return WithdrawMethodsResponse(**methods_data)
        else:
            raise HTTPException(status_code=500, detail="Ошибка получения методов")

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

    from decimal import Decimal

    amount_rub = int(Decimal(body.amount))
    logger.info(f"Creating withdraw: user_id={user.id}, amount={amount_rub}, method_id={body.method_id}")

    try:
        # 1. Получаем методы для проверки
        methods_data = plat_client.get_withdraw_methods()
        if not methods_data.get("success"):
            raise HTTPException(status_code=500, detail="Не удалось получить методы выплат")

        # 2. Проверяем что метод существует
        method_exists = any(method['id'] == body.method_id for method in methods_data.get('methods', []))
        if not method_exists:
            raise HTTPException(status_code=400, detail="Неверный метод выплаты")

        # 3. Проверяем сумму
        method_info = next((m for m in methods_data['methods'] if m['id'] == body.method_id), None)
        if amount_rub < method_info['min']:
            raise HTTPException(status_code=400, detail=f"Минимальная сумма: {method_info['min']} руб")
        if amount_rub > method_info['max']:
            raise HTTPException(status_code=400, detail=f"Максимальная сумма: {method_info['max']} руб")

        # 4. Проверяем баланс пользователя
        from decimal import Decimal
        if user.balance < Decimal(str(amount_rub)):
            raise HTTPException(status_code=400, detail="Недостаточно средств")

        # 5. Резервируем средства (списываем с баланса)
        user.balance -= Decimal(str(amount_rub))

        # 6. Генерируем merchant_id
        timestamp = int(datetime.utcnow().timestamp())
        merchant_id = f"withdraw_{user.id}_{timestamp}"

        # 7. Создаем транзакцию
        tx = PaymentTransaction(
            user_id=user.id,
            type=TxTypeEnum.WITHDRAW,
            amount=-float(amount_rub),
            status=TxStatusEnum.PENDING,
            merchant_order_id=merchant_id,
            plat_withdraw_id=None,
            created_at=datetime.utcnow(),
        )

        session.add(tx)
        await session.flush()  # Получаем ID без коммита
        tx_id = tx.id

        # 8. Получаем название банка если указан bank_id
        bank_name = None
        if body.bank_id and methods_data.get('banks'):
            bank_name = methods_data['banks'].get(body.bank_id)

        # 9. Создаем выплату в Plat (передаем наш merchant_id)
        withdraw_data = plat_client.create_withdraw(
            merchant_id=merchant_id,  # наш внутренний ID
            amount=amount_rub,
            method_id=body.method_id,
            purse=body.purse,
            bank=bank_name
        )

        plat_withdraw_id = str(withdraw_data['withdraw']['id'])

        # 10. Обновляем транзакцию с plat_withdraw_id
        tx.plat_withdraw_id = plat_withdraw_id

        # 11. Коммитим все изменения
        await session.commit()

        # 12. Обновляем объект пользователя после коммита
        await session.refresh(user)

        logger.info(f"Withdraw created: tx_id={tx_id}, plat_withdraw_id={plat_withdraw_id}")
        return WithdrawResponse(
            withdraw_id=tx_id,
            status=TxStatusEnum.PENDING,
            plat_withdraw_id=plat_withdraw_id,
            message="Заявка на вывод создана"
        )

    except ValueError as e:
        await session.rollback()
        if "Insufficient funds" in str(e):
            raise HTTPException(status_code=400, detail="Недостаточно средств")
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        await session.rollback()
        raise
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

    # 1. Проверяем подпись (раскомментируйте когда будете готовы)
    # if not plat_client.verify_callback(payload):
    #     raise HTTPException(status_code=403, detail="Invalid signature")

    # 2. Извлекаем данные - ВАЖНО: используем merchant_id для поиска
    merchant_id = str(payload.get("merchant_id", ""))  # наш внутренний ID
    plat_withdraw_id = str(payload.get("withdraw_id", ""))
    status = int(payload.get("status", 0))

    logger.info(f"Withdraw callback: merchant_id={merchant_id}, status={status}")

    try:
        # 3. Обрабатываем выплату по нашему merchant_id
        success = await PaymentTransactionDAO.process_withdraw_callback(
            session=session,
            merchant_id=merchant_id,
            plat_withdraw_id=plat_withdraw_id,
            status=status
        )

        if success:
            await session.commit()
            logger.info(f"Withdraw callback processed: {merchant_id}")
            return {"status": "ok"}
        else:
            await session.rollback()
            logger.error(f"Failed to process withdraw callback: {merchant_id}")
            return {"status": "error"}, 500

    except Exception as e:
        await session.rollback()
        logger.error(f"Withdraw callback error: {e}")
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


@router.post("/test/withdraw/simple")
async def test_create_withdraw_simple(
        body: WithdrawRequest,
        session: SessionDep,
        user: User = Depends(get_current_user)
):
    """
    Тестовый эндпоинт для создания выплаты ТОЛЬКО в БД (без вызова Plat API)
    """
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    amount_rub = int(Decimal(body.amount))
    logger.info(f"Creating TEST withdraw (DB only): user_id={user.id}, amount={amount_rub}")

    try:
        # 1. Проверяем баланс пользователя

        if user.balance < Decimal(str(amount_rub)):
            raise HTTPException(status_code=400, detail="Недостаточно средств")

        # 2. Резервируем средства (списываем с баланса)
        user.balance -= Decimal(str(amount_rub))

        # 3. Генерируем merchant_id
        timestamp = int(datetime.utcnow().timestamp())
        merchant_id = f"withdraw_{user.id}_{timestamp}"

        # 4. Создаем транзакцию
        tx = PaymentTransaction(
            user_id=user.id,
            type=TxTypeEnum.WITHDRAW,
            amount=-float(amount_rub),
            status=TxStatusEnum.PENDING,
            merchant_order_id=merchant_id,
            plat_withdraw_id=None,
            created_at=datetime.utcnow(),
        )

        session.add(tx)
        await session.flush()  # Получаем ID без коммита
        tx_id = tx.id

        # 5. Генерируем тестовый plat_withdraw_id
        plat_withdraw_id = f"test_plat_{tx_id}_{timestamp}"

        # 6. Обновляем транзакцию
        tx.plat_withdraw_id = plat_withdraw_id

        # 7. Коммитим
        await session.commit()

        # 8. Обновляем объект пользователя после коммита
        await session.refresh(user)

        logger.info(f"TEST withdraw created successfully: tx_id={tx_id}, merchant_id={merchant_id}")

        return {
            "success": True,
            "transaction_id": tx_id,
            "merchant_id": merchant_id,
            "plat_withdraw_id": plat_withdraw_id,
            "user_id": user.id,
            "user_balance": float(user.balance),
            "amount": amount_rub,
            "status": "pending",
            "message": "Тестовая выплата создана в БД (без вызова Plat)"
        }

    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Test withdraw creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания тестовой выплаты: {str(e)}")


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