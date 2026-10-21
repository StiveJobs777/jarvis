"""Подготовка текста для озвучки.

Silero не читает цифры и латиницу (молча пропускает), поэтому перед озвучкой
всё превращается в русские слова: 14:30 -> «четырнадцать тридцать»,
Discord -> «дискорд», CS2 -> «си эс два».
"""

import re

ONES_M = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
ONES_F = ["ноль", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
         "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
        "восемьдесят", "девяносто"]
HUND = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
        "восемьсот", "девятьсот"]
SCALES = [(("тысяча", "тысячи", "тысяч"), True),
          (("миллион", "миллиона", "миллионов"), False),
          (("миллиард", "миллиарда", "миллиардов"), False)]


def _plural(n, forms):
    n %= 100
    if 11 <= n <= 19:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def _triplet(n, fem):
    ones = ONES_F if fem else ONES_M
    words = []
    h, r = divmod(n, 100)
    if h:
        words.append(HUND[h])
    if r >= 20:
        words.append(TENS[r // 10])
        if r % 10:
            words.append(ones[r % 10])
    elif r >= 10:
        words.append(TEENS[r - 10])
    elif r:
        words.append(ones[r])
    return words


def num_to_words(n):
    if n < 0:
        return "минус " + num_to_words(-n)
    if n == 0:
        return "ноль"
    if len(str(n)) > 12:  # телефоны и прочие длинные числа читаем по цифрам
        return " ".join(ONES_M[int(d)] for d in str(n))
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        if i == 0:
            parts += _triplet(g, False)
        else:
            forms, fem = SCALES[i - 1]
            parts += _triplet(g, fem)
            parts.append(_plural(g, forms))
    return " ".join(parts)


# ---------- латиница ----------

WORDS = {
    "steam": "стим", "chrome": "хром", "google": "гугл", "discord": "дискорд",
    "telegram": "телеграм", "counter": "каунтер", "strike": "страйк", "cs": "си эс",
    "windows": "виндовс", "youtube": "ютуб", "notepad": "блокнот", "spotify": "спотифай",
    "word": "ворд", "excel": "эксель", "edge": "эдж", "opera": "опера", "code": "код",
    "visual": "визуал", "studio": "студио", "microsoft": "майкрософт", "launcher": "лаунчер",
    "zen": "зен", "browser": "браузер", "dota": "дота", "minecraft": "майнкрафт",
    "games": "геймс", "battlestate": "баттлстейт", "stalker": "сталкер", "obs": "о би эс",
    "desktop": "десктоп", "pc": "пи си", "ok": "окей",
}

_DIGRAPHS = [("sch", "ск"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("th", "т"),
             ("ph", "ф"), ("ck", "к"), ("ee", "и"), ("oo", "у"), ("ea", "и")]
_LETTERS = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
            "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
            "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
            "y": "и", "z": "з"}


def _latin_word(w):
    low = w.lower()
    if low in WORDS:
        return WORDS[low]
    for lat, cyr in _DIGRAPHS:
        low = low.replace(lat, cyr)
    out = []
    for i, ch in enumerate(low):
        if ch == "c" and i + 1 < len(low) and low[i + 1] in "eiy":
            out.append("с")
        else:
            out.append(_LETTERS.get(ch, ch))
    return "".join(out)


# ---------- главная функция ----------

def prepare(text):
    t = text
    t = re.sub(r"[*#`_~]", "", t)                           # остатки markdown
    t = re.sub(r"(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), t)  # S.T.A.L.K.E.R.
    t = re.sub(r"(?<=[^\W\d_])(?=\d)", " ", t)              # CS2 -> CS 2

    def time_repl(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if mi == 0:
            return f"{num_to_words(h)} ровно"
        if mi < 10:
            return f"{num_to_words(h)} ноль {num_to_words(mi)}"
        return f"{num_to_words(h)} {num_to_words(mi)}"
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", time_repl, t)

    t = re.sub(r"(\d+)\s*%",
               lambda m: f"{num_to_words(int(m.group(1)))} "
                         f"{_plural(int(m.group(1)), ('процент', 'процента', 'процентов'))}", t)

    def dec_repl(m):
        frac = m.group(2)
        zeros = len(frac) - len(frac.lstrip("0"))
        rest = frac.lstrip("0")
        words = ["ноль"] * zeros + ([num_to_words(int(rest))] if rest else [])
        return f"{num_to_words(int(m.group(1)))} запятая {' '.join(words)}"
    t = re.sub(r"(\d+)[.,](\d+)", dec_repl, t)

    t = re.sub(r"-?\d+", lambda m: num_to_words(int(m.group(0))), t)
    t = re.sub(r"[A-Za-z]+", lambda m: _latin_word(m.group(0)), t)
    return re.sub(r"\s+", " ", t).strip()