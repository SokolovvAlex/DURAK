# test_sbp_real_phone.py
import requests
import json
from datetime import datetime, timezone


def simple_withdraw_test_sbp_real():
    """Тест вывода через СБП с реальным номером телефона"""
    print("=== ТЕСТ ВЫВОДА ЧЕРЕЗ СБП (РЕАЛЬНЫЙ НОМЕР) ===")

    SHOP_ID = "825"
    SECRET_KEY = "1112222"
    BASE_URL = "https://1plat.cash"

    # Замените на реальный номер телефона
    REAL_PHONE = "+79785838651"  # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ НОМЕР

    timestamp = int(datetime.now(timezone.utc).timestamp())
    merchant_id = f"real_sbp_{timestamp}"

    payload = {
        "amount": 100.0,
        "method_id": 2,  # sbp
        "merchant_id": merchant_id,
        "purse": REAL_PHONE,
        "bank": "Сбербанк",
        "commission_payment": True
    }

    endpoint = "/api/merchant/withdraw/shop/create/by-api"
    url = f"{BASE_URL}{endpoint}"

    headers = {
        "x-shop": SHOP_ID,
        "x-secret": SECRET_KEY,
        "Content-Type": "application/json",
    }

    print(f"🔄 Отправка запроса вывода на реальный номер...")
    print(f"   Сумма: {payload['amount']} руб")
    print(f"   Метод: СБП")
    print(f"   Телефон: {payload['purse']}")
    print(f"   Банк: {payload['bank']}")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        print(f"📥 Ответ: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print("✅ Ответ:")
            print(json.dumps(data, indent=2, ensure_ascii=False))

            if data.get("success"):
                print(f"\n🎯 Вывод создан! ID: {data['withdraw']['id']}")
            else:
                print("❌ Ошибка в ответе")
        else:
            print(f"📝 Response Text: {response.text}")
            try:
                error_data = response.json()
                print(f"❌ Ошибка: {error_data.get('error', 'Unknown error')}")
            except:
                print(f"❌ Ошибка: {response.text}")

    except Exception as e:
        print(f"💥 Исключение: {e}")


if __name__ == "__main__":
    simple_withdraw_test_sbp_real()