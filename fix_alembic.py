"""
Скрипт для исправления версии Alembic в базе данных.
Если в БД записана несуществующая миграция, обновляем на последнюю реальную.
"""
import asyncio
from sqlalchemy import text
from app.database import async_session_maker


async def fix_alembic_version():
    """Обновляет версию Alembic в БД на последнюю реальную миграцию."""
    async with async_session_maker() as session:
        # Проверяем текущую версию
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        current_version = result.scalar()
        print(f"Текущая версия в БД: {current_version}")
        
        # Последняя реальная миграция (до add_loss_by_leave)
        last_real_version = "1fc2ef0eb454"
        
        # Если версия не совпадает с реальной, обновляем
        if current_version != last_real_version:
            print(f"Обновляем версию на: {last_real_version}")
            await session.execute(
                text("UPDATE alembic_version SET version_num = :version"),
                {"version": last_real_version}
            )
            await session.commit()
            print("Версия обновлена успешно!")
        else:
            print("Версия уже корректна!")
        
        # Проверяем результат
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        new_version = result.scalar()
        print(f"Новая версия в БД: {new_version}")


if __name__ == "__main__":
    asyncio.run(fix_alembic_version())

