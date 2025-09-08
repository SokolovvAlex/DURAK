from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.payments.models import PaymentTransaction

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