"""Поиск и запуск любых установленных приложений Windows.

Список берётся у самой системы (PowerShell Get-StartApps): это всё, что есть
в меню «Пуск», включая программы из Microsoft Store. Название, которое ты
произнёс, сравнивается с этим списком «на слух»: русские слова
транслитерируются («дискорд» -> discord), плюс есть словарь псевдонимов.
"""

import os
import re
import json
import time
import difflib
import threading
import subprocess

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps_cache.json")
CACHE_TTL = 7 * 24 * 3600   # через неделю список обновится сам
THRESHOLD = 0.72            # ниже этой похожести приложение не запускаем

# служебные ярлыки, которые не нужны
SKIP_WORDS = ("uninstall", "удалить", "удаление", "деинсталл", "readme",
              "справка", "help", "license", "лицензи", "release notes")

# как говорим -> как это называется в системе (можно дописывать свои)
ALIASES = {
    "хром": "chrome",
    "гугл хром": "chrome",
    "эдж": "edge",
    "опера": "opera",
    "стим": "steam",
    "дискорд": "discord",
    "телеграм": "telegram",
    "телеграмм": "telegram",
    "ватсап": "whatsapp",
    "вацап": "whatsapp",
    "вайбер": "viber",
    "скайп": "skype",
    "зум": "zoom",
    "спотифай": "spotify",
    "ворд": "word",
    "эксель": "excel",
    "пауэрпоинт": "powerpoint",
    "павер поинт": "powerpoint",
    "аутлук": "outlook",
    "вс код": "visual studio code",
    "визуал студио код": "visual studio code",
    "обс": "obs studio",
    "фотошоп": "photoshop",
    "пайчарм": "pycharm",
    "зен": "zen",
    "пейнт": "paint",
}

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

RESCAN_COOLDOWN = 600  # промах не чаще раза в 10 минут вызывает пересканирование

_lock = threading.Lock()
_apps = None
_last_scan = 0.0


def translit(s):
    return "".join(_CYR.get(ch, ch) for ch in s)


def _norm(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[™®©]", "", s)
    s = re.sub(r"[^\w\s+#.]", " ", s)  # + # . оставляем: c++, notepad++
    return re.sub(r"\s+", " ", s).strip()


# ---------- список приложений ----------

def _scan():
    """Спрашивает у Windows все приложения из меню «Пуск» и кэширует результат."""
    script = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
              "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8-sig", timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = r.stdout.strip()
    data = json.loads(out) if out else []
    if isinstance(data, dict):  # одно приложение PowerShell отдаёт не списком
        data = [data]

    apps = []
    for a in data:
        name, app_id = a.get("Name"), a.get("AppID")
        if not name or not app_id:
            continue
        if any(w in name.lower() for w in SKIP_WORDS):
            continue
        apps.append({"name": name, "id": app_id})

    global _last_scan
    _last_scan = time.time()
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"time": _last_scan, "apps": apps}, f, ensure_ascii=False)
    return apps


def get_apps(refresh=False):
    """Возвращает (список приложений, был ли он только что получен заново)."""
    global _apps, _last_scan
    with _lock:
        if not refresh and _apps is not None:
            return _apps, False

        if not refresh and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, encoding="utf-8") as f:
                    cache = json.load(f)
                if time.time() - cache["time"] < CACHE_TTL:
                    _apps = cache["apps"]
                    _last_scan = cache["time"]
                    return _apps, False
            except Exception:
                pass

        try:
            _apps = _scan()
        except Exception as e:
            print("Не удалось получить список приложений:", e)
            _apps = _apps or []
        return _apps, True


def warm_up():
    """Загружает список в фоне, чтобы первая команда не тормозила."""
    threading.Thread(target=get_apps, daemon=True).start()


def rescan():
    """Принудительно перечитывает список (после установки новой программы)."""
    apps, _ = get_apps(refresh=True)
    return len(apps)


# ---------- поиск ----------

def _variants(q):
    v = [q, translit(q)]
    if q in ALIASES:
        v.append(ALIASES[q])
    return v


def _ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score(variants, name):
    name_l = _norm(name)
    cands = {name_l, translit(name_l)}
    best = 0.0
    for q in variants:
        for cand in cands:
            best = max(best, _ratio(q, cand))
            if len(q) >= 3 and q in cand:
                best = max(best, 0.9)
            for word in cand.split():
                best = max(best, _ratio(q, word) - 0.05)  # слово из названия чуть слабее целого
    return best


def _best_match(variants, apps):
    best = None
    for a in apps:
        key = (_score(variants, a["name"]), -len(a["name"]))  # при равенстве берём короче
        if best is None or key > best[0]:
            best = (key, a)
    if best and best[0][0] >= THRESHOLD:
        return best[1]
    return None


def find_app(query):
    """Находит приложение по произнесённому названию или возвращает None."""
    q = _norm(query)
    if not q:
        return None
    variants = _variants(q)

    apps, fresh = get_apps()
    app = _best_match(variants, apps)
    if app is None and not fresh and time.time() - _last_scan > RESCAN_COOLDOWN:
        # возможно, программу установили недавно: перечитываем список и пробуем ещё раз
        apps, _ = get_apps(refresh=True)
        app = _best_match(variants, apps)
    return app


def launch(app):
    os.startfile("shell:AppsFolder\\" + app["id"])