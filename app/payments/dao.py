from datetime import datetime

from sqlalchemy import select
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