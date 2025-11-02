from typing import Dict, Any
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User
from app.payments.models import PaymentTransaction, TxTypeEnum, TxStatusEnum
from app.game.redis_dao.manager import get_redis


class StatsDAO:
    """DAO для получения статистики платформы"""

    @staticmethod
    async def get_platform_statistics(session: AsyncSession) -> Dict[str, Any]:
        """Получить общую статистику платформы"""
        redis = await get_redis()

        # 1. Количество пользователей
        total_users_query = select(func.count(User.id))
        result = await session.execute(total_users_query)
        total_users = result.scalar() or 0

        # 2. Подсчет онлайн игроков в комнатах Redis
        online_count = await StatsDAO._count_online_players(redis)

        # 3. Общий баланс всех пользователей
        total_balance_query = select(func.sum(User.balance))
        result = await session.execute(total_balance_query)
        total_balance = float(result.scalar() or 0)

        # 4. Статистика транзакций
        deposit_stats = await StatsDAO._get_transaction_stats(
            session, TxTypeEnum.DEPOSIT, TxStatusEnum.POSTED
        )
        withdraw_stats = await StatsDAO._get_transaction_stats(
            session, TxTypeEnum.WITHDRAW, TxStatusEnum.POSTED
        )

        return {
            "total_users": total_users,
            "online_users": online_count,
            "total_balance": total_balance,
            "total_deposits": deposit_stats["amount"],
            "deposits_count": deposit_stats["count"],
            "total_withdrawals": withdraw_stats["amount"],
            "withdrawals_count": withdraw_stats["count"],
            "net_profit": deposit_stats["amount"] - withdraw_stats["amount"],
        }

    @staticmethod
    async def _count_online_players(redis) -> int:
        """Подсчитать количество игроков онлайн в комнатах Redis"""
        try:
            # Получаем все ключи комнат (формат: "10_a535d472")
            all_keys = await redis.keys("*")
            if not all_keys:
                return 0

            online_players = set()
            values = await redis.mget(all_keys)

            for key, value in zip(all_keys, values):
                if value:
                    try:
                        import json
                        room_data = json.loads(value)
                        # Проверяем поле players
                        if "players" in room_data:
                            for player_id in room_data["players"].keys():
                                online_players.add(player_id)
                    except (json.JSONDecodeError, Exception):
                        continue

            return len(online_players)
        except Exception as e:
            print(f"Error counting online players: {e}")
            return 0

    @staticmethod
    async def _get_transaction_stats(
        session: AsyncSession, 
        tx_type: TxTypeEnum, 
        status: TxStatusEnum
    ) -> Dict[str, float]:
        """Получить статистику по типу и статусу транзакций"""
        query = select(
            func.count(PaymentTransaction.id).label('count'),
            func.sum(
                case((PaymentTransaction.type == tx_type, PaymentTransaction.amount), else_=0)
            ).label('amount')
        ).where(
            PaymentTransaction.type == tx_type,
            PaymentTransaction.status == status
        )

        result = await session.execute(query)
        row = result.first()

        return {
            "count": row.count or 0,
            "amount": float(row.amount or 0)
        }

