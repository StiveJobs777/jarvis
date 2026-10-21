import os
import tempfile

import torch
import soundfile as sf
import pygame

device = torch.device("cpu")
model, _ = torch.hub.load(
    repo_or_dir="snakers4/silero-models",
    model="silero_tts",
    language="ru",
    speaker="v4_ru",
)
model.to(device)

SPEAKER = "aidar"  # мужской; ещё: eugene, baya, kseniya, xenia
SAMPLE_RATE = 48000

pygame.mixer.init()
path = os.path.join(tempfile.gettempdir(), "jarvis_tts.wav")


def say(text):
    print("Джарвис:", text)
    audio = model.apply_tts(text=text, speaker=SPEAKER, sample_rate=SAMPLE_RATE)
    sf.write(path, audio.numpy(), SAMPLE_RATE)
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.music.unload()
