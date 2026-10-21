"""Поиск и запуск любых установленных приложений Windows.

Список берётся у самой системы (PowerShell Get-StartApps): это всё, что есть
в меню «Пуск», включая программы из Microsoft Store. Название, которое ты
произнёс, сравнивается с этим списком «на слух»: русские слова
транслитерируются («дискорд» -> discord), плюс есть словарь псевдонимов.
"""

import os
import re
import glob
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
              "справка", "help", "license", "лицензи", "release notes",
              "documentation", "website", "manual", "руководство", "документация",
              "посетить", "регистрация", "новости в последней версии",
              "check for updates", "reload configuration")
# ярлыки-ссылки и документы (сайты, .txt, .pdf...): запускать их как «приложения» не нужно
SKIP_ID_PREFIX = ("http://", "https://", "file://")
SKIP_ID_EXT = (".url", ".txt", ".chm", ".pdf", ".ini", ".html", ".htm", ".rtf")
# служебное в библиотеке Steam, играми не является
SKIP_STEAM = ("redistributable", "steamworks", "runtime", "proton", "steam linux")

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
    "блокнот": "notepad",
    "проводник": "explorer",
    # игры
    "кс 2": "counter-strike 2",
    "цс 2": "counter-strike 2",
    "cs 2": "counter-strike 2",
    "си эс 2": "counter-strike 2",
    "контр страйк 2": "counter-strike 2",
    "контрстрайк 2": "counter-strike 2",
    "дота": "dota 2",
    "дота 2": "dota 2",
    "тарков": "battlestate games launcher",
    "майнкрафт": ("minecraft", "tlauncher"),
}

_NUMS = {"один": "1", "два": "2", "три": "3", "четыре": "4", "пять": "5",
         "шесть": "6", "семь": "7", "восемь": "8", "девять": "9", "десять": "10"}

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

def _ok(app):
    name, app_id = app["name"].lower(), app["id"].lower()
    if app_id.startswith(SKIP_ID_PREFIX) or app_id.endswith(SKIP_ID_EXT):
        return False
    return not any(w in name for w in SKIP_WORDS)


def _read_manifests(libs):
    """Игры Steam: читает appmanifest_*.acf в папках библиотек."""
    games, seen = [], set()
    for lib in libs:
        for mf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                with open(mf, encoding="utf-8", errors="ignore") as f:
                    t = f.read()
            except OSError:
                continue
            m_id = re.search(r'"appid"\s+"(\d+)"', t)
            m_name = re.search(r'"name"\s+"([^"]+)"', t)
            if not m_id or not m_name or m_id.group(1) in seen:
                continue
            if any(w in m_name.group(1).lower() for w in SKIP_STEAM):
                continue
            seen.add(m_id.group(1))
            games.append({"name": m_name.group(1), "id": "steam:" + m_id.group(1)})
    return games


def _steam_games():
    """Находит Steam и все его библиотеки (на разных дисках тоже)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = winreg.QueryValueEx(k, "SteamPath")[0]
    except Exception:
        return []
    libs = [steam]
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"),
                  encoding="utf-8", errors="ignore") as f:
            libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
    except OSError:
        pass
    return _read_manifests(libs)


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
        apps.append({"name": name, "id": app_id})

    global _last_scan
    _last_scan = time.time()
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"time": _last_scan, "apps": apps}, f, ensure_ascii=False)
    return apps


def _finish(apps):
    """Убирает мусор и добавляет игры Steam (они не лежат в меню «Пуск»)."""
    return [a for a in apps if _ok(a)] + _steam_games()


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
                    _apps = _finish(cache["apps"])
                    _last_scan = cache["time"]
                    return _apps, False
            except Exception:
                pass

        try:
            _apps = _finish(_scan())
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

def _prepare(q):
    """«кс два» -> «кс 2», «цс2» -> «цс 2»."""
    q = " ".join(_NUMS.get(w, w) for w in q.split())
    return re.sub(r"(?<=[^\W\d_])(?=\d)", " ", q)


def _variants(q):
    v = [q, translit(q)]
    alias = ALIASES.get(q)
    if alias:
        v += [_norm(a) for a in ([alias] if isinstance(alias, str) else alias)]
    return v


def _ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score(variants, name):
    name_l = _norm(name)
    nodots = name_l.replace(".", "")
    cands = {name_l, translit(name_l), nodots, translit(nodots)}
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
    q = _prepare(_norm(query))
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
    if app["id"].startswith("steam:"):
        os.startfile("steam://rungameid/" + app["id"][6:])
    else:
        os.startfile("shell:AppsFolder\\" + app["id"])


# ---------- закрытие ----------

# окна этих процессов не трогаем: там живёт сам Джарвис
PROTECTED_EXE = {"python.exe", "pythonw.exe", "py.exe", "windowsterminal.exe", "wt.exe",
                 "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "openconsole.exe"}
# системные процессы: окна закрыть можно, убивать нельзя
NEVER_KILL = {"explorer.exe", "applicationframehost.exe", "textinputhost.exe",
              "searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe"}


def _windows():
    """Все видимые окна верхнего уровня: (hwnd, заголовок, pid, класс окна)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                title = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, title, n + 1)
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((hwnd, title.value, pid.value, cls.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def _exe_of(pid):
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def _candidates():
    wins = []
    me = {os.getpid(), os.getppid()}
    for hwnd, title, pid, cls in _windows():
        if pid in me:
            continue
        exe = os.path.basename(_exe_of(pid)).lower()
        if not exe or exe in PROTECTED_EXE:
            continue
        if exe == "explorer.exe" and cls != "CabinetWClass":  # рабочий стол и панель задач не трогаем
            continue
        wins.append({"hwnd": hwnd, "title": title, "pid": pid, "exe": exe})
    return wins


def _title_score(variants, title):
    """Заголовок целиком сравниваем строго, иначе вкладка браузера
    «Дискорд — как установить» сойдёт за приложение Discord.
    Название программы обычно стоит в конце заголовка: «... - Google Chrome»."""
    full = _norm(title)
    best = max(max(_ratio(v, full), _ratio(v, translit(full))) for v in variants)
    parts = re.split(r"\s[-–—]\s", title)
    if len(parts) > 1:
        best = max(best, _score(variants, parts[-1]))
    return best


def _pick(variants, wins):
    best = None
    for w in wins:
        stem = w["exe"][:-4] if w["exe"].endswith(".exe") else w["exe"]
        sc = max(_score(variants, stem), _title_score(variants, w["title"]))
        if best is None or sc > best[0]:
            best = (sc, w)
    if not best or best[0] < THRESHOLD:
        return None, []
    exe = best[1]["exe"]
    return exe, [w for w in wins if w["exe"] == exe]


def close_app(query, force=False):
    """Закрывает окна приложения. Мягко (как крестик: программа успеет спросить
    про сохранение) или принудительно. Возвращает имя процесса или None."""
    q = _prepare(_norm(query))
    if not q:
        return None
    exe, group = _pick(_variants(q), _candidates())
    if not exe:
        return None

    if force and exe not in NEVER_KILL:
        subprocess.run(["taskkill", "/IM", exe, "/F", "/T"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        import ctypes
        for w in group:
            ctypes.windll.user32.PostMessageW(w["hwnd"], 0x0010, 0, 0)  # WM_CLOSE
    return exe