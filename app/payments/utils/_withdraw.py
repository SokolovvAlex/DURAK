# test_sbp_real_phone.py
import requests
import json
from datetime import datetime, timezone

from app.config import settings
from app.payments.dao import logger


def simple_withdraw_test_sbp_real():
    """Тест вывода через СБП с реальным номером телефона"""
    print("=== ТЕСТ ВЫВОДА ЧЕРЕЗ СБП (РЕАЛЬНЫЙ НОМЕР) ===")

    SHOP_ID = "918"
    SECRET_KEY = "ROS5FVN5PXKOJT07RFUNINI2E3M0TII3"
    BASE_URL = "https://1plat.cash"

    # Замените на реальный номер телефона
    REAL_PHONE = "+79785838651"  # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ НОМЕР

    timestamp = int(datetime.now(timezone.utc).timestamp())
    merchant_id = f"real_sbp_{timestamp}"

    payload = {
        "amount": 1000.0,
        "method_id": 10,  # sbp
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

    BASE_URL = "https://1plat.cash"

    endpoint = "/api/merchant/withdraws/methods/by-api"
    url = f"{BASE_URL}{endpoint}"

    SHOP_ID = "825"
    SECRET_KEY = "1112222"

    headers = {
        "x-shop": SHOP_ID,
        "x-secret": SECRET_KEY,
    }

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        data = response.json()
        print(data)
        logger.info(f"Withdraw methods response: {data}")


"""

{
  "success": 1,
  "withdraw": {
    "note": {
      "bank": "Сбербанк"
    },
    "meta": {},
    "files": [],
    "cb_id": 0,
    "success_cb": false,
    "msg_id": 15767,
    "long_wait": 0,
    "id": 14233,
    "status": 1,
    "user_id": 1513,
    "method_id": 10,
    "provider_id": 47927,
    "shop_id": 825,
    "merchant_id": "real_sbp_1760552007",
    "amount": "1000.00",
    "amount_to_pay": 930,
    "method_name": "Sbp#1",
    "method_purse": "+79785838651",
    "count": 1,
    "updatedAt": "2025-10-15T18:13:29.178Z",
    "createdAt": "2025-10-15T18:13:28.847Z"
  }
}

{'success': 1, 'methods': [{'id': 6, 'name': 'USDTTRC20', 'label': 'USDT TRC20', 'regex': '^T[a-zA-Z0-9]{33}$', 'min': 1000, 'max': 50000000, 'commission_fix': 350, 'commission_percent': 2, 'commission_cascade_fix': 0, 'commission_cascade_percent': 0, 'available_private': False, 'WithdrawCommissions': []}, {'id': 9, 'name': 'card#1', 'label': 'Card#1', 'regex': '', 'min': 500, 'max': 500000, 'commission_fix': 0, 'commission_percent': 7, 'commission_cascade_fix': 0, 'commission_cascade_percent': 2, 'available_private': True, 'WithdrawCommissions': []}, {'id': 10, 'name': 'sbp#1', 'label': 'Sbp#1', 'regex': '', 'min': 500, 'max': 500000, 'commission_fix': 0, 'commission_percent': 7, 'commission_cascade_fix': 0, 'commission_cascade_percent': 2, 'available_private': True, 'WithdrawCommissions': []}], 'banks': {'100000000111': 'Сбербанк', '100000000012': 'Росбанк', '100000000100': 'Т-банк', '100000000007': 'Райффайзен', '100000000008': 'АЛЬФА-БАНК', '100000000041': 'БКС Банк', '999999999999': 'ЮМаней', '100000000010': 'ВТБ Банк', '100000000273': 'Озон Банк (Ozon)'}}

"""