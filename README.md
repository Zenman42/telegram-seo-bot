# Telegram SEO Bot Mini App

SEO-ассистент на Claude с интеграцией Just-Magic API.

## Возможности

- 🔍 Кластеризация семантики
- 📊 Сбор частотности из Wordstat
- 💡 Парсинг подсказок
- 📝 Текстовый анализ страниц
- 🎨 LSI-анализ (Акварель)
- 📑 Тематическая классификация

## Деплой на Railway

### 1. Загрузи файлы на GitHub

Создай репозиторий и загрузи все файлы из этой папки.

### 2. Подключи к Railway

1. Зайди на [railway.app](https://railway.app)
2. Login with GitHub
3. New Project → Deploy from GitHub repo
4. Выбери репозиторий

### 3. Добавь переменные окружения

В Railway → твой сервис → Variables добавь:

| Variable | Описание |
|----------|----------|
| `ANTHROPIC_API_KEY` | Ключ от console.anthropic.com |
| `JUSTMAGIC_API_KEY` | Ключ от just-magic.org |
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |

### 4. Получи ссылку

Settings → Networking → Generate Domain

### 5. Настрой Mini App в Telegram

1. Открой @BotFather
2. /mybots → выбери бота
3. Bot Settings → Menu Button → Configure
4. Введи URL от Railway

## Локальный запуск

```bash
# Установи зависимости
pip install -r requirements.txt

# Создай .env файл
export ANTHROPIC_API_KEY=sk-ant-...
export JUSTMAGIC_API_KEY=...
export TELEGRAM_BOT_TOKEN=...

# Запусти
uvicorn main:app --reload
```

## Структура

```
├── main.py              # FastAPI backend
├── justmagic_tools.py   # Just-Magic интеграция  
├── static/
│   └── index.html       # Mini App UI
├── requirements.txt
└── nixpacks.toml        # Railway конфиг
```

## API

- `GET /` — Mini App
- `GET /health` — Health check
- `POST /api/chat` — Чат с Claude
- `GET /api/tasks` — Список задач
- `GET /api/account` — Баланс аккаунта
