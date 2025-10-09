import logging

import aiohttp
import hashlib
import hmac
import json
from typing import Tuple, Dict, Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class PlatClient:
    BASE_URL = "https://1plat.cash/api/merchant"

    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key
        logger.info(f"PlatClient initialized with shop_id: {shop_id}")

    def generate_sign(self, amount: int, merchant_order_id: str) -> str:
        """
        Генерация подписи для метода с sign
        Формат: md5(shopId + ':' + secret + ':' + amount + ':' + merchantOrderId)
        """
        sign_string = f"{self.shop_id}:{self.secret_key}:{amount}:{merchant_order_id}"
        sign = hashlib.md5(sign_string.encode()).hexdigest()
        logger.debug(f"Generated sign for order {merchant_order_id}: {sign}")
        return sign

    async def create_payment_with_sign(
            self,
            merchant_order_id: str,
            user_id: int,
            amount: int,
            method: str = "alfa"
    ) -> str:
        """
        Создание платежа через метод с sign (Redirect approach)
        Возвращает URL для редиректа на форму оплаты
        """
        url = f"{self.BASE_URL}/order/sign/create/by-api"

        # Генерируем подпись
        sign = self.generate_sign(amount, merchant_order_id)

        payload = {
            "sign": sign,
            "merchant_order_id": merchant_order_id,
            "user_id": str(user_id),
            "shop_id": self.shop_id,
            "amount": str(amount),
            "method": method,
            "email": f"{user_id}@temp.com"
        }

        logger.info(
            f"Creating payment with sign: order_id={merchant_order_id}, user_id={user_id}, amount={amount}, method={method}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        allow_redirects=False  # важно для редиректа!
                ) as resp:

                    if resp.status in [301, 302]:
                        redirect_url = resp.headers.get('Location')
                        if redirect_url:
                            logger.info(f"Payment created successfully with sign, redirect to: {redirect_url}")
                            return redirect_url
                        else:
                            raise RuntimeError("No redirect URL in response")
                    else:
                        # Если нет редиректа, пробуем получить JSON ответ
                        try:
                            data = await resp.json()
                            error_msg = f"PLAT sign error: {data}"
                            logger.error(error_msg)
                            raise RuntimeError(error_msg)
                        except:
                            text = await resp.text()
                            raise RuntimeError(f"PLAT sign error. Status: {resp.status}, Response: {text}")

        except Exception as e:
            logger.error(f"Payment creation with sign failed: {e}")
            raise

    # Остальные ваши методы остаются без изменений:
    async def check_connection(self) -> bool:
        """Проверка подключения к Plat API"""
        try:
            url = f"{self.BASE_URL}/shop/info/by-api"
            headers = {
                "x-shop": str(self.shop_id),
                "x-secret": self.secret_key,
            }

            logger.debug(f"Checking Plat connection to {url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"Plat connection successful. Shop: {data.get('shop', {}).get('name')}")
                        return True
                    else:
                        logger.error(f"Plat connection failed. Status: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Plat connection check error: {e}")
            return False

    async def create_payment(
            self,
            merchant_order_id: str,
            user_id: int,
            amount: int,
            method: str = "card",
            email: str = None,
            currency: str = "RUB"
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Создать платеж (Host2Host) с логированием
        """
        url = f"{self.BASE_URL}/order/create/by-api"

        payload = {
            "merchant_order_id": str(merchant_order_id),
            "user_id": str(user_id),
            "amount": str(amount),
            "method": method,
            "email": email or f"{user_id}@temp.com",
            "currency": currency if method == "crypto" else "RUB"
        }

        headers = {
            "x-shop": str(self.shop_id),
            "x-secret": self.secret_key,
            "Content-Type": "application/json",
        }

        logger.info(
            f"Creating payment: order_id={merchant_order_id}, user_id={user_id}, amount={amount}, method={method}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    logger.debug(f"Plat API response: {data}")

                    if not data.get("success"):
                        error_msg = f"PLAT error: {data}"
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)

                    logger.info(f"Payment created successfully: guid={data['guid']}")
                    return data["guid"], data["url"], data["payment"]

        except Exception as e:
            logger.error(f"Payment creation failed: {e}")
            raise

    async def get_payment_info(self, guid: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о платеже по GUID"""
        url = f"{self.BASE_URL}/order/info/{guid}/by-api"
        headers = {
            "x-shop": str(self.shop_id),
            "x-secret": self.secret_key,
        }

        logger.debug(f"Getting payment info for guid: {guid}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            logger.debug(f"Payment info retrieved: status={data.get('payment', {}).get('status')}")
                            return data
                        else:
                            logger.warning(f"Payment info not found for guid: {guid}")
                            return None
                    else:
                        logger.error(f"Failed to get payment info. Status: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting payment info: {e}")
            return None

    def verify_callback(self, data: dict) -> bool:
        """
        Проверка callback от PLAT (по signature_v2 - MD5 вариант)
        """
        try:
            # Копия данных без сигнатур
            payload = {k: v for k, v in data.items() if k not in ("signature", "signature_v2")}

            # Используем signature_v2 (MD5) как в документации
            merchant_id = str(data.get('merchant_id', ''))
            amount = str(data.get('amount', ''))
            shop_id = str(self.shop_id)

            signature_v2 = data.get("signature_v2", "")

            expected = hashlib.md5(
                f"{merchant_id}{amount}{shop_id}{self.secret_key}".encode()
            ).hexdigest()

            is_valid = hmac.compare_digest(signature_v2, expected)

            if is_valid:
                logger.info("Callback signature verified successfully")
            else:
                logger.warning("Callback signature verification failed")

            return is_valid

        except Exception as e:
            logger.error(f"Callback verification error: {e}")
            return False


class PlatService:
    """
    Облегчённый сервис под redirect/sign.
    """
    BASE_URL = "https://1plat.cash"
    ENDPOINT_SIGN = "/api/merchant/order/sign/create/by-api"
    ENDPOINT_SHOP_INFO = "/api/shop/info/by-api"

    @staticmethod
    def generate_sign(amount_rub: int, merchant_order_id: str) -> str:
        """
        md5(shopId:secret:amount:merchantOrderId)
        amount — В РУБЛЯХ (не копейках).
        """
        sign_string = f"{settings.PLAT_SHOP_ID}:{settings.PLAT_SECRET_KEY}:{amount_rub}:{merchant_order_id}"
        return hashlib.md5(sign_string.encode()).hexdigest()

    @classmethod
    async def create_payment_with_sign(cls, merchant_order_id: str, user_id: int, amount_rub: int, method: str = "alfa") -> str:
        """
        Возвращает redirect URL для оплаты.
        """
        url = f"{cls.BASE_URL}{cls.ENDPOINT_SIGN}"
        payload = {
            "sign": cls.generate_sign(amount_rub, merchant_order_id),
            "merchant_order_id": merchant_order_id,
            "user_id": str(user_id),
            "shop_id": settings.PLAT_SHOP_ID,
            "amount": str(amount_rub),
            "method": method,
            "email": f"{user_id}@temp.com",
        }
        logger.info(f"[PLAT] create_payment_with_sign order_id={merchant_order_id} amount={amount_rub} method={method}")

        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload, headers={"Content-Type": "application/json"}, allow_redirects=False) as r:
                if r.status in (301, 302):
                    redirect = r.headers.get("Location")
                    if not redirect:
                        raise RuntimeError("Empty redirect from PLAT")
                    logger.info(f"[PLAT] redirect={redirect}")
                    return redirect
                try:
                    data = await r.json()
                except Exception:
                    data = {"raw": await r.text()}
                logger.error(f"[PLAT] sign create error status={r.status} data={data}")
                raise RuntimeError(f"PLAT sign error: {data}")

    @classmethod
    async def check_connection(cls) -> Dict:
        url = f"{cls.BASE_URL}{cls.ENDPOINT_SHOP_INFO}"
        headers = {
            "x-shop": settings.PLAT_SHOP_ID,
            "x-secret": settings.PLAT_SECRET_KEY,
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers) as r:
                try:
                    data = await r.json()
                except Exception:
                    data = {"raw": await r.text()}
                logger.info(f"[PLAT] shop_info status={r.status} data={data}")
                return {"status": r.status, "data": data}

    @staticmethod
    def verify_callback_md5_v2(payload: dict) -> bool:
        """
        signature_v2 = md5(merchant_id + amount + shop_id + secret)
        amount — в РУБЛЯХ.
        """
        merchant_id = str(payload.get("merchant_id", ""))
        amount = str(payload.get("amount", ""))
        shop_id = str(settings.PLAT_SHOP_ID)
        sign = str(payload.get("signature_v2", ""))

        expected = hashlib.md5(f"{merchant_id}{amount}{shop_id}{settings.PLAT_SECRET_KEY}".encode()).hexdigest()
        ok = sign == expected
        if not ok:
            logger.warning(f"[PLAT] callback signature mismatch expected={expected} got={sign} payload={payload}")
        return ok