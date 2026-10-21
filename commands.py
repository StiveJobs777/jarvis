import re
import datetime
import subprocess
import webbrowser

from ddgs import DDGS

from speak import say
import notepad_tool as notepad


APPS = {
    "блокнот": "notepad",
    "калькулятор": "calc",
    "мой компьютер": "explorer",
    "проводник": "explorer",
    "диспетчер задач": "taskmgr",
}

SITES = {
    "ютуб": "https://youtube.com",
    "youtube": "https://youtube.com",
    "вк мессенджер": "https://web.vk.me",
    "вконтакте": "https://vk.com",
    "вк": "https://vk.com",
    "гугл": "https://google.com",
    "википедия": "https://wikipedia.org",
    "почту": "https://mail.google.com",
}

STOP_WORDS = ["джарвис", "открой", "запусти", "найди", "пожалуйста",
              "новую", "вкладку", "в браузере", "сайт"]


def find_url(query):
    results = DDGS().text(query, max_results=1)
    return results[0]["href"] if results else None


def clean_query(cmd):
    for w in STOP_WORDS:
        cmd = cmd.replace(w, "")
    return cmd.strip()


def extract_filename(cmd):
    """Достаёт имя файла из фраз вроде «сохрани под названием список покупок»."""
    m = re.search(
        r"(?:под\s+названием|под\s+именем|с\s+названием|с\s+именем|назови|называется|\bкак)\s+(.+)",
        cmd,
    )
    if not m:
        return None
    name = m.group(1)
    name = re.sub(r"на\s+рабоч\w+\s+стол\w*", "", name)
    name = re.sub(r'[\\/:*?"<>|]', "", name)  # запрещённые в именах файлов символы
    return name.strip(" ,.") or None


def handle(cmd):
    """Возвращает True, если команда выполнена."""
    if "время" in cmd:
        say(datetime.datetime.now().strftime("Сейчас %H:%M"))
        return True

    if "сохрани" in cmd:
        name = extract_filename(cmd)
        if notepad.save_note_to_desktop(name):
            say("Сохранил на рабочий стол" + (f" как {name}" if name else ""))
        else:
            say("Пока нечего сохранять")
        return True

    if "запиши" in cmd or "напиши" in cmd:
        note = notepad.extract_note(cmd)
        if note:
            say("Записываю")
            notepad.write_note(note)
        else:
            say("А что записать?")
        return True

    if "новый блокнот" in cmd or "новую заметку" in cmd:
        notepad.open_new_notepad()
        say("Открываю новый блокнот")
        return True

    if "открой" in cmd or "запусти" in cmd or "найди" in cmd:
        for name, url in SITES.items():
            if name in cmd:
                webbrowser.open(url)
                say(f"Открываю {name}")
                return True

        for name, exe in APPS.items():
            if name in cmd:
                if name == "блокнот":
                    notepad.open_notepad()
                else:
                    subprocess.Popen(exe)
                say(f"Запускаю {name}")
                return True

        query = clean_query(cmd)
        if query:
            say(f"Ищу {query}")
            url = find_url(query)
            if url:
                webbrowser.open(url)
                return True
            say("Ничего не нашёл")
            return True

    return False