# test_withdraw.py
import asyncio
import os
import sys

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.payments.utils.plat_client import PlatClient
from app.config import settings


async def test_withdraw_methods():
    """Тестируем получение методов выплат"""
    print("=== ТЕСТИРУЕМ МЕТОДЫ ВЫВОДА ===")

    client = PlatClient(
        shop_id=settings.PLAT_SHOP_ID,
        secret_key=settings.PLAT_SECRET_KEY
    )

    try:
        methods = client.get_withdraw_methods()
        print("✅ Методы выплат получены:")
        print(f"Успех: {methods.get('success')}")

        if methods.get('methods'):
            print("\n📋 Доступные методы:")
            for method in methods['methods']:
                print(f"  ID: {method.get('id')}, Название: {method.get('name')}, Лейбл: {method.get('label')}")
                print(f"    Мин: {method.get('min')}, Макс: {method.get('max')}")
                print(f"    Комиссия: {method.get('commission_percent')}% + {method.get('commission_fix')} руб")
                print()

        if methods.get('banks'):
            print("🏦 Доступные банки:")
            for bank_id, bank_name in methods['banks'].items():
                print(f"  {bank_id}: {bank_name}")

    except Exception as e:
        print(f"❌ Ошибка: {e}")


async def test_create_withdraw():
    """Тестируем создание выплаты"""
    print("\n=== ТЕСТИРУЕМ СОЗДАНИЕ ВЫВОДА ===")

    client = PlatClient(
        shop_id=settings.PLAT_SHOP_ID,
        secret_key=settings.PLAT_SECRET_KEY
    )

    # Сначала получим методы
    try:
        methods = client.get_withdraw_methods()
        if not methods.get('methods'):
            print("❌ Нет доступных методов выплат")
            return

        # Берем первый доступный метод
        method = methods['methods'][0]
        print(f"Используем метод: {method['name']} (ID: {method['id']})")

        # Тестовые данные
        test_data = {
            "merchant_id": f"test_withdraw_{int(asyncio.get_event_loop().time())}",
            "amount": 100,  # Минимальная сумма
            "method_id": method['id'],
            "purse": "2200000000000000",  # Тестовый номер карты
            "bank": "Сбербанк",  # Если требуется для метода
            "commission_payment": True
        }

        print(f"Данные для выплаты: {test_data}")

        # Пробуем создать выплату
        result = client.create_withdraw(**test_data)
        print("✅ Выплата создана успешно!")
        print(f"Ответ: {result}")

    except Exception as e:
        print(f"❌ Ошибка создания выплаты: {e}")


async def test_shop_info():
    """Проверяем информацию о магазине"""
    print("\n=== ИНФОРМАЦИЯ О МАГАЗИНЕ ===")

    client = PlatClient(
        shop_id=settings.PLAT_SHOP_ID,
        secret_key=settings.PLAT_SECRET_KEY
    )

    try:
        # Используем существующий метод проверки подключения
        is_connected = client.check_connection()
        print(f"Подключение: {'✅ Успешно' if is_connected else '❌ Ошибка'}")

    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")


async def main():
    """Запускаем все тесты"""
    print("🔧 ТЕСТИРОВАНИЕ ВЫВОДА СРЕДСТВ PLAT")
    print(f"Shop ID: {settings.PLAT_SHOP_ID}")

    await test_shop_info()
    await test_withdraw_methods()
    await test_create_withdraw()


if __name__ == "__main__":
    asyncio.run(main())