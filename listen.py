import speech_recognition as sr
from faster_whisper import WhisperModel
from speak import say

r = sr.Recognizer()
r.pause_threshold = 1.5  # секунд тишины, после которых фраза считается законченной
mic = sr.Microphone()

with mic as src:
    r.adjust_for_ambient_noise(src, duration=1)

# "small" быстрее, "medium" точнее (лучше для длинной диктовки)
model = WhisperModel("small", device="cpu", compute_type="int8")


def listen():
    with mic as src:
        print("...слушаю")
        audio = r.listen(src, timeout=None, phrase_time_limit=None)

    with open("temp.wav", "wb") as f:
        f.write(audio.get_wav_data())

    segments, _ = model.transcribe(
        "temp.wav",
        language="ru",
        initial_prompt="Джарвис, открой ютуб. Джарвис, который час.",
        vad_filter=True,
    )
    text = "".join(seg.text for seg in segments).strip().lower()

    if text:
        print("Распознано:", text)
    else:
        print("Не разобрал речь")
        say("Не расслышал, повтори")
    return text
