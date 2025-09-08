import asyncio

import aiohttp

from app.config import settings


async def debug_shop_info():
    base_url = "https://1plat.cash"
    endpoint = "/api/shop/info/by-api"
    url = f"{base_url}{endpoint}"

    print(f"Shop ID: {settings.PLAT_SHOP_ID}")
    print(f"Secret Key: {settings.PLAT_SECRET_KEY}")

    headers = {
        "x-shop": settings.PLAT_SHOP_ID,
        "x-secret": settings.PLAT_SECRET_KEY,
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            print(f"Status Code: {response.status}")
            print(f"Response Headers: {dict(response.headers)}")

            try:
                data = await response.json()
                print(f"Response Data: {data}")
                return data
            except Exception as e:
                text = await response.text()
                print(f"Response Text: {text}")
                print(f"Error: {e}")
                return None


# Запустите debug функцию
print(asyncio.run(debug_shop_info()))