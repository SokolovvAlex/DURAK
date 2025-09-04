import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn

from app.bot.create_bot import bot, dp, stop_bot, start_bot
from app.bot.handlers.router import router as bot_router
from app.config import settings

from app.game.router import router as game_router
from app.users.router import router as user_router

from fastapi.staticfiles import StaticFiles
from aiogram.types import Update
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Starting bot setup...")
    dp.include_router(bot_router)
    await start_bot()
    asyncio.create_task(dp.start_polling(bot))

    yield
    logging.info("Shutting down bot...")
    await stop_bot()



app = FastAPI(lifespan=lifespan)

app.mount('/static', StaticFiles(directory='app/static'), 'static')


@app.post("/webhook")
async def webhook(request: Request) -> None:
    logging.info("Received webhook request")
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    logging.info("Update processed")


app.include_router(game_router)
app.include_router(user_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)
