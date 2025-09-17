

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from loguru import logger


router = APIRouter(prefix="/games", tags=["GAMES"])


