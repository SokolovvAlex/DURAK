import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, func, case
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.game.models import GameResult, GameResultEnum
from app.payments.models import PaymentTransaction, TxTypeEnum, TxStatusEnum
from app.users.models import User

logger = logging.getLogger(__name__)


class PaymentTransactionDAO(BaseDAO):
    model = PaymentTransaction

    @staticmethod
    async def create_deposit_transaction(
        session: AsyncSession,
        user_id: int,
        amount_rub: float,
    ) -> PaymentTransaction:
        """
        Создаём PENDING-транзакцию пополнения. Сумма — в РУБЛЯХ.
        """
        logger.info(f"[DAO] create_deposit_transaction user_id={user_id} amount={amount_rub}")

        user = await session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise ValueError(f"User {user_id} not found")

        tx = PaymentTransaction(
            user_id=user_id,
            type=TxTypeEnum.DEPOSIT,
            amount=amount_rub,
            status=TxStatusEnum.PENDING,
            created_at=datetime.utcnow(),
        )

        session.add(tx)
        await session.flush()
        await session.refresh(tx)
        logger.info(f"[DAO] deposit tx created id={tx.id}")
        return tx

    @staticmethod
    async def save_initial_order_id(
        session: AsyncSession,
        tx_id: int,
        merchant_order_id: str,
    ) -> None:
        """
        До редиректа сохраняем наш merchant_order_id в plat_guid (как временное поле).
        """
        logger.debug(f"[DAO] save_initial_order_id tx_id={tx_id} order_id={merchant_order_id}")
        tx = await session.get(PaymentTransaction, tx_id)
        if not tx:
            raise ValueError(f"Transaction {tx_id} not found")
        tx.plat_guid = merchant_order_id
        # await session.commit()

    @staticmethod
    async def find_deposit_by_order_or_guid(
        session: AsyncSession,
        merchant_order_id: Optional[str],
        guid: Optional[str],
    ) -> Optional[PaymentTransaction]:
        """
        Ищем транзакцию:
        1) по временному хранению merchant_order_id в plat_guid,
        2) либо по реальному guid, если уже перезаписали.
        """
        if merchant_order_id:
            tx = await session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.plat_guid == merchant_order_id)
            )
            if tx:
                return tx
        if guid:
            tx = await session.scalar(
                select(PaymentTransaction).where(PaymentTransaction.plat_guid == guid)
            )
            if tx:
                return tx
        return None

    @staticmethod
    async def finalize_successful_deposit(
        session: AsyncSession,
        tx: PaymentTransaction,
        real_guid: Optional[str],
        real_amount_rub: Optional[float] = None,
    ) -> float:
        """
        Помечаем транзакцию как POSTED и зачисляем на баланс 1:1.
        Если real_amount_rub передан и отличается — перезаписываем сумму.
        Возвращает актуальный баланс пользователя.
        """
        if tx.status == TxStatusEnum.POSTED:
            logger.warning(f"[DAO] tx {tx.id} already POSTED — skip")
            user = await session.get(User, tx.user_id)
            return float(user.balance if user else 0.0)

        user = await session.get(User, tx.user_id)
        if not user:
            raise ValueError(f"User for tx {tx.id} not found")

        if real_amount_rub is not None and float(real_amount_rub) != float(tx.amount):
            logger.debug(f"[DAO] overwrite tx.amount {tx.amount} -> {float(real_amount_rub)}")
            tx.amount = float(real_amount_rub)

        before = float(user.balance or 0)
        user.balance = before + float(tx.amount)
        tx.status = TxStatusEnum.POSTED
        if real_guid:
            tx.plat_guid = real_guid

        await session.commit()
        logger.info(
            f"[DAO] deposit posted tx_id={tx.id} credit={tx.amount} balance {before} -> {float(user.balance)}"
        )
        return float(user.balance)

    # --- GAME RESULT (оставил как было) ---

    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply_game_result(self, winner_id: int, loser_id: int, stake: int):
        winner = await self.session.scalar(select(User).where(User.tg_id == winner_id))
        loser = await self.session.scalar(select(User).where(User.tg_id == loser_id))
        if not winner or not loser:
            raise ValueError("Пользователь не найден")

        winner.balance += stake
        loser.balance -= stake

        win_tx = PaymentTransaction(
            user_id=winner.id,
            amount=stake,
            type=TxTypeEnum.PAYOUT,
            status=TxStatusEnum.POSTED,
            created_at=datetime.utcnow(),
        )
        lose_tx = PaymentTransaction(
            user_id=loser.id,
            amount=-stake,
            type=TxTypeEnum.LOSS,
            status=TxStatusEnum.POSTED,
            created_at=datetime.utcnow(),
        )
        win_result = GameResult(user_id=winner.id, result=GameResultEnum.WIN, rate=stake)
        lose_result = GameResult(user_id=loser.id, result=GameResultEnum.LOSS, rate=stake)

        self.session.add_all([win_tx, lose_tx, win_result, lose_result])
        await self.session.flush()
        await self.session.refresh(win_result)
        await self.session.refresh(lose_result)

        return {
            "winner_balance": float(winner.balance),
            "loser_balance": float(loser.balance),
            "winner_result": win_result.id,
            "loser_result": lose_result.id,
        }

    # --- READ methods (как у тебя) ---

    @classmethod
    async def get_user_transactions(cls, session: AsyncSession, tg_id: int) -> List[PaymentTransaction]:
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
        stmt = (
            select(
                func.count(PaymentTransaction.id).label("total_transactions"),
                func.sum(case((PaymentTransaction.type == TxTypeEnum.DEPOSIT, PaymentTransaction.amount), else_=0)).label("total_deposits"),
                func.sum(case((PaymentTransaction.type == TxTypeEnum.WITHDRAW, PaymentTransaction.amount), else_=0)).label("total_withdrawals"),
                func.sum(case((PaymentTransaction.type.in_([TxTypeEnum.PAYOUT, TxTypeEnum.REFERRAL_REWARD]), PaymentTransaction.amount), else_=0)).label("total_earned"),
                func.sum(case((PaymentTransaction.type.in_([TxTypeEnum.LOSS]), PaymentTransaction.amount), else_=0)).label("total_lost"),
                func.sum(PaymentTransaction.amount).label("net_flow"),
            )
            .join(User, PaymentTransaction.user_id == User.id)
            .where(User.tg_id == tg_id)
        )
        result = await session.execute(stmt)
        s = result.first()
        return {
            "total_transactions": s.total_transactions or 0,
            "total_deposits": float(s.total_deposits or 0),
            "total_withdrawals": float(s.total_withdrawals or 0),
            "total_earned": float(s.total_earned or 0),
            "total_lost": float(s.total_lost or 0),
            "net_flow": float(s.net_flow or 0),
        }


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