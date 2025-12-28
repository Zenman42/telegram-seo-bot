"""
Telegram Mini App Backend для SEO-ассистента на Claude
С интеграцией Just-Magic API
"""

import os
import json
import logging
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import anthropic

from justmagic_tools import JustMagicTools, TOOLS_DEFINITIONS

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
JUSTMAGIC_API_KEY = os.environ.get("JUSTMAGIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Системный промпт для Claude
SYSTEM_PROMPT = """Ты — SEO-ассистент, работающий через Telegram Mini App.

У тебя есть доступ к инструментам Just-Magic для SEO-анализа:
- Кластеризация семантики (justmagic_cluster)
- Сбор частотности из Wordstat (justmagic_wordstat_frequency)
- Парсер подсказок (justmagic_suggestions_parser)
- Текстовый анализатор страниц (justmagic_text_analyzer)
- LSI-анализ текста (justmagic_aquarelle)
- Генератор LSI-слов (justmagic_aquarelle_generator)
- Тематическая классификация (justmagic_thematic_classifier)
- Маркеры для распределения запросов (justmagic_markers_online)
- Расширение семантики (justmagic_expand_semantics)
- Поиск по регулярным выражениям (justmagic_regex_search)

Важно:
1. Многие задачи выполняются асинхронно — ты ставишь задачу и сообщаешь пользователю ID
2. Регион 213 = Москва, 2 = Санкт-Петербург
3. Для кластеризации нужен список запросов

Отвечай кратко и по делу. Используй инструменты когда нужно выполнить SEO-задачу.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SEO Bot Backend...")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Telegram SEO Bot",
    description="SEO-ассистент на Claude с Just-Magic",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    message: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    tool_calls: Optional[list] = None
    conversation_id: str


# Хранилище диалогов (в проде использовать Redis/PostgreSQL)
conversations: dict[str, list] = {}


def get_anthropic_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def get_justmagic_tools() -> JustMagicTools:
    if not JUSTMAGIC_API_KEY:
        raise HTTPException(status_code=500, detail="JUSTMAGIC_API_KEY not configured")
    return JustMagicTools(JUSTMAGIC_API_KEY)


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "justmagic_configured": bool(JUSTMAGIC_API_KEY),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN)
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatMessage):
    conv_id = request.conversation_id or f"conv_{request.user_id or 'anon'}_{datetime.now().timestamp()}"
    
    if conv_id not in conversations:
        conversations[conv_id] = []
    
    history = conversations[conv_id]
    history.append({"role": "user", "content": request.message})
    
    try:
        client = get_anthropic_client()
        jm_tools = get_justmagic_tools()
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS_DEFINITIONS,
            messages=history
        )
        
        tool_calls_made = []
        
        while response.stop_reason == "tool_use":
            tool_uses = [block for block in response.content if block.type == "tool_use"]
            history.append({"role": "assistant", "content": response.content})
            
            tool_results = []
            for tool_use in tool_uses:
                tool_name = tool_use.name
                tool_input = tool_use.input
                
                logger.info(f"Calling tool: {tool_name}")
                result = await jm_tools.execute(tool_name, tool_input)
                
                tool_calls_made.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result_preview": str(result)[:200]
                })
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
            
            history.append({"role": "user", "content": tool_results})
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS_DEFINITIONS,
                messages=history
            )
        
        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text
        
        history.append({"role": "assistant", "content": response.content})
        
        if len(history) > 40:
            conversations[conv_id] = history[-40:]
        
        return ChatResponse(
            response=final_text,
            tool_calls=tool_calls_made if tool_calls_made else None,
            conversation_id=conv_id
        )
        
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        raise HTTPException(status_code=500, detail=f"AI service error: {str(e)}")
    except Exception as e:
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clear")
async def clear_conversation(conversation_id: str):
    if conversation_id in conversations:
        del conversations[conversation_id]
    return {"status": "ok"}


@app.get("/api/tasks")
async def list_tasks(limit: int = 10):
    try:
        jm_tools = get_justmagic_tools()
        result = await jm_tools.execute("justmagic_list_tasks", {"limit": limit})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks/{tid}")
async def get_task(tid: int):
    try:
        jm_tools = get_justmagic_tools()
        result = await jm_tools.execute("justmagic_get_task", {"tid": tid, "mode": "info"})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/account")
async def get_account_info():
    try:
        jm_tools = get_justmagic_tools()
        result = await jm_tools.execute("justmagic_info", {})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
