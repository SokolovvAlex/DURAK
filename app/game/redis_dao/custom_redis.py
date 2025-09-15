import json
from redis.asyncio import Redis
from loguru import logger
from typing import Any, Callable, Awaitable, Dict, List


class CustomRedis(Redis):
    """Расширенный класс Redis с дополнительными методами"""

    async def delete_key(self, key: str):
        """Удаляет ключ из Redis."""
        await self.delete(key)
        logger.info(f"Ключ {key} удален")

    async def delete_keys_by_prefix(self, prefix: str):
        """Удаляет ключи, начинающиеся с указанного префикса."""
        keys = await self.keys(prefix + '*')
        if keys:
            await self.delete(*keys)
            logger.info(f"Удалены ключи, начинающиеся с {prefix}")

    async def delete_all_keys(self):
        """Удаляет все ключи из текущей базы данных Redis."""
        await self.flushdb()
        logger.info("Удалены все ключи из текущей базы данных")

    async def get_value(self, key: str):
        """Возвращает значение ключа из Redis."""
        value = await self.get(key)
        if value:
            return value
        else:
            logger.info(f"Ключ {key} не найден")
            return None

    async def set_value(self, key: str, value: str):
        """Устанавливает значение ключа в Redis."""
        await self.set(key, value)
        logger.info(f"Установлено значение ключа {key}")

    async def set_value_with_ttl(self, key: str, value: str, ttl: int):
        """Устанавливает значение ключа с временем жизни в Redis."""
        await self.setex(key, ttl, value)
        logger.info(f"Установлено значение ключа {key} с TTL {ttl}")

    async def exists(self, key: str) -> bool:
        """Проверяет, существует ли ключ в Redis."""
        return await super().exists(key)

    async def get_keys(self, pattern: str = '*'):
        """Возвращает список ключей, соответствующих шаблону."""
        return await self.keys(pattern)

    async def get_cached_data(
        self,
        cache_key: str,
        fetch_data_func: Callable[..., Awaitable[Any]],
        *args,
        ttl: int = 1800,
        **kwargs
    ) -> Any:
        """
        Получает данные из кэша Redis или из БД, если их нет в кэше.

        Args:
            cache_key: Ключ для кэширования данных
            fetch_data_func: Асинхронная функция для получения данных из БД
            *args: Позиционные аргументы для fetch_data_func
            ttl: Время жизни кэша в секундах (по умолчанию 30 минут)
            **kwargs: Именованные аргументы для fetch_data_func

        Returns:
            Данные из кэша или из БД
        """
        cached_data = await self.get(cache_key)

        if cached_data:
            logger.info(f"Данные получены из кэша для ключа: {cache_key}")
            return json.loads(cached_data)
        else:
            logger.info(f"Данные не найдены в кэше для ключа: {cache_key}, получаем из источника")
            data = await fetch_data_func(*args, **kwargs)

            # Преобразуем данные в зависимости от их типа
            if isinstance(data, list):
                processed_data = [
                    item.to_dict() if hasattr(item, 'to_dict') else item 
                    for item in data
                ]
            else:
                processed_data = data.to_dict() if hasattr(data, 'to_dict') else data

            # Сохраняем данные в кэше с указанным временем жизни
            await self.setex(cache_key, ttl, json.dumps(processed_data))
            logger.info(f"Данные сохранены в кэш для ключа: {cache_key} с TTL: {ttl} сек")

            return processed_data


    async def get_rooms_by_bet(self, bet: int) -> List[Dict[str, Any]]:
        """
        Возвращает список комнат, чьи ключи начинаются со строки '{bet}_'.
        Предполагается, что каждая комната хранится под ключом = её id (например, '10_a535d472')
        и значение — JSON-строка с полями комнаты.
        Если у тебя комнаты хранятся НЕ как JSON-строка, см. комментарий внутри.
        """
        pattern = f"{bet}_*"
        rooms: List[Dict[str, Any]] = []

        async for raw_key in self.scan_iter(match=pattern, count=1000):
            key = raw_key.decode() if isinstance(raw_key, (bytes, bytearray)) else raw_key
            try:
                raw = await self.get(key)  # <-- если у тебя Hash, замени на: data = await self.hgetall(key) + декод
                if raw is None:
                    continue

                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode()

                data: Dict[str, Any]
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    # если хранится как Hash, раскомментируй этот блок и закомментируй GET/JSON выше:
                    # raw_hash = await self.hgetall(key)
                    # data = {
                    #     (k.decode() if isinstance(k, (bytes, bytearray)) else k):
                    #     (v.decode() if isinstance(v, (bytes, bytearray)) else v)
                    #     for k, v in raw_hash.items()
                    # }
                    # или, если хранится как строка — оборачиваем как есть:
                    data = {"value": raw}

                # добавим id ключа для удобства
                data.setdefault("id", key)
                rooms.append(data)

            except Exception as e:
                logger.warning("Не удалось прочитать комнату %s: %s", key, e)

        return rooms