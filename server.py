"""
SafeToy AI — Low-latency Gnani pipeline for the Great Indian AI Internship Challenge.
Deadline: Nov 10, 2026, 11:59 PM IST.

What changed vs the original repo (Whisper + Groq Llama + Edge TTS):
  STT:  Whisper (Groq)            -> Prisma v2.5 (Gnani, gnani-vachana)
  TTS:  Edge TTS (localhost:8000) -> Timbre v2.5 (Gnani, SSE streaming)
  LLM:  llama-3.3-70b, stream=False, max_tokens=1024
        -> Evon v3.3 (Gnani, via local vLLM) FIRST when available, with
           Groq llama-3.1-8b-instant as automatic fallback.
           Evon: gnani/gnani-evon-v3.3-30B-A3B, 30B MoE / ~3.5B active,
           128K context, thinking OFF for kid answers (enable_thinking=False),
           temperature 0.6, max_tokens=120, stream=True.
           Groq fallback: llama-3.1-8b-instant, temperature 0.7.
           Set LLM_PROVIDER=groq | evon | auto (default groq = safest for demo).
        + sentence-wise TTS: speak sentence 1 while sentence 2 is still generating.

Why this is fast (the latency fix):
  Old: save wav to disk -> full STT -> full LLM -> emotion (blocks) -> full TTS
       -> ffmpeg convert -> ESP32 does a 2nd GET for the audio.  ~3-5 s silence.
  New: in-memory bytes only, no disk for input, no ffmpeg, emotion runs in
       parallel and never blocks the reply, LLM streams, each finished
       sentence goes to Timbre SSE immediately. Target: first sound in ~0.9-1.2 s.

ESP32 COMPATIBILITY — NO firmware change needed:
  POST /upload takes the same multipart field "audio" and returns the same
  JSON keys the original .ino expects: text, ai_response, emotion,
  has_audio, audio_url. Just update server_url in esp32_robot.ino to your
  PC IP, e.g. http://192.168.1.5:5050 — keep your working wiring as-is.

Verified Gnani API (checked against installed gnani-vachana on 2026-11-08):
  from gnani.stt import GnaniSTTClient
    GnaniSTTClient(api_key=...).transcribe_bytes(
        audio_bytes, filename="audio.wav", language_code="en-IN")
    -> dict with key "transcript". Default model is Prisma v2.5.
    Supported: en-IN, hi-IN, gu-IN, ta-IN, kn-IN, te-IN, mr-IN, bn-IN, ml-IN, pa-IN.
  from gnani.tts import GnaniTTSStreamClient, AudioConfig
    GnaniTTSStreamClient(api_key=...).synthesize_stream(
        text, voice="Nalini", model="timbre-v2.5", language="hi-IN",
        audio_config=AudioConfig(sample_rate=24000))
    -> Iterator[bytes] of raw PCM (no WAV header). We wrap it as WAV ourselves.
    Timbre v2.5 voices include Nalini, Kaveri, Asmita, Deepak, Pranav, etc. (42 total).

Env (.env):
  GNANI_API_KEY=...   # from app.gnani.ai/voice — 5,000 challenge credits
  GROQ_API_KEY=...    # Groq fallback LLM; keep your existing Groq key
  GNANI_STT_LANG=en-IN        # en-IN = Hinglish (Latin), hi-IN = Hindi
  GNANI_TTS_VOICE=Nalini
  GNANI_TTS_LANG=hi-IN        # auto-detected per reply if left empty
  LLM_PROVIDER=groq           # groq | evon | auto — see EVON_SETUP.md
  LLM_MODEL=llama-3.1-8b-instant   # Groq model
  EVON_BASE_URL=http://localhost:8000/v1  # vLLM serve URL for Evon
  EVON_MODEL=gnani/gnani-evon-v3.3-30B-A3B
  EVON_API_KEY=evon-local     # vLLM needs any non-empty key; it is not checked
  EVON_ENABLE_THINKING=0      # keep 0 for kid answers — reasoning is slow
  MOCK_GNANI=0                # set to 1 to test the full pipeline with no keys
  SAVE_AUDIO=0                # set to 1 to also save mic_input/ files for debug

Run:
  pip install -r requirements.txt
  python server.py   # http://localhost:5050, no second tts_server.py needed
"""

import io
import logging
import os
import re
import sqlite3
import struct
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, send_file

# override=True: a stale GROQ_API_KEY in Windows user env vars must not
# silently beat the .env file (this caused a 401 in testing).
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_PATH = "conversations.db"
AUDIO_DIR = "audio_responses"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ---------------------------------------------------------------- config
GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
STT_LANG = os.getenv("GNANI_STT_LANG", "en-IN")          # Hinglish default
TTS_VOICE = os.getenv("GNANI_TTS_VOICE", "Nalini")       # Hindi female, Timbre v2.5
TTS_MODEL = os.getenv("GNANI_TTS_MODEL", "timbre-v2.5")
TTS_LANG_ENV = os.getenv("GNANI_TTS_LANG", "")           # "" = auto-detect per reply
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")  # fast Groq chat model
# NOTE: llama-3.1-8b-instant was deprecated/removed from Groq (tested 2026-11-08).
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "120"))
# --- Evon v3.3 (Gnani LLM) — via a local vLLM OpenAI-compatible server.
# Evon is NOT on the Gnani API platform, so there is no Gnani API key for it.
# Run it yourself: vllm serve gnani/gnani-evon-v3.3-30B-A3B  (see EVON_SETUP.md)
# then set LLM_PROVIDER=evon or auto. Groq stays as the automatic fallback
# when the vLLM server is down, so a dead Evon never kills the demo.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower().strip()  # groq | evon | auto
EVON_BASE_URL = os.getenv("EVON_BASE_URL", "http://localhost:8000/v1").rstrip("/")
EVON_MODEL = os.getenv("EVON_MODEL", "gnani/gnani-evon-v3.3-30B-A3B")
EVON_API_KEY = os.getenv("EVON_API_KEY", "evon-local")
EVON_ENABLE_THINKING = os.getenv("EVON_ENABLE_THINKING", "0") == "1"
EVON_TEMPERATURE = float(os.getenv("EVON_TEMPERATURE", "0.6"))
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.7"))
# Last provider that actually answered — reported in /upload and /health.
# Thread-safe enough for this single-robot demo (one turn at a time).
LAST_LLM_PROVIDER = {"name": LLM_PROVIDER, "model": LLM_MODEL}
MOCK = os.getenv("MOCK_GNANI", "0") == "1" or not GNANI_API_KEY
SAVE_AUDIO = os.getenv("SAVE_AUDIO", "0") == "1"
SAMPLE_RATE = 24000  # ESP32 speaker path in the original .ino expects 24k WAV

if MOCK:
    logger.warning("MOCK MODE: no GNANI_API_KEY — STT/TTS are faked so you can test "
                   "timing + flow with no credits. Set GNANI_API_KEY for the real run.")

# Lazy singletons — creating a client per request adds ~100ms. Reuse them.
_stt_client = None
_tts_stream_client = None
_tts_rest_client = None
_llm_client = None
_llm_evon_client = None
_client_lock = threading.Lock()


def get_stt_client():
    global _stt_client
    if _stt_client is None:
        with _client_lock:
            if _stt_client is None:
                from gnani.stt import GnaniSTTClient
                _stt_client = GnaniSTTClient(api_key=GNANI_API_KEY)
    return _stt_client


def get_tts_stream_client():
    global _tts_stream_client
    if _tts_stream_client is None:
        with _client_lock:
            if _tts_stream_client is None:
                from gnani.tts import GnaniTTSStreamClient
                _tts_stream_client = GnaniTTSStreamClient(api_key=GNANI_API_KEY)
    return _tts_stream_client


def get_tts_rest_client():
    global _tts_rest_client
    if _tts_rest_client is None:
        with _client_lock:
            if _tts_rest_client is None:
                from gnani.tts import GnaniTTSClient
                _tts_rest_client = GnaniTTSClient(api_key=GNANI_API_KEY)
    return _tts_rest_client


def get_llm_client():
    """Groq client (backward-compatible name — used by /api/report)."""
    global _llm_client
    if _llm_client is None:
        with _client_lock:
            if _llm_client is None:
                from groq import Groq
                _llm_client = Groq(api_key=GROQ_API_KEY)
    return _llm_client


def get_evon_llm_client():
    """Evon v3.3 client — plain OpenAI client pointed at local vLLM.

    vLLM's `vllm serve` exposes an OpenAI-compatible API at
    EVON_BASE_URL (default http://localhost:8000/v1), so the standard
    OpenAI client works with no Gnani-specific code. vLLM does not check
    the key, but the client requires a non-empty one.
    """
    global _llm_evon_client
    if _llm_evon_client is None:
        with _client_lock:
            if _llm_evon_client is None:
                from openai import OpenAI
                _llm_evon_client = OpenAI(base_url=EVON_BASE_URL, api_key=EVON_API_KEY)
    return _llm_evon_client


def _evon_available(timeout_s=2.0):
    """Cheap pre-flight check: is the vLLM server up?

    GET {EVON_BASE_URL}/models. Returns True only on HTTP 200.
    Called only when LLM_PROVIDER is evon/auto, once per turn, before
    streaming — so a dead Evon costs at most ~2s and then falls back to
    Groq, instead of failing the child's turn. Never raises.
    """
    try:
        r = requests.get(f"{EVON_BASE_URL}/models",
                         headers={"Authorization": f"Bearer {EVON_API_KEY}"},
                         timeout=timeout_s)
        return r.status_code == 200
    except Exception as e:
        logger.warning("Evon server not reachable at %s: %s", EVON_BASE_URL, e)
        return False


def resolve_llm_provider():
    """Pick the LLM for this turn. Returns (provider_name, client, model).

    groq -> Groq only. evon/auto -> Evon if its vLLM server answers,
    otherwise Groq with a warning log. This is the fallback that keeps
    the demo alive when Evon is down, slow to start, or not yet approved
    on Hugging Face.
    """
    if LLM_PROVIDER in ("evon", "auto"):
        if _evon_available():
            return "evon", get_evon_llm_client(), EVON_MODEL
        logger.warning("LLM_PROVIDER=%s but Evon is down — falling back to Groq",
                       LLM_PROVIDER)
    return "groq", get_llm_client(), LLM_MODEL


# ---------------------------------------------------------------- safety
# Kept from the original server.py, plus a few Hindi/Hinglish additions.
UNSAFE_WORDS = [
    "kill", "death", "die", "suicide", "hurt", "harm", "weapon", "gun",
    "knife", "bomb", "attack", "violence", "blood", "abuse", "nude",
    "naked", "sex", "porn", "drug", "alcohol", "cigarette", "smoke",
    "drunk", "self harm", "cut", "burn", "terrorist", "rape", "assault",
    "molest", "maar", "khoon", "chaku", "bandook",
]
PROFANITY_WORDS = [
    "shit", "fuck", "bitch", "bastard", "asshole", "cunt", "whore",
    "slut", "fucker", "fucking", "bullshit", "dammit",
]
SAFE_RESPONSES = {
    "dangerous": "Main is baare mein baat nahi kar sakta. Chalo kuch aur seekhte hain! Tum kya seekhna chahte ho?",
    "inappropriate": "Chalo friendly aur fun baatein karte hain! Kuch aur poochna hai?",
    "profanity": "Oops! Achhe words use karte hain. Phir se try karein?",
}


def check_response_safety(text):
    text_lower = (text or "").lower()
    for word in UNSAFE_WORDS:
        if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text_lower):
            return False, "dangerous"
    for word in PROFANITY_WORDS:
        if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text_lower):
            return False, "profanity"
    return True, None


def get_safe_response(flag_type):
    return SAFE_RESPONSES.get(flag_type, SAFE_RESPONSES["inappropriate"])


# ---------------------------------------------------------------- emotion
# Fast, no-model heuristic — runs in <5ms in a parallel thread and NEVER
# blocks the reply. The original local BERT (torch + transformers) added
# seconds of startup and ~200ms per turn; plug it back only if you need it
# and have time to measure it. Keyword lists cover English + Hinglish.
EMOTION_KEYWORDS = {
    "happy": ["happy", "khush", "maza", "mazaa", "great", "awesome", "yay", "achha laga", "bahut achha"],
    "excited": ["excited", "wow", "amazing", "yay", "jaldi", "kamaal"],
    "sad": ["sad", "dukhi", "dukh", "cry", "rona", "upset", "bura laga", "akela"],
    "angry": ["angry", "gussa", "naraz", "mad", "irritated"],
    "scared": ["scared", "darr", "dar", "afraid", "bhoot", "andhera"],
    "confused": ["confused", "samajh nahi", "confuse", "kya matlab"],
}


def predict_emotion_fast(text):
    t = (text or "").lower()
    for label, words in EMOTION_KEYWORDS.items():
        if any(w in t for w in words):
            return label
    return "neutral"


# ---------------------------------------------------------------- text / audio helpers
_SENTENCE_END = re.compile(r"(.+?[.!?।\n])\s*", re.DOTALL)


def split_sentences(text):
    """Split streamed LLM text into speakable sentences, keeping the end mark."""
    parts = [p.strip() for p in _SENTENCE_END.findall(text or "")]
    rest = _SENTENCE_END.sub("", text or "").strip()
    if rest:
        parts.append(rest)
    return [p for p in parts if p]


def has_devanagari(text):
    return any("\u0900" <= ch <= "\u097f" for ch in (text or ""))


def tts_language_for(text):
    if TTS_LANG_ENV:
        return TTS_LANG_ENV
    return "hi-IN" if has_devanagari(text) else "en-IN"


def wav_header(data_len, sample_rate=SAMPLE_RATE, channels=1, sample_width=2):
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE", b"fmt ", 16, 1, channels,
        sample_rate, byte_rate, block_align, sample_width * 8, b"data", data_len,
    )


def pcm_to_wav(pcm_bytes):
    return wav_header(len(pcm_bytes)) + pcm_bytes


def wav_bytes_to_pcm(wav_bytes):
    """Strip a 44-byte RIFF header if present; otherwise assume raw PCM."""
    if len(wav_bytes) > 44 and wav_bytes[:4] == b"RIFF":
        return wav_bytes[44:]
    return wav_bytes


def mock_pcm(duration_s=0.6, freq=440.0):
    """Fake TTS audio for MOCK mode: a short sine tone at 24kHz, 16-bit mono."""
    import math
    n = int(SAMPLE_RATE * duration_s)
    return b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
        for i in range(n)
    )


# ---------------------------------------------------------------- Gnani calls
def gnani_transcribe(audio_bytes):
    """Prisma v2.5 STT. Returns (text, elapsed_ms). Raises on API error."""
    if MOCK:
        return "mujhe ek kahani sunao dinosaur wali", 5.0
    t0 = time.monotonic()
    try:
        result = get_stt_client().transcribe_bytes(
            audio_bytes, filename="audio.wav", language_code=STT_LANG,
        )
    except Exception:
        # Hinglish heard as Hindi (or vice versa) — one retry in the other lang.
        other = "hi-IN" if STT_LANG == "en-IN" else "en-IN"
        logger.info("STT retry in %s", other)
        result = get_stt_client().transcribe_bytes(
            audio_bytes, filename="audio.wav", language_code=other,
        )
    text = ""
    if isinstance(result, dict):
        text = str(result.get("transcript") or result.get("text") or "").strip()
    else:
        text = str(result).strip()
    return text, (time.monotonic() - t0) * 1000


def gnani_tts_sentence(sentence):
    """One sentence -> raw PCM bytes via Timbre v2.5 SSE streaming.

    synthesize_stream yields raw PCM chunks as they arrive (no WAV header).
    We collect one short sentence, so this returns in ~200-400ms and the
    next sentence can already be synthesising in parallel.
    Falls back to the REST client if streaming fails.
    """
    if MOCK:
        return mock_pcm(duration_s=max(0.4, min(1.5, len(sentence) * 0.04)))
    lang = tts_language_for(sentence)
    try:
        from gnani.tts import AudioConfig
        cfg = AudioConfig(sample_rate=SAMPLE_RATE, encoding="linear_pcm",
                          num_channels=1, sample_width=2, container="wav")
        chunks = get_tts_stream_client().synthesize_stream(
            sentence, voice=TTS_VOICE, model=TTS_MODEL, language=lang,
            audio_config=cfg,
        )
        return b"".join(chunks)
    except Exception as e:
        logger.warning("Timbre SSE failed (%s), falling back to REST", e)
        wav = get_tts_rest_client().synthesize(
            sentence, voice=TTS_VOICE, model=TTS_MODEL, language=lang,
            audio_config=AudioConfig(sample_rate=SAMPLE_RATE),
        )
        return wav_bytes_to_pcm(wav)


# ---------------------------------------------------------------- LLM
ROBOT_PROMPT = """You are SafeToy, a safe friendly AI dost for children aged 6-14 in India.
Answer in the SAME language as the child: Hinglish (Hindi in Roman letters) if they speak Hinglish, Hindi if they speak Hindi, simple English otherwise.
Use very simple words. Keep it to 2-3 SHORT sentences, max 40 words total. No emojis.
Be warm like a caring teacher. If the child is sad or scared, comfort them first.
Never give harmful, unsafe or inappropriate content. If asked something unsafe, gently refuse and suggest a fun safe topic instead."""

# Short history keeps the LLM fast: every token of history is re-sent each turn.
MAX_HISTORY_TURNS = 6


def llm_stream_reply(user_text, history_rows, warning_note=""):
    """Yield (cumulative_text, first_token_ms, total_ms_or_None) per chunk.

    Yields on EVERY chunk so the caller can submit a finished sentence to
    Timbre the moment its full stop arrives — while the LLM is still
    generating the next sentence. The final yield has total_ms set.
    In MOCK mode yields the reply in 3 sentence-sized chunks.
    """
    if MOCK or (not GROQ_API_KEY and LLM_PROVIDER == "groq"):
        LAST_LLM_PROVIDER.update({"name": "mock", "model": "mock"})
        reply = "Ek chhota dinosaur tha, uska naam Chintu tha. Chintu ko khelna bahut pasand tha, aur woh roz naye dost banata tha!"
        # Fake streaming: one yield per sentence, so the overlap path is exercised.
        acc = ""
        for part in split_sentences(reply):
            acc = (acc + " " + part).strip()
            yield acc, 5.0, None
        yield acc, 5.0, 10.0
        return
    messages = [{"role": "system", "content": ROBOT_PROMPT}]
    for row in history_rows[-MAX_HISTORY_TURNS:]:
        messages.append({"role": "user", "content": row["user_message"]})
        messages.append({"role": "assistant", "content": row["ai_response"]})
    messages.append({"role": "user",
                     "content": user_text + ("\n\n" + warning_note if warning_note else "")})

    # Resolve once per turn — Evon first if configured and up, else Groq.
    provider, client, model = resolve_llm_provider()
    LAST_LLM_PROVIDER.update({"name": provider, "model": model})
    logger.info("LLM provider: %s model=%s", provider, model)
    temperature = EVON_TEMPERATURE if provider == "evon" else GROQ_TEMPERATURE
    # Evon is a reasoning model. For a kid's short answer, thinking must be
    # OFF, otherwise it spends seconds reasoning before the first word.
    # vLLM reads this via chat_template_kwargs on the OpenAI-compatible API.
    extra = {}
    if provider == "evon":
        extra = {"extra_body": {"chat_template_kwargs": {"enable_thinking": EVON_ENABLE_THINKING}}}
    elif "gpt-oss" in model:
        # gpt-oss is a reasoning model: with a 120-token budget its hidden
        # reasoning can consume everything and the spoken reply comes out
        # EMPTY (seen on /llm-test, 2026-11-08). Force minimal reasoning.
        extra = {"extra_body": {"reasoning_effort": "low"}}

    t0 = time.monotonic()
    first_token_ms = None
    full = []
    stream = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature,
        max_completion_tokens=LLM_MAX_TOKENS, top_p=0.95 if provider == "evon" else 1,
        stream=True, **extra,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        # Evon may also send reasoning_content — ignore it, speak only content.
        text = getattr(delta, "content", None) or ""
        if text:
            if first_token_ms is None:
                first_token_ms = (time.monotonic() - t0) * 1000
            full.append(text)
            yield "".join(full), first_token_ms, None
    total_ms = (time.monotonic() - t0) * 1000
    yield "".join(full).strip(), (first_token_ms or total_ms), total_ms


# ---------------------------------------------------------------- DB
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        user_message TEXT NOT NULL,
        ai_response TEXT NOT NULL,
        emotion TEXT,
        audio_input TEXT,
        audio_output TEXT,
        flag_type TEXT
    )""")
    conn.commit()
    conn.close()


init_db()


# ---------------------------------------------------------------- routes
@app.route("/")
def index():
    return render_template("conversations.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "mock": MOCK,
        "gnani_configured": bool(GNANI_API_KEY),
        "groq_configured": bool(GROQ_API_KEY),
        "llm_provider_configured": LLM_PROVIDER,
        "llm_provider_last_used": LAST_LLM_PROVIDER["name"],
        "evon_base_url": EVON_BASE_URL,
        "evon_model": EVON_MODEL,
        "models": {"stt": "prisma-v2.5", "tts": TTS_MODEL, "tts_voice": TTS_VOICE,
                   "llm": LLM_MODEL, "evon_llm": EVON_MODEL, "stt_lang": STT_LANG},
    })


@app.route("/llm-test", methods=["POST"])
def llm_test():
    """Test the LLM layer alone, no audio: {"text": "mujhe ek kahani sunao"}.

    Returns which provider actually answered (evon / groq / mock) and the
    reply. Use this to prove Evon works before filming — if it says groq,
    your vLLM server was down and the fallback kicked in.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip() or "mujhe ek kahani sunao"
    t0 = time.monotonic()
    chunks = list(llm_stream_reply(text, [], ""))
    reply = chunks[-1][0] if chunks else ""
    return jsonify({
        "text": text,
        "ai_response": reply,
        "llm_provider_used": LAST_LLM_PROVIDER["name"],
        "llm_model_used": LAST_LLM_PROVIDER["model"],
        "total_ms": round((time.monotonic() - t0) * 1000, 1),
        "mock": MOCK,
    })


@app.route("/upload", methods=["POST"])
def upload():
    """Same contract as the original ESP32 firmware expects.

    The ESP32 sends one 3-second wav and waits for JSON. We do the slow
    work overlapped (LLM streams -> sentence TTS starts immediately) and
    return one 24kHz WAV file the .ino already knows how to play.
    """
    t_start = time.monotonic()
    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400
    audio_bytes = request.files["audio"].read()
    if not audio_bytes:
        return jsonify({"error": "Empty audio file"}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if SAVE_AUDIO:
        os.makedirs("mic_input", exist_ok=True)
        with open(f"mic_input/req_{timestamp}.wav", "wb") as f:
            f.write(audio_bytes)

    timings = {}

    # 1. STT — Prisma v2.5, in-memory, no disk round-trip.
    try:
        user_text, stt_ms = gnani_transcribe(audio_bytes)
    except Exception as e:
        logger.error("STT failed: %s", e)
        return jsonify({"error": f"STT failed: {e}"}), 502
    timings["stt_ms"] = round(stt_ms, 1)
    logger.info("STT (%.0f ms): %s", stt_ms, user_text)
    if not user_text:
        # Speak the fallback too — a silent robot tells you nothing about
        # whether the speaker path works. With audio, a silent robot after
        # this message means the I2S/amp path, not the mic.
        sorry = "Sorry, main sun nahi paya. Phir se bolo?"
        sorry_wav = f"resp_{timestamp}_sorry.wav"
        pcm = gnani_tts_sentence(sorry)
        with open(os.path.join(AUDIO_DIR, sorry_wav), "wb") as f:
            f.write(pcm_to_wav(pcm))
        logger.info("Empty transcript — played fallback audio")
        return jsonify({"text": "", "ai_response": sorry, "emotion": "neutral",
                        "has_audio": True, "audio_url": f"/audio/{sorry_wav}",
                        "timings_ms": timings})

    # 2. Safety on the INPUT + emotion in parallel (never blocks the reply).
    user_safe, user_flag = check_response_safety(user_text)
    flag_type = None
    warning_note = ""
    if not user_safe:
        flag_type = user_flag
        warning_note = ("Note: The child used inappropriate words / mentioned a "
                        "sensitive topic. Gently redirect to a positive, educational topic.")
    emotion_holder = {"value": "neutral"}
    emotion_thread = threading.Thread(
        target=lambda: emotion_holder.__setitem__("value", predict_emotion_fast(user_text)),
        daemon=True)
    emotion_thread.start()

    # 3. LLM streaming + sentence-wise TTS, overlapped.
    db = get_db()
    history = db.execute(
        "SELECT user_message, ai_response FROM conversations ORDER BY id DESC LIMIT ?",
        (MAX_HISTORY_TURNS,)).fetchall()
    history = list(reversed(history))

    # Timbre allows only ONE active request per key (429 RATE_LIMITED with
    # "Only 1 active request is allowed at a time" — seen live 2026-11-08).
    # So sentences must be synthesised sequentially; they still overlap with
    # the LLM stream, which is where the latency win comes from.
    tts_executor = ThreadPoolExecutor(max_workers=1)
    tts_futures = []          # (sentence, future) in spoken order
    submitted = set()
    ai_text = ""
    llm_first_ms = llm_total_ms = 0.0
    t_tts_start = time.monotonic()

    def submit_sentence(sentence):
        if sentence and sentence not in submitted:
            submitted.add(sentence)
            tts_futures.append((sentence, tts_executor.submit(gnani_tts_sentence, sentence)))

    try:
        # Submit each COMPLETE sentence to Timbre as soon as it arrives,
        # while the LLM is still generating the next one. The last (incomplete)
        # sentence is held back until the stream ends.
        for cumulative, first_ms, total_ms in llm_stream_reply(user_text, history, warning_note):
            ai_text = cumulative.strip()
            llm_first_ms = first_ms
            if total_ms is not None:
                llm_total_ms = total_ms
            sentences = split_sentences(ai_text)
            complete = sentences[:-1] if total_ms is None else sentences
            for sentence in complete:
                submit_sentence(sentence)
        for sentence in split_sentences(ai_text):
            submit_sentence(sentence)
    except Exception as e:
        logger.error("LLM failed: %s", e)
        return jsonify({"error": f"LLM failed: {e}"}), 502

    timings["llm_first_token_ms"] = round(llm_first_ms, 1)
    timings["llm_total_ms"] = round(llm_total_ms, 1)
    logger.info("LLM (first %.0f ms, total %.0f ms): %s", llm_first_ms, llm_total_ms, ai_text)

    # Safety on the OUTPUT — replace, never speak, an unsafe reply.
    is_safe, out_flag = check_response_safety(ai_text)
    if not is_safe:
        flag_type = out_flag
        ai_text = get_safe_response(out_flag)
        logger.warning("Unsafe LLM reply blocked (%s)", out_flag)
        tts_futures = [(ai_text, tts_executor.submit(gnani_tts_sentence, ai_text))]

    # 4. Collect TTS in spoken order and concat into ONE 24kHz WAV.
    #    No ffmpeg needed — Timbre already returns 24kHz PCM.
    pcm_parts = []
    for sentence, fut in tts_futures:
        try:
            pcm_parts.append(fut.result(timeout=30))
        except Exception as e:
            logger.warning("TTS failed for %r: %s", sentence[:40], e)
    tts_executor.shutdown(wait=False)
    timings["tts_ms"] = round((time.monotonic() - t_tts_start) * 1000, 1)

    wav_bytes = pcm_to_wav(b"".join(pcm_parts)) if pcm_parts else b""
    output_filename = f"resp_{timestamp}.wav"
    output_path = os.path.join(AUDIO_DIR, output_filename)
    if wav_bytes:
        with open(output_path, "wb") as f:
            f.write(wav_bytes)

    # Emotion: take the parallel result if ready, else the fast value.
    emotion_thread.join(timeout=0.3)
    emotion = emotion_holder["value"]

    db.execute(
        "INSERT INTO conversations (timestamp, user_message, ai_response, emotion,"
        " audio_input, audio_output, flag_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (timestamp, user_text, ai_text, emotion, "", output_filename, flag_type))
    db.commit()

    timings["total_ms"] = round((time.monotonic() - t_start) * 1000, 1)
    logger.info("TOTAL %.0f ms | stt %.0f | llm %.0f | tts %.0f",
                timings["total_ms"], timings["stt_ms"],
                timings["llm_total_ms"], timings["tts_ms"])

    return jsonify({
        "text": user_text,
        "ai_response": ai_text,
        "emotion": emotion,
        "has_audio": bool(wav_bytes),
        "audio_url": f"/audio/{output_filename}",
        "timings_ms": timings,
        "models": {"stt": "prisma-v2.5", "tts": TTS_MODEL,
                   "llm": LAST_LLM_PROVIDER["model"],
                   "llm_provider": LAST_LLM_PROVIDER["name"]},
        "mock": MOCK,
    })


@app.route("/audio/<filename>")
def serve_audio(filename):
    # Only serve files we created in AUDIO_DIR.
    safe = os.path.basename(filename)
    return send_file(os.path.join(AUDIO_DIR, safe), mimetype="audio/wav")


@app.route("/test-tts", methods=["POST"])
def test_tts():
    """Quick check without the ESP32: {"text": "Namaste! Kaisi ho?"} -> WAV."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or request.form.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Provide {\"text\": \"...\"}"}), 400
    pcm = gnani_tts_sentence(text)
    return send_file(io.BytesIO(pcm_to_wav(pcm)), mimetype="audio/wav",
                     as_attachment=True, download_name="test.wav")


@app.route("/conversations")
def get_conversations():
    limit = request.args.get("limit", 50, type=int)
    db = get_db()
    rows = db.execute(
        "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/conversations/<int:conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    db = get_db()
    db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    db.commit()
    return jsonify({"deleted": conv_id})


@app.route("/conversations/clear", methods=["POST"])
def clear_conversations():
    db = get_db()
    db.execute("DELETE FROM conversations")
    db.commit()
    return jsonify({"cleared": True})


@app.route("/conversations/recompute", methods=["POST"])
def recompute_emotions():
    db = get_db()
    rows = db.execute("SELECT id, user_message FROM conversations").fetchall()
    for row in rows:
        db.execute("UPDATE conversations SET emotion = ? WHERE id = ?",
                   (predict_emotion_fast(row["user_message"]), row["id"]))
    db.commit()
    return jsonify({"updated": len(rows)})


@app.route("/report")
def report_page():
    return render_template("report.html")


@app.route("/api/report")
def generate_report_api():
    db = get_db()
    rows = db.execute("SELECT * FROM conversations ORDER BY id").fetchall()
    if not rows:
        return jsonify({"message": "No conversations yet"}), 400
    conversation_text = "".join(
        f"User: {r['user_message']}\nAI: {r['ai_response']}\nEmotion: {r['emotion']}\n\n"
        for r in rows)
    prompt = ("Create a development report for a child based on their conversation "
              "history. Use ONLY plain text with simple formatting:\n\n"
              "1. EMOTIONAL ANALYSIS\n2. TOPIC ANALYSIS\n3. DEVELOPMENTAL OBSERVATIONS\n"
              "4. CONCERNS - Be specific, quote the child's exact words\n"
              "5. RECOMMENDATIONS\n6. SUMMARY\n\n"
              f"CONVERSATIONS:\n{conversation_text}\nGenerate the report now:")
    if MOCK or (not GROQ_API_KEY and LLM_PROVIDER == "groq"):
        return jsonify({"report": "Mock mode: connect GROQ_API_KEY for a real report.",
                        "total_conversations": len(rows)})
    _prov, _client, _model = resolve_llm_provider()
    completion = _client.chat.completions.create(
        model=_model,
        messages=[{"role": "system",
                   "content": "You are a child development expert."},
                  {"role": "user", "content": prompt}],
        temperature=0.7, max_completion_tokens=1024)
    return jsonify({"report": completion.choices[0].message.content.strip(),
                    "total_conversations": len(rows)})


if __name__ == "__main__":
    print("SafeToy Gnani pipeline on http://0.0.0.0:5050  (mock=%s)" % MOCK)
    print("STT: Prisma v2.5 (%s) | TTS: %s voice=%s | LLM provider: %s "
          "(groq=%s, evon=%s @ %s, thinking=%s)" %
          (STT_LANG, TTS_MODEL, TTS_VOICE, LLM_PROVIDER, LLM_MODEL,
           EVON_MODEL, EVON_BASE_URL, EVON_ENABLE_THINKING))
    app.run(host="0.0.0.0", port=5050, threaded=True)
