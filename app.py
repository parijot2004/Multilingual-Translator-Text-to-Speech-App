import time
import base64
import tempfile
import os
import json
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from deep_translator import GoogleTranslator, MyMemoryTranslator, LibreTranslator
from gtts import gTTS
from gtts.lang import tts_langs

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def translator_langs_dict() -> Dict[str, str]:
    return GoogleTranslator().get_supported_languages(as_dict=True)

TRANS_NAME_TO_CODE = translator_langs_dict()            
TRANS_CODES = {code.lower() for code in TRANS_NAME_TO_CODE.values()}
TTS_CODE_TO_NAME = tts_langs()                          
TTS_CODES = {code.lower() for code in TTS_CODE_TO_NAME.keys()}

INDIAN_LANG_CODES = {"hi","bn","ta","te","kn","ml","mr","gu","pa","or","sa"}
SUPPORTED_CODES = sorted(set(TRANS_CODES & TTS_CODES) | (INDIAN_LANG_CODES & (TRANS_CODES | TTS_CODES)))

def code_to_label(code: str) -> str:
    code_l = code.lower()
    tr_name = next((n for n, c in TRANS_NAME_TO_CODE.items() if str(c).lower() == code_l), None)
    tts_name = TTS_CODE_TO_NAME.get(code_l)
    
    indian_lang_map = {
        "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
        "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi",
        "gu": "Gujarati", "pa": "Punjabi", "or": "Odia", "sa": "Sanskrit"
    }
    if code_l in indian_lang_map:
        return f"{indian_lang_map[code_l]} ({code})"
    
    if tr_name and tts_name and tr_name.lower() != tts_name.lower():
        return f"{tr_name.title()} / {tts_name} ({code})"
    if tr_name:
        return f"{tr_name.title()} ({code})"
    if tts_name:
        return f"{tts_name} ({code})"
    return code

def translate_router(text: str, target: str) -> Dict[str, Any]:
    last_err = None
    for provider, fn in [
        ("Google", lambda: GoogleTranslator(source="auto", target=target).translate(text)),
        ("MyMemory", lambda: MyMemoryTranslator(source="auto", target=target).translate(text)),
        ("Libre", lambda: LibreTranslator(source="auto", target=target).translate(text)),
    ]:
        try:
            out = fn()
            if out and isinstance(out, str) and out.strip():
                return {"translation": out, "provider": provider}
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All translators failed; last error: {last_err}")

def synthesize_tts(text: str, lang: str, slow: bool = False, tld: str = "com") -> bytes:
    tts = gTTS(text=text, lang=lang, slow=slow, tld=tld)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        tts.save(tmp.name)
        return open(tmp.name, "rb").read()

HISTORY_FILE = "history.json"

def save_history(entry: Dict[str, Any]):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

@app.get("/api/languages")
def list_languages():
    items = [{"code": c, "label": code_to_label(c)} for c in SUPPORTED_CODES]
    return {"languages": items}

@app.post("/api/translate")
def translate(payload: Dict[str, Any]):
    text = str(payload.get("text", "")).strip()
    target = str(payload.get("target", "en")).strip()
    slow = bool(payload.get("slow", False))
    tld = str(payload.get("tld", "com")).strip()

    if not text:
        return {"ok": False, "error": "No input text"}
    if target.lower() not in SUPPORTED_CODES:
        return {"ok": False, "error": f"Unsupported target: {target}"}

    started = time.time()
    routed = translate_router(text, target)
    elapsed = time.time() - started

    audio_bytes = synthesize_tts(routed["translation"], target, slow=slow, tld=tld)
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    target_name = next((n for n, c in TRANS_NAME_TO_CODE.items() if str(c).lower() == target.lower()), target)

    save_history({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input": text,
        "output": routed["translation"],
        "target": target,
        "provider": routed["provider"],
        "elapsed": round(elapsed, 2)
    })

    return {
        "ok": True,
        "translation": routed["translation"],
        "provider": routed["provider"],
        "target": target,
        "target_name": target_name,
        "elapsed": round(elapsed, 2),
        "audio_base64": audio_b64,
        "audio_mime": "audio/mpeg",
    }

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

# Run: uvicorn app:app --reload --port 8000
