import os
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()
api_key = os.getenv("ELEVENLABS_API_KEY")
if not api_key:
    raise SystemExit("ELEVENLABS_API_KEY is missing. Check your .env file.")

client = ElevenLabs(api_key=api_key)

# Any voice ID works. This one is a default ElevenLabs voice.
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"

audio = client.text_to_speech.convert(
    voice_id=VOICE_ID,
    text="Hello from uplink. The ElevenLabs key is working.",
    model_id="eleven_multilingual_v2",
)

with open("test_output.mp3", "wb") as f:
    for chunk in audio:
        f.write(chunk)

print("Saved test_output.mp3")