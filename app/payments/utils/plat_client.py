import aiohttp
import hashlib
import hmac
import json
from typing import Tuple, Dict, Any


class PlatClient:
    BASE_URL = "https://1plat.cash/api/merchant"

    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key

    async def create_payment(
        self,
        merchant_order_id: str,
        user_id: int,
        amount: int,
        method: str = "card",
        email: str = None,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Создать платеж (Host2Host).
        Возвращает (guid, pay_url, payment_data).
        """
        url = f"{self.BASE_URL}/order/create/by-api"

        payload = {
            "merchant_order_id": str(merchant_order_id),
            "user_id": str(user_id),
            "amount": str(amount),
            "method": method,
            "email": email or f"{user_id}@temp.com",
        }

        headers = {
            "x-shop": str(self.shop_id),
            "x-secret": self.secret_key,
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                if not data.get("success"):
                    raise RuntimeError(f"PLAT error: {data}")
                return data["guid"], data["url"], data["payment"]

    def verify_callback(self, data: dict) -> bool:
        """
        Проверка callback от PLAT (по signature).
        """
        # Копия данных без сигнатур
        payload = {k: v for k, v in data.items() if k not in ("signature", "signature_v2")}

        # signature (HMAC SHA256)
        signature = data.get("signature")
        expected = hmac.new(
            self.secret_key.encode(),
            json.dumps(payload, separators=(",", ":")).encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature or "", expected)
