"""Работа с Блокнотом: текст печатается в окно в реальном времени.

Каждая фраза вставляется в открытый Блокнот через буфер обмена
(так работает и с кириллицей). Вставка идёт ТОЛЬКО если Блокнот
реально получил фокус, чтобы текст не улетел в другое окно.

Клавиши нажимаются через Windows API по кодам клавиш, поэтому
работает при любой раскладке (русской или английской).
"""

import re
import os
import time
import ctypes
import datetime
import subprocess

import pyautogui
import pyperclip
import pygetwindow as gw

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

VK_ALT, VK_CTRL, VK_ESC, VK_END = 0x12, 0x11, 0x1B, 0x23
VK_A, VK_C, VK_V = 0x41, 0x43, 0x56

note_win = None     # окно Блокнота, в которое сейчас пишем
note_buffer = []    # всё, что напечатал Джарвис (запасной вариант для сохранения)
note_name = None    # имя заметки по умолчанию


# ---------- клавиши (не зависят от раскладки) ----------

def _key(vk, up=False):
    user32.keybd_event(vk, 0, 2 if up else 0, 0)


def _hotkey(*vks):
    for vk in vks:
        _key(vk)
    time.sleep(0.03)
    for vk in reversed(vks):
        _key(vk, up=True)
    time.sleep(0.08)


# ---------- окна ----------

def _notepad_windows():
    wins = []
    for w in gw.getAllWindows():
        t = w.title or ""
        if "Блокнот" in t or "Notepad" in t:
            wins.append(w)
    return wins


def _hwnd(w):
    return getattr(w, "_hWnd", id(w))


def _alive(w):
    return w is not None and any(_hwnd(x) == _hwnd(w) for x in _notepad_windows())


def _is_foreground(win):
    try:
        return user32 is not None and user32.GetForegroundWindow() == _hwnd(win)
    except Exception:
        return False


def _force_foreground(win):
    """Переводит окно на передний план (трюк с Alt обходит блокировку фокуса Windows)."""
    if user32 is None:
        return False
    try:
        hwnd = _hwnd(win)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        _key(VK_ALT)
        _key(VK_ALT, up=True)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.25)
    except Exception as e:
        print("[фокус] ошибка:", e)
    return _is_foreground(win)


def _focus(win):
    """Ставит фокус на Блокнот и курсор в конец текста. True, если фокус получен."""
    ok = _force_foreground(win)

    if ok:
        # Alt-трюк мог активировать меню Блокнота, из-за чего Ctrl+V уходил в меню.
        # Escape закрывает меню, клик возвращает курсор в текстовую область.
        _hotkey(VK_ESC)
        try:
            pyautogui.click(win.left + win.width // 2, win.top + win.height // 2)
        except Exception:
            pass
        time.sleep(0.15)
        if not _is_foreground(win):
            ok = _force_foreground(win)
            if ok:
                _hotkey(VK_ESC)
    else:
        try:
            win.activate()
        except Exception:
            pass
        time.sleep(0.2)
        ok = _is_foreground(win)

    print("[фокус]", "ок" if ok else "НЕ УДАЛОСЬ получить фокус")
    if ok:
        _hotkey(VK_CTRL, VK_END)  # дописываем всегда в конец
    return ok


# ---------- блокнот ----------

def open_notepad():
    """Открывает Блокнот, если он ещё не открыт, иначе переключается на него."""
    global note_win, note_buffer, note_name
    wins = _notepad_windows()
    if not wins:
        open_new_notepad()
        return
    note_win = wins[0]
    note_buffer = []
    note_name = datetime.datetime.now().strftime("заметка_%Y-%m-%d_%H-%M-%S")
    _focus(note_win)


def open_new_notepad():
    """Всегда открывает новое пустое окно Блокнота."""
    global note_win, note_buffer, note_name
    before = {_hwnd(w) for w in _notepad_windows()}
    subprocess.Popen("notepad")

    win = None
    for _ in range(20):  # ждём до 10 секунд
        time.sleep(0.5)
        new = [w for w in _notepad_windows() if _hwnd(w) not in before]
        if new:
            win = new[0]
            break
    if win is None:
        # Блокнот мог открыться вкладкой в уже открытом окне
        wins = _notepad_windows()
        win = wins[0] if wins else None

    note_win = win
    note_buffer = []
    note_name = datetime.datetime.now().strftime("заметка_%Y-%m-%d_%H-%M-%S")
    if win:
        time.sleep(0.5)
        _focus(win)
    return win


def extract_note(cmd):
    """Берёт только текст после слова «запиши» / «напиши»."""
    m = re.search(r"(?:запиши|напиши)\w*(.*)", cmd, re.S)
    text = m.group(1) if m else cmd
    text = re.sub(r"\bв\s+(?:блокнот|открыт)\w*", "", text)
    text = text.replace("пожалуйста", "")
    return re.sub(r"\s+", " ", text).strip(" ,.")


def write_note(text, new_file=True):
    """Печатает текст в Блокнот.

    new_file=True  - начать новую заметку (если открыт пустой блокнот, пишем в него)
    new_file=False - дописать в текущую (для режима диктовки)
    """
    if new_file:
        if not (_alive(note_win) and not note_buffer):
            open_new_notepad()
    elif not _alive(note_win):
        open_new_notepad()

    note_buffer.append(text)  # запоминаем в любом случае

    if note_win is None:
        print("Блокнот не открылся, текст сохранён только в памяти")
        return

    if not _focus(note_win):
        # без фокуса не вставляем: текст улетел бы в другое окно
        print("Текст НЕ вставлен (нет фокуса), но запомнен для сохранения")
        return

    was_modified = (note_win.title or "").startswith("*")
    pyperclip.copy(text + "\n")
    _hotkey(VK_CTRL, VK_V)
    time.sleep(0.2)

    # Блокнот ставит «*» в заголовок после первой правки: так видно, что вставка дошла
    if not was_modified and not (note_win.title or "").startswith("*"):
        print("[вставка] Блокнот не принял текст (заголовок не изменился)")


# ---------- сохранение ----------

def desktop_path():
    home = os.path.expanduser("~")
    # OneDrive часто подменяет рабочий стол, поэтому проверяем его первым
    for p in (os.path.join("OneDrive", "Desktop"),
              os.path.join("OneDrive", "Рабочий стол"),
              "Desktop", "Рабочий стол"):
        full = os.path.join(home, p)
        if os.path.isdir(full):
            return full
    return home


def _read_window_text():
    """Забирает текст прямо из окна Блокнота (Ctrl+A, Ctrl+C), с учётом ручных правок."""
    try:
        if not _focus(note_win):
            return None
        pyperclip.copy("")
        _hotkey(VK_CTRL, VK_A)
        _hotkey(VK_CTRL, VK_C)
        time.sleep(0.3)
        text = pyperclip.paste()
        _hotkey(VK_CTRL, VK_END)  # снимаем выделение
        return text
    except Exception:
        return None


def save_note_to_desktop(filename=None):
    """Сохраняет текущую заметку на рабочий стол. Возвращает путь или None."""
    text = _read_window_text() if _alive(note_win) else None
    if not text:
        text = "\n".join(note_buffer)  # запасной вариант
    text = text.replace("\r\n", "\n")
    if not text.strip():
        return None

    name = filename or note_name or datetime.datetime.now().strftime("заметка_%Y-%m-%d_%H-%M-%S")
    if not name.endswith(".txt"):
        name += ".txt"
    dst = os.path.join(desktop_path(), name)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    return dst