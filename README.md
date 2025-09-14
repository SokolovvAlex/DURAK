# 🎮 Burkozel Online API — Frontend Guide

Этот документ описывает REST API и события **Centrifugo**, которые фронт использует для реализации игры **Буркозёл 1x1**.

---

## 📌 Общие положения

* **Идентификация игроков** — через `tg_id` (Telegram ID).
* **REST API** — все игровые действия (`/burkozel/...`).
* **Centrifugo** — WebSocket-каналы для событий в реальном времени.
* **Redis** — хранение состояния комнаты: колода, поле, игроки, очки.

---

## 🔗 REST API

### `POST /burkozel/find_player`

Поиск комнаты или создание новой.

**Request**

```json
{
  "tg_id": 7022782558,
  "nickname": "sasha",
  "stake": 10
}
```

**Response (нашёлся соперник)**

```json
{
  "room_id": "10_a42fe7db",
  "status": "matched",
  "message": "Игрок найден",
  "stake": 10,
  "opponent": "edward"
}
```

**Response (ожидаем соперника)**

```json
{
  "room_id": "10_123abcd4",
  "status": "waiting",
  "message": "Ожидание второго игрока",
  "stake": 10
}
```

---

### `POST /burkozel/ready`

Игрок отмечает готовность. Когда оба готовы → старт игры.

**Request**

```json
{
  "room_id": "10_a42fe7db",
  "tg_id": 7022782558
}
```

**Response**

```json
{ "ok": true }
```

После старта всем игрокам приходят события в Centrifugo:

* `hand` (индивидуально, карты игрока),
* `game_start` (общая информация: козырь, атакующий, колода).

---

### `POST /burkozel/move`

Игрок делает ход.

* Если поле пустое → **атака**.
* Если поле уже заполнено атакой → **защита**.
* После защиты → определяется победитель, начисляются очки, добор карт по одной (до 4 в руке), поле очищается.

**Request**

```json
{
  "room_id": "10_a42fe7db",
  "tg_id": 7022782558,
  "cards": [["8","♠"]]
}
```

**Response**

```json
{
  "ok": true,
  "room": { ...полное состояние комнаты... }
}
```


---

### `GET /burkozel/rooms`

Получить список всех активных комнат.

---

### `POST /burkozel/clear_room/{room_id}`

Удалить конкретную комнату (для админов/отладки).

---

### `POST /burkozel/create_test_room`

Создать тестовую комнату (с полной колодой и руками по 4 карты).
Используется для отладки фронта.

---

## 📡 Centrifugo Events

### 🔹 Индивидуальные каналы

Канал: `user#{tg_id}`

#### `hand`

Отправляется при старте и при доборе карт.

```json
{
  "event": "hand",
  "payload": {
    "hand": [["8","♥"],["J","♣"],["9","♠"],["8","♠"]],
    "trump": "♦",
    "deck_count": 28,
    "attacker": "7022782558"
  }
}
```

---

### 🔹 Канал комнаты

Канал: `room#{room_id}`

#### `game_start`

```json
{
  "event": "game_start",
  "payload": {
    "room_id": "10_a42fe7db",
    "trump": "♥",
    "deck_count": 28,
    "attacker": "7022782558"
  }
}
```

#### `move`

```json
{
  "event": "move",
  "payload": {
    "room_id": "10_a42fe7db",
    "field": {
      "attack": {"player": "7022782558", "cards": [["8","♠"]]},
      "defend": {"player": "5254325840", "cards": [["9","♠"]]},
      "winner": "5254325840"
    },
    "hands_count": {
      "7022782558": 4,
      "5254325840": 4
    }
  }
}
```

#### `game_over`

```json
{
  "event": "game_over",
  "payload": {
    "room_id": "10_a42fe7db",
    "winner": "7022782558",
    "loser": "5254325840",
    "stake": 10
  }
}
```

---

# 📦 Хранение данных в Redis

Каждая комната хранится как один ключ в Redis:

🔑 **Ключ**:

```
{stake}_{room_id}
например: "10_a42fe7db"
```

📄 **Значение (JSON):**

```json
{
  "room_id": "10_a42fe7db",
  "stake": 10,
  "created_at": "2025-09-12T07:39:26.642840",
  "status": "playing",
  "players": {
    "7022782558": {
      "nickname": "sasha",
      "is_ready": true,
      "hand": [
        ["8","♥"], ["J","♣"], ["9","♠"], ["8","♠"]
      ],
      "round_score": 0,
      "penalty": 0
    },
    "5254325840": {
      "nickname": "ed",
      "is_ready": true,
      "hand": [
        ["A","♣"], ["7","♦"], ["Q","♠"], ["8","♦"]
      ],
      "round_score": 0,
      "penalty": 0
    }
  },
  "deck": [
    ["Q","♦"], ["9","♥"], ["8","♣"], ["A","♦"], ...
  ],
  "trump": "♥",
  "field": {
    "attack": null,
    "defend": null,
    "winner": null
  },
  "attacker": "7022782558"
}
```

---

### 🔑 Основные элементы

* `room_id` — уникальный ID комнаты (stake + random uuid).
* `stake` — ставка (размер банка).
* `status` — `waiting` | `matched` | `playing`.
* `players` — игроки в комнате:

  * `nickname` — имя игрока.
  * `hand` — список карт на руках.
  * `round_score` — очки за взятки в текущей партии.
  * `penalty` — штрафные очки (до 12).
* `deck` — оставшиеся карты в колоде.
* `trump` — козырная масть.
* `field` — текущее состояние стола:

  * `attack` — карты атакующего.
  * `defend` — карты защитника.
  * `winner` — ID игрока, который взял взятку (null, пока не определён).
* `attacker` — чей сейчас ход.

---

# 🧪 Эндпоинт: создание тестовой комнаты

Используется для отладки фронта: быстро создать готовую комнату с предопределёнными руками и колодой.

```python
@router.post("/create_test_room")
async def create_test_room(redis: CustomRedis = Depends(get_redis)):
    room_id = f"10_{uuid.uuid4().hex[:8]}"
    trump = "♥"

    room = {
        "room_id": room_id,
        "stake": 10,
        "created_at": datetime.utcnow().isoformat(),
        "status": "playing",
        "players": {
            "7022782558": {
                "nickname": "sasha",
                "is_ready": True,
                "hand": [["8","♥"],["J","♣"],["9","♠"],["8","♠"]],
                "round_score": 0,
                "penalty": 0
            },
            "5254325840": {
                "nickname": "ed",
                "is_ready": True,
                "hand": [["A","♣"],["7","♦"],["Q","♠"],["8","♦"]],
                "round_score": 0,
                "penalty": 0
            }
        },
        "deck": [
            ["Q","♦"], ["9","♥"], ["8","♣"], ["A","♦"], ["9","♦"], ["Q","♥"],
            ["A","♥"], ["6","♥"], ["10","♠"], ["10","♦"], ["K","♦"], ["K","♣"],
            ["6","♣"], ["A","♠"], ["J","♠"], ["7","♣"], ["J","♥"], ["6","♦"],
            ["7","♠"], ["7","♥"], ["K","♠"], ["9","♣"], ["Q","♣"], ["6","♠"],
            ["10","♣"], ["K","♥"], ["J","♦"]
        ],
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "attacker": "7022782558"
    }

    await redis.set(room_id, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая комната {room_id}")

    return {"ok": True, "room": room}
```

---

Хорошо 🚀
Давай пошагово разберём, как поднять твой проект через **Docker** и **docker-compose**.

---

# 📦 Поднятие проекта через Docker


## ⚙️ Файл `.env`

Пример `.env` для dev:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=burkozel
POSTGRES_HOST=db
POSTGRES_PORT=5432

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD= # если без пароля, оставить пустым

CENTRIFUGO_API_KEY=super_api_key
CENTRIFUGO_URL=http://centrifugo:8000/api
SOCKET_URL=ws://localhost:8000/connection/websocket

DB_URL=postgresql+asyncpg://postgres:postgres@db:5432/burkozel
```

## 🚀 Запуск

```bash
# Сборка
docker-compose build

# Запуск
docker-compose up -d

```

---

## 7. 🔗 Доступ

* FastAPI backend → [http://localhost:8001/docs](http://localhost:8001/docs)
* Centrifugo → [http://localhost:8000](http://localhost:8000)
* Redis → localhost:6379
* Postgres → localhost:5432

---
