import aiohttp
import hashlib
import hmac
import time
from typing import Tuple


class PlatClient:
    BASE_URL = "https://1plat.cash/api"

    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key

    def _sign(self, payload: dict) -> str:
        """
        Подпись = HMAC_SHA256(secret_key, sorted(key=value...))
        """
        items = [f"{k}={payload[k]}" for k in sorted(payload)]
        check_string = "&".join(items)
        return hmac.new(
            self.secret_key.encode(), check_string.encode(), hashlib.sha256
        ).hexdigest()

    async def create_payment(self, amount: float, tx_id: int) -> Tuple[str, str]:
        """
        Создать пополнение
        :returns (plat_payment_id, pay_url)
        """
        url = f"{self.BASE_URL}/payment"
        payload = {
            "shop_id": self.shop_id,
            "amount": str(amount),
            "order_id": str(tx_id),   # наш внутренний id транзакции
            "time": int(time.time()),
        }
        payload["sign"] = self._sign(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data["status"] != "ok":
                    raise RuntimeError(f"PLAT error: {data}")
                return data["payment_id"], data["pay_url"]

    async def create_payout(self, amount: float, tx_id: int, card: str) -> str:
        """
        Создать выплату (вывод)
        :returns plat_payout_id
        """
        url = f"{self.BASE_URL}/payout"
        payload = {
            "shop_id": self.shop_id,
            "amount": str(amount),
            "order_id": str(tx_id),
            "card": card,
            "time": int(time.time()),
        }
        payload["sign"] = self._sign(payload)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data["status"] != "ok":
                    raise RuntimeError(f"PLAT error: {data}")
                return data["payout_id"]

    def verify_callback(self, data: dict) -> bool:
        """
        Проверка подписи webhook-а от PLAT
        """
        sign = data.pop("sign", None)
        expected = self._sign(data)
        return hmac.compare_digest(sign, expected)