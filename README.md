# 🃏 Burkozel

Мультиплеерная онлайн-игра с использованием **FastAPI**, **Redis**, **PostgreSQL** и **Centrifugo** для real-time взаимодействия.

---

## 🚀 Запуск через Docker

### 1. Переменные окружения
Создать файл `.env` в корне проекта:

```env
BOT_TOKEN=test_token
ADMIN_IDS=[5254325840]
BASE_URL=base_url
FRONT_URL=base_url

SECRET_KEY=bbe7d157-a253-4094-9759-06a8236543f9

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=my_super_pass
REDIS_SSL=0


CENTRIFUGO_API_KEY=super_api_key
CENTRIFUGO_URL=http://localhost:8000/api
SOCKET_URL=ws://localhost:8000/connection/websocket


# POSTGRES
POSTGRES_DB=durak
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_PORT=5432
POSTGRES_HOST=localhost

PLAT_SHOP_ID=888
PLAT_SECRET_KEY=11

```

### 2. Сборка и запуск

```commandline
docker-compose up --build
```


### 3. Доступ
API → http://localhost:8000

Swagger Docs → http://localhost:8000/docs

### 📂 Структура проекта
bash
```commandline
app/
 ├── game/          # игровая логика
 │   ├── api/       # эндпоинты
 │   ├── core/      # правила игры (Burkozel)
 │   ├── redis_dao/ # работа с Redis
 │   └── tests/     # тесты
 ├── users/         # пользователи
 ├── payments/      # система транзакций
 ├── migration/     # alembic миграции
 ├── config.py      # конфигурация
 └── main.py        # точка входа FastAPI
```

### 🎮 Эндпоинты

---

#### 🕹 Игры (`/games`)
| Метод | Эндпоинт              | Описание                                           |
|-------|-----------------------|---------------------------------------------------|
| GET   | `/games/`             | Получить все игры                                 |
| GET   | `/games/{game_id}`    | Получить игру по ID                               |
| POST  | `/games/clear_db`     | Очистить БД (кроме таблицы `game_types`)          |

---

#### 🎴 Буркозел (`/burkozel`)
| Метод | Эндпоинт                          | Описание                          |
|-------|-----------------------------------|-----------------------------------|
| POST  | `/burkozel/find_player`           | Найти или создать комнату         |
| POST  | `/burkozel/join_room`             | Присоединиться к комнате          |
| POST  | `/burkozel/ready`                 | Отметить игрока готовым           |
| POST  | `/burkozel/move`                  | Сделать ход (атака/защита)        |
| POST  | `/burkozel/leave`                 | Выйти из комнаты                  |
| GET   | `/burkozel/rooms`                 | Список ожидающих комнат           |
| GET   | `/burkozel/all_rooms`             | Все комнаты                       |
| GET   | `/burkozel/room/{room_id}`        | Состояние комнаты                 |
| POST  | `/burkozel/clear_room/{room_id}`  | Очистить комнату                  |
| POST  | `/burkozel/clear_redis`           | Очистить Redis                    |
| POST  | `/burkozel/create_test_room`      | Создать тестовую комнату          |
| POST  | `/burkozel/create_last_hand_room` | Тест конца игры                   |

---

#### 👤 Пользователи (`/users`)
| Метод | Эндпоинт                                | Описание                          |
|-------|-----------------------------------------|-----------------------------------|
| POST  | `/users/add_user`                       | Создать пользователя              |
| GET   | `/users/all_users`                      | Список пользователей              |
| GET   | `/users/get_current_user?tg_id=...`     | Получить пользователя по `tg_id`  |
| PATCH | `/users/update_user/{user_id}`          | Обновить данные пользователя      |

---

#### 💳 Платежи (`/payments`)
| Метод | Эндпоинт                                | Описание                          |
|-------|-----------------------------------------|-----------------------------------|
| POST  | `/payments/paycash?tg_id=&amount=`      | Пополнить баланс                  |
| POST  | `/payments/callback`                    | Callback от платежной системы     |
| GET   | `/payments/transactions/{tg_id}`        | История транзакций игрока         |

---

### 🔄 Real-Time (Centrifugo)

Используется **Centrifugo** для обновлений в реальном времени.

**События:**
- `new_room` — создана новая комната  
- `close_room` — комната закрыта  
- `game_start` — начало игры  
- `move` — сделан ход  
- `hand` — обновление карт игрока  
  ```json
  {
    "event": "hand",
    "payload": {
      "hand": [["8","♥"],["J","♣"],["9","♠"]],
      "old_cards_user": [["6","♠"]],
      "trump": "♦",
      "deck_count": 28,
      "attacker": "7022782558"
    }
  }


game_over — игра завершена

reshuffle — пересдача карт


### 🔗 Игровой процесс
Игрок вызывает find_player или join_room.

При готовности жмет ready.

После старта получает событие game_start и свою руку (hand).

Игроки ходят через move, события обновляются через Centrifugo.

При доборе карт отправляется hand с new_cards и old_cards_user.

Игра завершается событием game_over либо пересдачей reshuffle.