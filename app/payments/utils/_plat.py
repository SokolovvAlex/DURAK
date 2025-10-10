import asyncio
import hashlib
import time

import aiohttp

from app.config import settings

import asyncio


async def test_sign_with_delays():
    """Тестируем с задержками между запросами"""
    base_url = "https://1plat.cash"
    endpoint = "/api/merchant/order/sign/create/by-api"

    test_cases = [
        {"method": "alfa", "amount": 1000, "desc": "1000 руб - стандарт"},
        {"method": "alfa", "amount": 1500, "desc": "1500руб - нестандартная"},
        {"method": "alfa", "amount": 3000, "desc": "3000 руб СБП"},
        {"method": "alfa", "amount": 5000, "desc": "5000 руб СБП"},
    ]

    print("=== ТЕСТ С ЗАДЕРЖКАМИ ===")

    for i, test_case in enumerate(test_cases):
        if i > 0:
            print(f"⏳ Ждем 60 секунд...")
            await asyncio.sleep(60)  # ждем между запросами

        method = test_case["method"]
        amount = test_case["amount"]
        desc = test_case["desc"]

        try:
            merchant_order_id = f"delay_test_{method}_{amount}_{int(time.time())}"
            sign_string = f"{settings.PLAT_SHOP_ID}:{settings.PLAT_SECRET_KEY}:{amount}:{merchant_order_id}"
            sign = hashlib.md5(sign_string.encode()).hexdigest()

            payload = {
                "sign": sign,
                "merchant_order_id": merchant_order_id,
                "user_id": "1",
                "shop_id": settings.PLAT_SHOP_ID,
                "amount": str(amount),
                "method": method,
                "email": "test@temp.com"
            }

            print(f"\n🔧 {i + 1}/{len(test_cases)}: {desc}")
            print(f"   Method: {method}, Amount: {amount} rub")

            async with aiohttp.ClientSession() as session:
                async with session.post(
                        f"{base_url}{endpoint}",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        allow_redirects=False
                ) as response:

                    if response.status in [301, 302]:
                        redirect_url = response.headers.get('Location')
                        print(f"🎉 УСПЕХ! {desc}")
                        print(f"   Redirect: {redirect_url}")
                        return {
                            "method": method,
                            "amount": amount,
                            "redirect_url": redirect_url,
                            "description": desc
                        }
                    else:
                        try:
                            data = await response.json()
                            print(f"❌ ОШИБКА: {data.get('error', 'Unknown error')}")
                        except:
                            text = await response.text()
                            print(f"❌ ОШИБКА. Status: {response.status}")

        except Exception as e:
            print(f"⚠️ ИСКЛЮЧЕНИЕ: {e}")

    return None


# Запускаем тест с задержками
result = asyncio.run(test_sign_with_delays())