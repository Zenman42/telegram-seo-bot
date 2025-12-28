"""
Just-Magic Tools для интеграции с Claude API
Адаптировано из MCP-сервера для использования как обычные функции
"""

import json
import gzip
import csv
import io
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.just-magic.org/api_v1.php"

# Определения инструментов в формате Anthropic Tools
TOOLS_DEFINITIONS = [
    {
        "name": "justmagic_info",
        "description": "Получить информацию об аккаунте Just-Magic: тариф, баланс, срок действия подписки",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "justmagic_list_tasks",
        "description": "Получить список задач пользователя с их статусами",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Количество задач (по умолчанию 10, максимум 100)", "default": 10},
                "offset": {"type": "integer", "description": "Смещение для пагинации", "default": 0}
            },
            "required": []
        }
    },
    {
        "name": "justmagic_get_task",
        "description": "Получить информацию о конкретной задаче и её результат",
        "input_schema": {
            "type": "object",
            "properties": {
                "tid": {"type": "integer", "description": "ID задачи"},
                "mode": {"type": "string", "enum": ["info", "xlsx", "csv"], "description": "Режим выдачи", "default": "info"}
            },
            "required": ["tid"]
        }
    },
    {
        "name": "justmagic_download_result",
        "description": "Скачать результат задачи в виде таблицы (CSV). Возвращает данные как список строк",
        "input_schema": {
            "type": "object",
            "properties": {
                "tid": {"type": "integer", "description": "ID задачи"},
                "max_rows": {"type": "integer", "description": "Максимальное число строк (по умолчанию 100)", "default": 100}
            },
            "required": ["tid"]
        }
    },
    {
        "name": "justmagic_cluster",
        "description": "Кластеризация семантического ядра. Группирует запросы по топам выдачи Яндекс/Google. Задача выполняется асинхронно — возвращает ID задачи для отслеживания.",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "Список запросов для кластеризации"},
                "search_engine": {"type": "string", "enum": ["yandex", "google"], "default": "yandex"},
                "region": {"type": "integer", "description": "Код региона Яндекса (213 = Москва)", "default": 213},
                "google_lr": {"type": "string", "description": "Регион Google (например 'Saratov Oblast,Russia')"},
                "lang": {"type": "string", "enum": ["ru", "en"], "default": "ru"},
                "label": {"type": "string", "description": "Метка задачи"},
                "collect_frequency": {"type": "boolean", "description": "Собирать базовую частотность", "default": False},
                "domain": {"type": "string", "description": "Домен для поиска релевантных страниц"},
                "just_ask": {"type": "boolean", "description": "Только рассчитать стоимость", "default": False}
            },
            "required": ["queries"]
        }
    },
    {
        "name": "justmagic_text_analyzer",
        "description": "Текстовый анализатор страниц. Анализирует текстовую оптимизацию URL по группе запросов",
        "input_schema": {
            "type": "object",
            "properties": {
                "pages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "queries": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["url", "queries"]
                    },
                    "description": "Список страниц с запросами"
                },
                "search_engine": {"type": "string", "enum": ["yandex", "google"], "default": "yandex"},
                "region": {"type": "integer", "description": "Код региона Яндекса", "default": 213},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["pages"]
        }
    },
    {
        "name": "justmagic_aquarelle",
        "description": "Акварель - LSI анализ текста. Проверяет тематичность текста запросу пословно",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Ключевое слово/фраза"},
                "text": {"type": "string", "description": "Текст для анализа"},
                "search_engine": {"type": "string", "enum": ["yandex", "google"], "default": "yandex"},
                "lang": {"type": "string", "enum": ["ru", "en"], "default": "ru"}
            },
            "required": ["keyword", "text"]
        }
    },
    {
        "name": "justmagic_aquarelle_generator",
        "description": "Акварель-генератор - генерирует список LSI слов для написания тематичного текста",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "Список запросов"},
                "search_engine": {"type": "string", "enum": ["yandex", "google"], "default": "yandex"},
                "lang": {"type": "string", "enum": ["ru", "en"], "default": "ru"},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["queries"]
        }
    },
    {
        "name": "justmagic_wordstat_frequency",
        "description": "Сбор частотности запросов из Яндекс.Wordstat",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "Список запросов"},
                "region": {"type": "integer", "description": "Код региона Яндекса"},
                "device": {"type": "string", "enum": ["all", "desktop", "tablet_phone", "tablet", "phone"], "default": "all"},
                "label": {"type": "string"},
                "s_std": {"type": "boolean", "description": "Базовая частотность", "default": True},
                "s_q": {"type": "boolean", "description": 'Частотность в кавычках "купить слона"', "default": False},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["queries"]
        }
    },
    {
        "name": "justmagic_suggestions_parser",
        "description": "Парсер поисковых подсказок Яндекса с итерациями и перебором",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "Базовые запросы"},
                "region": {"type": "integer", "description": "Код региона", "default": 213},
                "lang": {"type": "string", "enum": ["ru", "en"], "default": "ru"},
                "iterations": {"type": "integer", "description": "Число итераций (1-3)", "default": 1},
                "add_russian_letters": {"type": "boolean", "description": "Перебор русского алфавита", "default": False},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["queries"]
        }
    },
    {
        "name": "justmagic_thematic_classifier",
        "description": "Тематическая классификация запросов по категориям",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "Список запросов"},
                "show_all_categories": {"type": "boolean", "description": "Показать 10 категорий с весами", "default": False},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["queries"]
        }
    },
    {
        "name": "justmagic_markers_online",
        "description": "Маркеры-онлайн - распределение запросов по страницам сайта на основе выдачи",
        "input_schema": {
            "type": "object",
            "properties": {
                "pages": {"type": "array", "items": {"type": "object"}, "description": "Страницы с текущими запросами"},
                "base_queries": {"type": "array", "items": {"type": "string"}, "description": "База запросов для распределения"},
                "region": {"type": "integer", "default": 213},
                "mode": {"type": "string", "enum": ["hard", "soft"], "default": "hard"},
                "min_power": {"type": "integer", "description": "Минимальный порог привязки (3-9)", "default": 3},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["pages", "base_queries"]
        }
    },
    {
        "name": "justmagic_expand_semantics",
        "description": "Расширение семантического ядра на основе локальной базы",
        "input_schema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "Исходные запросы"},
                "base": {"type": "integer", "description": "ID локальной базы", "default": 3},
                "depth": {"type": "integer", "description": "Глубина расширения (0-9)", "default": 1},
                "min_power": {"type": "integer", "description": "Минимальный порог связи (3-9)", "default": 3},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["queries"]
        }
    },
    {
        "name": "justmagic_regex_search",
        "description": "Поиск по регулярному выражению в локальной базе ключевых слов",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "POSIX регулярное выражение для поиска"},
                "exclude_pattern": {"type": "string", "description": "Регулярное выражение для исключения"},
                "base": {"type": "integer", "description": "ID локальной базы", "default": 3},
                "just_ask": {"type": "boolean", "default": False}
            },
            "required": ["pattern"]
        }
    }
]


class JustMagicTools:
    """Класс для выполнения инструментов Just-Magic"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def _request(self, action: str, params: dict = None) -> dict:
        """Базовый запрос к API"""
        data = {"action": action, "apikey": self.api_key}
        if params:
            data.update(params)
        
        files = {k: (None, str(v)) for k, v in data.items()}
        
        try:
            response = await self.client.post(API_URL, files=files)
            return response.json()
        except Exception as e:
            logger.error(f"API request error: {e}")
            return {"err": "request_error", "errtxt": str(e)}
    
    async def _request_binary(self, action: str, params: dict = None) -> tuple[bytes, dict]:
        """Запрос для получения бинарных данных"""
        data = {"action": action, "apikey": self.api_key}
        if params:
            data.update(params)
        
        files = {k: (None, str(v)) for k, v in data.items()}
        
        try:
            response = await self.client.post(API_URL, files=files)
            return response.content, dict(response.headers)
        except Exception as e:
            return None, {"error": str(e)}
    
    async def _get_task_csv(self, tid: int) -> list[list]:
        """Скачать результат задачи как CSV"""
        content, headers = await self._request_binary("get_task", {"tid": tid, "mode": "csv", "system": "unix"})
        
        if content is None:
            return []
        
        try:
            error = json.loads(content)
            if error.get("err"):
                return []
        except:
            pass
        
        try:
            decompressed = gzip.decompress(content)
            text = decompressed.decode('utf-8')
        except:
            text = content.decode('utf-8')
        
        reader = csv.reader(io.StringIO(text), delimiter='\t')
        return list(reader)
    
    async def _put_task(self, task_data: dict, just_ask: bool = False) -> dict:
        """Поставить задачу в очередь"""
        params = dict(task_data)
        if just_ask:
            params["justask"] = 1
        return await self._request("put_task", params)
    
    async def execute(self, name: str, args: dict) -> dict:
        """Выполнить инструмент по имени"""
        
        # === Информация ===
        if name == "justmagic_info":
            return await self._request("info")
        
        elif name == "justmagic_list_tasks":
            return await self._request("list_tasks", {
                "limit": min(args.get("limit", 10), 100),
                "offset": args.get("offset", 0)
            })
        
        elif name == "justmagic_get_task":
            return await self._request("get_task", {
                "tid": args["tid"],
                "mode": args.get("mode", "info")
            })
        
        elif name == "justmagic_download_result":
            data = await self._get_task_csv(args["tid"])
            max_rows = args.get("max_rows", 100)
            if not data:
                return {"err": "no_data", "errtxt": "Не удалось получить данные"}
            return {
                "err": 0,
                "total_rows": len(data),
                "returned_rows": min(len(data), max_rows),
                "data": data[:max_rows]
            }
        
        # === Кластеризация (grp_onl) ===
        elif name == "justmagic_cluster":
            task_data = {
                "task": "grp_onl",
                "data": "\n".join(args["queries"]),
                "search_engine": args.get("search_engine", "yandex"),
                "lang": args.get("lang", "ru"),
            }
            if args.get("search_engine") == "google" and args.get("google_lr"):
                task_data["google_lr"] = args["google_lr"]
            else:
                task_data["ya_lr"] = args.get("region", 213)
            
            if args.get("collect_frequency"):
                task_data["s_std"] = 1
            if args.get("label"):
                task_data["label"] = args["label"]
            if args.get("domain"):
                task_data["domain"] = args["domain"]
            
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Текстовый анализатор (txt_anlz) ===
        elif name == "justmagic_text_analyzer":
            lines = []
            for p in args["pages"]:
                for query in p["queries"]:
                    lines.append(p["url"] + "\t" + query)
            task_data = {
                "task": "txt_anlz",
                "data": "\n".join(lines),
                "search_engine": args.get("search_engine", "yandex"),
                "ya_lr": args.get("region", 213),
            }
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Акварель (aqua) ===
        elif name == "justmagic_aquarelle":
            task_data = {
                "task": "aqua",
                "key": args["keyword"],
                "data": args["text"],
                "search_engine": args.get("search_engine", "yandex"),
                "lang": args.get("lang", "ru"),
            }
            return await self._put_task(task_data, False)
        
        # === Акварель-генератор (aqua_gen) ===
        elif name == "justmagic_aquarelle_generator":
            task_data = {
                "task": "aqua_gen",
                "data": "\n".join(args["queries"]),
                "search_engine": args.get("search_engine", "yandex"),
                "lang": args.get("lang", "ru"),
            }
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Частотность WordStat (wsfreq) ===
        elif name == "justmagic_wordstat_frequency":
            task_data = {
                "task": "wsfreq",
                "data": "\n".join(args["queries"]),
                "device": args.get("device", "all"),
            }
            if args.get("region"):
                task_data["ya_lrws"] = args["region"]
            if args.get("label"):
                task_data["label"] = args["label"]
            if args.get("s_std", True):
                task_data["s_std"] = 1
            if args.get("s_q"):
                task_data["s_q"] = 1
            
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Парсер подсказок (sug_par) ===
        elif name == "justmagic_suggestions_parser":
            task_data = {
                "task": "sug_par",
                "data": "\n".join(args["queries"]),
                "ya_lr": args.get("region", 213),
                "lang": args.get("lang", "ru"),
                "iter": min(max(args.get("iterations", 1), 1), 3),
            }
            if args.get("add_russian_letters"):
                task_data["f_rus"] = 1
            
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Тематический классификатор (temakl) ===
        elif name == "justmagic_thematic_classifier":
            task_data = {
                "task": "temakl",
                "data": "\n".join(args["queries"]),
            }
            if args.get("show_all_categories"):
                task_data["f_gall"] = 1
            
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Маркеры-онлайн (mark_onl) ===
        elif name == "justmagic_markers_online":
            lines = [
                p["url"] + ("\t" + "\t".join(p.get("queries", [])) if p.get("queries") else "")
                for p in args["pages"]
            ]
            task_data = {
                "task": "mark_onl",
                "data": "\n".join(lines),
                "data_base": "\n".join(args["base_queries"]),
                "ya_lr": args.get("region", 213),
                "mode": args.get("mode", "hard"),
                "min_pwr": min(max(args.get("min_power", 3), 3), 9),
            }
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Расширение семантики (grp_deep) ===
        elif name == "justmagic_expand_semantics":
            task_data = {
                "task": "grp_deep",
                "data": "\n".join(args["queries"]),
                "base": args.get("base", 3),
                "deep": min(max(args.get("depth", 1), 0), 9),
                "min_pwr": min(max(args.get("min_power", 3), 3), 9),
            }
            return await self._put_task(task_data, args.get("just_ask", False))
        
        # === Регулярки (rexp) ===
        elif name == "justmagic_regex_search":
            task_data = {
                "task": "rexp",
                "base": args.get("base", 3),
                "rexpa": args["pattern"],
            }
            if args.get("exclude_pattern"):
                task_data["rexpd"] = args["exclude_pattern"]
            
            return await self._put_task(task_data, args.get("just_ask", False))
        
        return {"err": "unknown_tool", "errtxt": f"Неизвестный инструмент: {name}"}
    
    async def close(self):
        await self.client.aclose()
