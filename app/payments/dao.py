import logging
from datetime import datetime
from operator import or_
from typing import List, Optional

from sqlalchemy import select, func, case, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.game.models import GameResult, GameResultEnum
from app.payments.models import PaymentTransaction, TxTypeEnum, TxStatusEnum
from app.users.models import User

logger = logging.getLogger(__name__)


class PaymentTransactionDAO:
    """
    Data Access Object для работы с платежными транзакциями
    """

    @staticmethod
    async def create_deposit_transaction(
            session: AsyncSession,
            user_id: int,
            amount_rub: float,
            merchant_order_id: str
    ) -> int:
        """
        Создает транзакцию депозита со статусом PENDING
        Возвращает ID созданной транзакции
        """
        logger.info(f"Creating deposit transaction: user_id={user_id}, amount={amount_rub}")

        # Проверяем существование пользователя
        user = await session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Создаем транзакцию
        tx = PaymentTransaction(
            user_id=user_id,
            type=TxTypeEnum.DEPOSIT,
            amount=amount_rub,
            status=TxStatusEnum.PENDING,
            merchant_order_id=merchant_order_id,  # сохраняем merchant_order_id
            plat_guid=None,  # будет заполнен позже из callback
            created_at=datetime.utcnow(),
        )

        session.add(tx)
        await session.flush()  # Получаем ID без коммита
        tx_id = tx.id

        logger.info(f"Deposit transaction created: id={tx_id}, order_id={merchant_order_id}")
        return tx_id

    @staticmethod
    async def process_successful_deposit(
            session: AsyncSession,
            merchant_order_id: str,
            plat_guid: str,
            amount_rub: float
    ) -> bool:
        """
        Обрабатывает успешный депозит:
        - Находит транзакцию по merchant_order_id
        - Начисляет средства пользователю
        - Обновляет статус и plat_guid
        """
        logger.info(f"Processing successful deposit: order_id={merchant_order_id}, amount={amount_rub}")

        # Ищем транзакцию по merchant_order_id
        tx = await session.scalar(
            select(PaymentTransaction).where(PaymentTransaction.merchant_order_id  == merchant_order_id)
        )

        if not tx:
            logger.error(f"Transaction not found for order_id: {merchant_order_id}")
            return False

        if tx.status == TxStatusEnum.POSTED:
            logger.warning(f"Transaction already processed: {tx.id}")
            return True

        # Находим пользователя
        user = await session.scalar(select(User).where(User.id == tx.user_id))
        if not user:
            logger.error(f"User not found for transaction: {tx.id}")
            return False

        # Начисляем средства 1:1 - конвертируем в Decimal
        from decimal import Decimal
        old_balance = user.balance
        user.balance += Decimal(str(amount_rub))  # Конвертируем float в Decimal

        # Обновляем статус и plat_guid
        tx.status = TxStatusEnum.POSTED
        tx.plat_guid = plat_guid  # заменяем на реальный GUID от Plat

        logger.info(f"Deposit processed successfully: user_id={user.id}, balance: {old_balance} -> {user.balance}")
        return True

    @staticmethod
    async def get_transaction_by_id(
            session: AsyncSession,
            tx_id: int
    ) -> Optional[PaymentTransaction]:
        """Получает транзакцию по ID"""
        return await session.scalar(select(PaymentTransaction).where(PaymentTransaction.id == tx_id))

    @staticmethod
    async def get_user_transactions(
            session: AsyncSession,
            user_id: int
    ) -> List[PaymentTransaction]:
        """Получает все транзакции пользователя"""
        stmt = (
            select(PaymentTransaction)
            .where(PaymentTransaction.user_id == user_id)
            .order_by(PaymentTransaction.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def create_withdraw_transaction(
            session: AsyncSession,
            user_id: int,
            amount_rub: float,
            method_id: int,
            purse: str,
            bank_id: Optional[str] = None
    ) -> tuple[int, str]:
        """
        Создает транзакцию вывода и резервирует средства
        Возвращает (tx_id, merchant_id)
        """
        logger.info(f"Creating withdraw transaction: user_id={user_id}, amount={amount_rub}")

        # Проверяем пользователя и баланс
        user = await session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Проверяем достаточно ли средств
        from decimal import Decimal
        if user.balance < Decimal(str(amount_rub)):
            raise ValueError("Insufficient funds")

        # Резервируем средства (списываем с баланса)
        user.balance -= Decimal(str(amount_rub))

        # Генерируем merchant_id
        timestamp = int(datetime.utcnow().timestamp())
        merchant_id = f"withdraw_{user_id}_{timestamp}"

        # Создаем транзакцию
        tx = PaymentTransaction(
            user_id=user_id,
            type=TxTypeEnum.WITHDRAW,
            amount=-amount_rub,
            status=TxStatusEnum.PENDING,
            merchant_order_id=merchant_id,  # сохраняем как merchant_order_id для поиска
            plat_withdraw_id=None,  # будет заполнен из ответа Plat
            created_at=datetime.utcnow(),
        )

        session.add(tx)
        await session.flush()
        tx_id = tx.id

        logger.info(f"Withdraw transaction created: id={tx_id}, merchant_id={merchant_id}")
        return tx_id, merchant_id

    @staticmethod
    async def process_withdraw_callback(
            session: AsyncSession,
            merchant_id: str,
            plat_withdraw_id: str,
            status: int
    ) -> bool:
        """
        Обрабатывает callback выплаты от Plat по merchant_id
        Проверяет что транзакция в статусе PENDING
        """
        logger.info(f"Processing withdraw callback: merchant_id={merchant_id}, status={status}")

        # Ищем транзакцию по merchant_order_id (это наш merchant_id)
        tx = await session.scalar(
            select(PaymentTransaction).where(PaymentTransaction.merchant_order_id == merchant_id)
        )

        if not tx:
            logger.error(f"Withdraw transaction not found: {merchant_id}")
            return False

        # ПРОВЕРКА СТАТУСА: если транзакция уже не в PENDING - игнорируем
        if tx.status != TxStatusEnum.PENDING:
            logger.warning(
                f"Withdraw transaction already processed: id={tx.id}, "
                f"current_status={tx.status}, requested_status={status}. Ignoring callback."
            )
            return True  # Возвращаем True, но ничего не меняем

        # Находим пользователя
        user = await session.scalar(select(User).where(User.id == tx.user_id))
        if not user:
            logger.error(f"User not found for transaction: {tx.id}")
            return False

        # Обновляем plat_withdraw_id если его еще нет
        if not tx.plat_withdraw_id:
            tx.plat_withdraw_id = plat_withdraw_id

        # Обрабатываем статусы Plat
        if status == 2:  # успешно выполнен
            tx.status = TxStatusEnum.POSTED
            logger.info(f"Withdraw completed successfully: {tx.id}")

        elif status in [-3, -2, -1]:  # отменен
            tx.status = TxStatusEnum.FAILED
            # Возвращаем средства на баланс
            from decimal import Decimal
            user.balance += Decimal(str(abs(tx.amount)))
            logger.info(f"Withdraw cancelled, funds returned: {tx.id}")

        elif status in [0, 1]:  # в ожидании/процессе
            logger.info(f"Withdraw still processing: {tx.id}")
            return True  # ничего не меняем

        logger.info(f"Withdraw status updated: tx_id={tx.id}, old_status=PENDING, new_status={tx.status}")
        return True

    @staticmethod
    async def reserve_funds_for_withdraw(
            session: AsyncSession,
            user_id: int,
            amount_rub: float
    ) -> bool:
        """
        Резервирует средства для вывода (списывает с баланса)
        """
        user = await session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise ValueError(f"User {user_id} not found")

        from decimal import Decimal
        if user.balance < Decimal(str(amount_rub)):
            raise ValueError("Insufficient funds")

        # Списываем средства
        user.balance -= Decimal(str(amount_rub))
        logger.info(f"Funds reserved: user_id={user_id}, amount={amount_rub}")
        return True


class TransactionDAO:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply_game_result(self, winner_id: int, loser_id: int, stake: int, is_leaver: bool = False):
        """
        Начисляет выигрыш победителю и списывает у проигравшего.
        Создаёт:
          • PaymentTransaction (для истории пополнений/списаний)
          • GameResult (для истории игр)
        Args:
            is_leaver: Если True, то проигравший ливнул из игры (используется LOSS_BY_LEAVE)
        """
        # --- Получаем пользователей ---
        winner = await self.session.scalar(select(User).where(User.tg_id == winner_id))
        loser = await self.session.scalar(select(User).where(User.tg_id == loser_id))

        if not winner or not loser:
            raise ValueError("Пользователь не найден")

        # --- Обновляем балансы ---
        # Победитель получает только ставку проигравшего
        winner.balance += stake
        # Проигравший теряет свою ставку
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
            result=GameResultEnum.LOSS_BY_LEAVE if is_leaver else GameResultEnum.LOSS,
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

    async def apply_game_result_multiplayer(
        self, 
        winner_id: int, 
        loser_ids: list[int], 
        stake: int
    ):
        """
        Обрабатывает результат игры с несколькими проигравшими.
        Победитель получает только ставки проигравших (не свою ставку).
        Проигравшие теряют свою ставку.
        """
        from decimal import Decimal
        
        # Получаем всех пользователей
        winner = await self.session.scalar(select(User).where(User.tg_id == winner_id))
        if not winner:
            raise ValueError(f"Победитель {winner_id} не найден")
        
        # Общая сумма, которую получит победитель
        # Победитель получает только ставки проигравших (не свою)
        total_pot = stake * len(loser_ids)
        
        # Начисляем победителю сумму ставок проигравших (без рейка пока)
        winner.balance += Decimal(str(total_pot))
        
        # Списываем у проигравших
        transactions = []
        game_results = []
        
        for loser_id in loser_ids:
            loser = await self.session.scalar(select(User).where(User.tg_id == loser_id))
            if not loser:
                continue
            
            # Проигравший теряет свою ставку
            loser.balance -= Decimal(str(stake))
            
            lose_tx = PaymentTransaction(
                user_id=loser.id,
                amount=-stake,
                type=TxTypeEnum.LOSS,
                status=TxStatusEnum.POSTED,
                created_at=datetime.utcnow()
            )
            lose_result = GameResult(
                user_id=loser.id,
                result=GameResultEnum.LOSS,
                rate=stake,
            )
            transactions.append(lose_tx)
            game_results.append(lose_result)
        
        # Транзакция и результат для победителя
        win_tx = PaymentTransaction(
            user_id=winner.id,
            amount=total_pot,
            type=TxTypeEnum.PAYOUT,
            status=TxStatusEnum.POSTED,
            created_at=datetime.utcnow()
        )
        win_result = GameResult(
            user_id=winner.id,
            result=GameResultEnum.WIN,
            rate=total_pot,
        )
        
        self.session.add_all([win_tx, win_result] + transactions + game_results)
        await self.session.flush()
        
        return {
            "winner_balance": float(winner.balance),
            "losers_balance": {lid: loser_id for lid in loser_ids},
        }
    
    async def apply_game_result_leave(self, leaver_id: int, stake: int):
        """
        Записывает результат лива игрока из игры.
        Создаёт запись GameResult с LOSS_BY_LEAVE для статистики.
        Деньги не списываются (списываются в apply_game_result при завершении игры).
        """
        # Получаем пользователя
        leaver = await self.session.scalar(select(User).where(User.tg_id == leaver_id))
        if not leaver:
            raise ValueError(f"Игрок {leaver_id} не найден")
        
        # Создаём запись в GameResult для статистики
        leave_result = GameResult(
            user_id=leaver.id,
            result=GameResultEnum.LOSS_BY_LEAVE,
            rate=stake,
        )
        
        self.session.add(leave_result)
        await self.session.flush()
        
        return {
            "leaver_result": leave_result.id,
        }

    @classmethod
    async def get_user_transactions(cls, session: AsyncSession, tg_id: int) -> List[PaymentTransaction]:
        """Получить все транзакции пользователя по tg_id"""
        stmt = (
            select(PaymentTransaction)
            .join(User, PaymentTransaction.user_id == User.id)
            .where(
                User.tg_id == tg_id,
                # Для транзакций DEPOSIT и WITHDRAW показываем только POSTED
                # Для остальных типов транзакций показываем все статусы
                or_(
                    and_(
                        PaymentTransaction.type.in_([TxTypeEnum.DEPOSIT, TxTypeEnum.WITHDRAW]),
                        PaymentTransaction.status == TxStatusEnum.POSTED
                    ),
                    PaymentTransaction.type.not_in([TxTypeEnum.DEPOSIT, TxTypeEnum.WITHDRAW])
                )
            )
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