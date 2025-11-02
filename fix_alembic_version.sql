-- Исправление версии Alembic в базе данных
-- Если у вас записана несуществующая миграция 'fix_tg_id_fkeys',
-- нужно обновить таблицу alembic_version на последнюю реальную миграцию

-- Вариант 1: Если миграция a1b2c3d4e5f6 (add_loss_by_leave) еще не применена
-- Обновляем на последнюю существующую миграцию
UPDATE alembic_version SET version_num = '1fc2ef0eb454';

-- ИЛИ

-- Вариант 2: Если миграция a1b2c3d4e5f6 уже была применена
-- UPDATE alembic_version SET version_num = 'a1b2c3d4e5f6';

-- Проверка текущей версии
SELECT * FROM alembic_version;

