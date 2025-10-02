from datetime import datetime
from typing import List

from sqlalchemy import select, func, case
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.game.models import GameResult, GameResultEnum
from app.payments.models import PaymentTransaction, TxTypeEnum, TxStatusEnum
from app.users.models import User


class PaymentTransactionDAO(BaseDAO):
    model = PaymentTransaction

    @classmethod
    async def add(cls, session: AsyncSession, **values):
        try:
            new_instance = cls.model(**values)
            session.add(new_instance)

            # flush → получаем id без коммита
            await session.flush()

            # refresh → гарантируем, что объект заполнен (id, defaults, server_default)
            await session.refresh(new_instance)

            # теперь можно коммитить
            await session.commit()

            return new_instance

        except SQLAlchemyError as e:
            await session.rollback()
            raise e

    @classmethod
    async def create_transaction(
            cls,
            session: AsyncSession,
            user_id: int,
            tx_type,
            amount: float,
            status,
    ) -> PaymentTransaction:
        """
        Создание транзакции для пользователя (без лишних зависимостей).
        """
        try:
            tx = cls.model(
                user_id=user_id,
                type=tx_type,
                amount=amount,
                status=status,
            )
            session.add(tx)
            await session.commit()  # сохраняем в БД
            await session.refresh(tx)  # подтягиваем id и created_at
            return tx
        except SQLAlchemyError as e:
            await session.rollback()
            raise e


class TransactionDAO:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply_game_result(self, winner_id: int, loser_id: int, stake: int):
        """
        Начисляет выигрыш победителю и списывает у проигравшего.
        Создаёт:
          • PaymentTransaction (для истории пополнений/списаний)
          • GameResult (для истории игр)
        """
        # --- Получаем пользователей ---
        winner = await self.session.scalar(select(User).where(User.tg_id == winner_id))
        loser = await self.session.scalar(select(User).where(User.tg_id == loser_id))

        if not winner or not loser:
            raise ValueError("Пользователь не найден")

        # --- Обновляем балансы ---
        winner.balance += stake
        loser.balance -= stake

        # --- Создаём транзакции ---
        win_tx = PaymentTransaction(
            user_id=winner.id,
            amount=stake,
            type=TxTypeEnum.PAYOUT,
            status=TxStatusEnum.POSTED,
            created_at=datetime.utcnow()
        )
        lose_tx = PaymentTransaction(
            user_id=loser.id,
            amount=-stake,
            type=TxTypeEnum.LOSS,
            status=TxStatusEnum.POSTED,
            created_at=datetime.utcnow()
        )

        # --- Создаём записи в GameResult ---
        win_result = GameResult(
            user_id=winner.id,
            result=GameResultEnum.WIN,
            rate=stake,
        )
        lose_result = GameResult(
            user_id=loser.id,
            result=GameResultEnum.LOSS,
            rate=stake,
        )

        self.session.add_all([win_tx, lose_tx, win_result, lose_result])
        await self.session.flush()  # фиксируем, чтобы появились ID
        await self.session.refresh(win_result)
        await self.session.refresh(lose_result)

        return {
            "winner_balance": float(winner.balance),
            "loser_balance": float(loser.balance),
            "winner_result": win_result.id,
            "loser_result": lose_result.id,
        }

    @classmethod
    async def get_user_transactions(cls, session: AsyncSession, tg_id: int) -> List[PaymentTransaction]:
        """Получить все транзакции пользователя по tg_id"""
        stmt = (
            select(PaymentTransaction)
            .join(User, PaymentTransaction.user_id == User.id)
            .where(User.tg_id == tg_id)
            .order_by(PaymentTransaction.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @classmethod
    async def get_user_transactions_stats(cls, session: AsyncSession, tg_id: int) -> dict:
        """Получить статистику транзакций пользователя по tg_id"""
        stmt = (
            select(
                func.count(PaymentTransaction.id).label('total_transactions'),
                func.sum(
                    case((PaymentTransaction.type == TxTypeEnum.DEPOSIT, PaymentTransaction.amount), else_=0)).label(
                    'total_deposits'),
                func.sum(
                    case((PaymentTransaction.type == TxTypeEnum.WITHDRAW, PaymentTransaction.amount), else_=0)).label(
                    'total_withdrawals'),
                func.sum(case((PaymentTransaction.type.in_([TxTypeEnum.PAYOUT, TxTypeEnum.REFERRAL_REWARD]),
                               PaymentTransaction.amount), else_=0)).label('total_earned'),
                func.sum(
                    case((PaymentTransaction.type.in_([TxTypeEnum.LOSS]), PaymentTransaction.amount), else_=0)).label(
                    'total_lost'),
                func.sum(PaymentTransaction.amount).label('net_flow')
            )
            .join(User, PaymentTransaction.user_id == User.id)
            .where(User.tg_id == tg_id)
        )
        result = await session.execute(stmt)
        stats = result.first()

        return {
            'total_transactions': stats.total_transactions or 0,
            'total_deposits': float(stats.total_deposits or 0),
            'total_withdrawals': float(stats.total_withdrawals or 0),
            'total_earned': float(stats.total_earned or 0),
            'total_lost': float(stats.total_lost or 0),
            'net_flow': float(stats.net_flow or 0)
        }

    @classmethod
    async def get_user_transactions_by_type(
            cls,
            session: AsyncSession,
            tg_id: int,
            transaction_type: TxTypeEnum
    ) -> List[PaymentTransaction]:
        """Получить транзакции пользователя по типу"""
        stmt = (
            select(PaymentTransaction)
            .join(User, PaymentTransaction.user_id == User.id)
            .where(
                User.tg_id == tg_id,
                PaymentTransaction.type == transaction_type
            )
            .order_by(PaymentTransaction.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().all()