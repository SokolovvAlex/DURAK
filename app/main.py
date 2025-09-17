import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from loguru import logger
from starlette.middleware.cors import CORSMiddleware

from app.bot.create_bot import bot, dp, stop_bot, start_bot
from app.bot.handlers.router import router as bot_router
from app.config import settings

from app.game.api.router import router as game_router
from app.game.redis_dao.manager import redis_manager
from app.users.router import router as user_router
from app.payments.router import router as payments_router

from fastapi.staticfiles import StaticFiles
from aiogram.types import Update
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Бот запущен...")
    await redis_manager.connect()
    await start_bot()
    # webhook_url = settings.hook_url
    # await bot.set_webhook(url=webhook_url,
    #                       allowed_updates=dp.resolve_used_update_types(),
    #                       drop_pending_updates=True)
    # logger.success(f"Вебхук установлен: {webhook_url}")

    dp.include_router(bot_router)
    asyncio.create_task(dp.start_polling(bot))

    yield
    logger.info("Бот остановлен...")
    await stop_bot()
    await redis_manager.close()



app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.post("/webhook")
async def webhook(request: Request) -> None:
    logging.info("Received webhook request")
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    logging.info("Update processed")


app.include_router(game_router)
app.include_router(user_router)
app.include_router(payments_router)


#ngrok http --url bursting-smart-eagle.ngrok-free.app 8080
#docker run --name redis -d -p 6379:6379 redis
#docker run -d -p 8000:8000 --name centrifugo my-centrifugo

# if __name__ == "__main__":
#     uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)
