import hashlib

# Ваши реальные данные из настроек Plat
merchant_id = "543"  # или возьмите из callback данных
amount = "100"
shop_id = "825"  # ваш PLAT_SHOP_ID
secret_key = "ваш_PLAT_SECRET_KEY"  # из settings.py

signature_v2 = hashlib.md5(
    f"{merchant_id}{amount}{shop_id}{secret_key}".encode()
).hexdigest()

print(f"Signature v2: {signature_v2}")