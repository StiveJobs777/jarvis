import re
import difflib

from listen import listen
from speak import say
from commands import handle, extract_filename
from brain import ask_ai
import notepad_tool as notepad

WAKE = "джарвис"
DICTATION_STOP = ["стоп", "хватит", "закончили"]


def is_wake(word, threshold=0.55):
    """Похоже ли слово на «Джарвис» (Whisper часто его искажает)."""
    clean = word.strip(".,!?«»\"")
    return difflib.SequenceMatcher(None, clean, WAKE).ratio() >= threshold


def find_wake(text):
    for word in text.split():
        if is_wake(word):
            return word
    return None


def dictation_mode():
    """Пишет в заметку всё подряд, без слова «Джарвис».

    Выходит, когда:
    - сказали «стоп» / «хватит» (короткая фраза) -> возвращает None
    - фраза начинается с «Джарвис» -> возвращает текст команды,
      сама эта фраза в заметку НЕ попадает
    """
    say("Диктую. Скажи стоп, когда закончишь")
    while True:
        text = listen()
        if not text:
            continue

        words = text.split()
        if is_wake(words[0], 0.6):
            return text.replace(words[0], "", 1).strip(" ,.")

        if len(words) <= 3 and any(w in text for w in DICTATION_STOP):
            say("Записал")
            return None

        # печатаем в блокнот сразу, фраза за фразой
        notepad.write_note(text, new_file=False)


def run(cmd):
    """Выполняет команду. Возвращает False, если пора выключаться."""
    while cmd is not None:
        if not cmd:
            # сказали только имя: ждём команду следующей фразой
            say("Слушаю")
            cmd = listen().strip(" ,.")
            if not cmd:
                return True

        if "выключись" in cmd:
            say("До связи")
            return False

        if "запиши" in cmd or "напиши" in cmd:
            handle(cmd)             # новая заметка + первая фраза
            cmd = dictation_mode()  # дальше пишем всё подряд
            continue

        # «сохрани ... под названием» и имя не расслышали / оно ушло отдельной фразой
        if ("сохрани" in cmd and not extract_filename(cmd)
                and re.search(r"назван|назови|имен", cmd)):
            say("Как назвать файл?")
            name = listen().strip(" ,.")
            if name:
                cmd = cmd + " " + name

        if not handle(cmd):
            say(ask_ai(cmd))
        return True

    return True


say("Система запущена")

while True:
    text = listen()
    wake_word = find_wake(text)
    if not wake_word:
        continue

    cmd = text.replace(wake_word, "", 1).strip(" ,.")

    if not run(cmd):
        break