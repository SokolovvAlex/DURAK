import aiohttp
import hashlib
import logging
from typing import Dict, Any, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class PlatClient:
    """
    СИНХРОННЫЙ клиент для работы с Plat API
    Решает проблему конфликта асинхронности
    """

    BASE_URL = "https://1plat.cash"

    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key
        logger.info(f"PlatClient initialized for shop: {shop_id}")

    def _generate_sign(self, amount: int, merchant_order_id: str) -> str:
        """
        Генерация подписи для API с sign
        Формат: md5(shopId + ':' + secret + ':' + amount + ':' + merchantOrderId)
        """
        sign_string = f"{self.shop_id}:{self.secret_key}:{amount}:{merchant_order_id}"
        return hashlib.md5(sign_string.encode()).hexdigest()

    def create_payment(
            self,
            merchant_order_id: str,
            user_id: int,
            amount: int,  # в рублях
            method: str = "alfa"
    ) -> str:
        """
        СИНХРОННОЕ создание платежа через метод с sign
        Возвращает URL для редиректа на оплату
        """
        endpoint = "/api/merchant/order/sign/create/by-api"
        url = f"{self.BASE_URL}{endpoint}"

        sign = self._generate_sign(amount, merchant_order_id)

        payload = {
            "sign": sign,
            "merchant_order_id": merchant_order_id,
            "user_id": str(user_id),
            "shop_id": self.shop_id,
            "amount": str(amount),  # в рублях
            "method": method,
            "email": f"{user_id}@temp.com",
        }

        logger.info(f"Creating Plat payment: order_id={merchant_order_id}, amount={amount}, method={method}")

        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                allow_redirects=False,
                timeout=30
            )

            if response.status_code in [301, 302]:
                redirect_url = response.headers.get('Location')
                if redirect_url:
                    logger.info(f"Plat payment created successfully: {redirect_url}")
                    return redirect_url
                else:
                    raise RuntimeError("Plat returned no redirect URL")
            else:
                # Пробуем получить ошибку из JSON
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', 'Unknown error')
                    raise RuntimeError(f"Plat API error: {error_msg}")
                except:
                    text = response.text
                    raise RuntimeError(f"Plat API error. Status: {response.status_code}, Response: {text}")

        except Exception as e:
            logger.error(f"Failed to create Plat payment: {e}")
            raise

    def get_payment_info(self, guid: str) -> Dict[str, Any]:
        """
        СИНХРОННОЕ получение информации о платеже по GUID
        """
        endpoint = f"/api/merchant/order/info/{guid}/by-api"
        url = f"{self.BASE_URL}{endpoint}"

        headers = {
            "x-shop": self.shop_id,
            "x-secret": self.secret_key,
        }

        logger.debug(f"Getting payment info for GUID: {guid}")

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
                else:
                    raise RuntimeError(f"Plat API error: {data}")
            else:
                raise RuntimeError(f"Plat API error. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to get payment info: {e}")
            raise

    def check_connection(self) -> bool:
        """
        СИНХРОННАЯ проверка подключения к Plat API
        """
        endpoint = "/api/shop/info/by-api"
        url = f"{self.BASE_URL}{endpoint}"

        headers = {
            "x-shop": self.shop_id,
            "x-secret": self.secret_key,
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                shop_name = data.get('shop', {}).get('name', 'Unknown')
                logger.info(f"Plat connection successful. Shop: {shop_name}")
                return True
            else:
                logger.error(f"Plat connection failed. Status: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Plat connection check error: {e}")
            return False

    def verify_callback(self, payload: dict) -> bool:
        """
        Проверка подписи callback от Plat
        """
        try:
            # Извлекаем данные для проверки
            merchant_id = str(payload.get('merchant_id', ''))
            amount = str(payload.get('amount', ''))
            shop_id = str(self.shop_id)
            signature_v2 = payload.get('signature_v2', '')

            # Генерируем ожидаемую подпись
            expected_signature = hashlib.md5(
                f"{merchant_id}{amount}{shop_id}{self.secret_key}".encode()
            ).hexdigest()

            is_valid = signature_v2 == expected_signature

            if is_valid:
                logger.info("Plat callback signature verified successfully")
            else:
                logger.warning(f"Plat callback signature mismatch. Expected: {expected_signature}, Got: {signature_v2}")

            return is_valid

        except Exception as e:
            logger.error(f"Callback verification error: {e}")
            return False

    def create_withdraw(
            self,
            merchant_id: str,
            amount: int,  # в рублях
            method_id: int,
            purse: str,
            bank: Optional[str] = None,
            token: Optional[str] = None,
            commission_payment: bool = True
    ) -> Dict[str, Any]:
        """
        Создание выплаты средств

        Docs: /api/merchant/withdraw/shop/create/by-api

        Status:
        -3 - отменен мерчантом
        -2 - отменен администратором
        -1 - отменен пользователем
        0 - в ожидании
        1 - в процессе выплаты
        2 - успешно выполнен
        """
        endpoint = "/api/merchant/withdraw/shop/create/by-api"
        url = f"{self.BASE_URL}{endpoint}"

        payload = {
            "amount": float(amount),
            "method_id": method_id,
            "merchant_id": merchant_id,
            "purse": purse,
            "commission_payment": commission_payment
        }

        # Опциональные поля
        if bank:
            payload["bank"] = bank
        if token:
            payload["token"] = token

        headers = {
            "x-shop": self.shop_id,
            "x-secret": self.secret_key,
            "Content-Type": "application/json",
        }

        logger.info(f"Creating withdraw: amount={amount}, method_id={method_id}, purse={purse}")

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    logger.info(f"Withdraw created successfully: {data['withdraw']}")
                    return data
                else:
                    raise RuntimeError(f"Plat withdraw error: {data}")
            else:
                raise RuntimeError(f"Plat API error. Status: {response.status_code}")

        except Exception as e:
            logger.error(f"Failed to create withdraw: {e}")
            raise

    def get_withdraw_info(self, withdraw_id: int) -> Dict[str, Any]:
        """
        Получение информации о выплате

        Docs: /api/merchant/shop/withdraw/info/{id}/by-api
        """
        endpoint = f"/api/merchant/shop/withdraw/info/{withdraw_id}/by-api"
        url = f"{self.BASE_URL}{endpoint}"

        headers = {
            "x-shop": self.shop_id,
            "x-secret": self.secret_key,
        }

        logger.debug(f"Getting withdraw info: id={withdraw_id}")

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
                else:
                    raise RuntimeError(f"Plat API error: {data}")
            else:
                raise RuntimeError(f"Plat API error. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to get withdraw info: {e}")
            raise

    def get_withdraw_methods(self) -> Dict[str, Any]:
        """
        Получение доступных методов для выплат

        Docs: /api/merchant/payments/methods/by-api
        """
        endpoint = "/api/merchant/payments/methods/by-api"
        url = f"{self.BASE_URL}{endpoint}"

        headers = {
            "x-shop": self.shop_id,
            "x-secret": self.secret_key,
        }

        logger.debug("Getting withdraw methods")

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data
                else:
                    raise RuntimeError(f"Plat API error: {data}")
            else:
                raise RuntimeError(f"Plat API error. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to get withdraw methods: {e}")
            raise