# SafeToy AI — Low-Latency Gnani Pipeline

For the Great Indian AI Internship Challenge (Gnani AI).
Deadline: **Nov 10, 2026, 11:59 PM IST.**

A drop-in replacement for `server.py` in
[AI-Chat-Robot-for-Children](https://github.com/Abhijeet-dhotre/AI-Chat-Robot-for-Children),
swapped from Whisper + Edge TTS to Gnani, and made fast.

## What changed

| Step | Before (original repo) | Now (this pipeline) |
|---|---|---|
| STT | Whisper via Groq, `language="en"` | **Prisma v2.5** via `gnani-vachana`, `en-IN` (Hinglish), retry `hi-IN` |
| LLM | llama-3.3-70b, `stream=False`, 1024 tokens | **Evon v3.3 first when available, Groq llama-3.1-8b-instant as automatic fallback** — `LLM_PROVIDER=groq \| evon \| auto`, `stream=True`, 120 tokens, 2–3 short sentences, thinking off for Evon |
| TTS | Edge TTS on localhost:8000 + ffmpeg to 24kHz | **Timbre v2.5, voice Nalini, SSE streaming**, 24kHz PCM direct, no ffmpeg |
| Emotion | Local BERT (torch) — blocks the reply | Fast keyword heuristic in a **parallel thread, never blocks** |
| Audio I/O | Save wav to disk, read it back, ESP32 does a 2nd GET | **In-memory bytes only**; one WAV file saved for the ESP32 GET |

No second `tts_server.py` needed. One process, one port: **5050**.

## Why it is faster

Old flow waits for everything to finish before starting the next step:
save → full STT → full LLM → emotion → full TTS → ffmpeg → play. ~3–5 s silence.

New flow overlaps:
- LLM **streams**. The moment sentence 1 ends (`...tha.`), it goes to Timbre
  SSE immediately, while sentence 2 is still generating.
- Timbre **streams** PCM per sentence (`GnaniTTSStreamClient.synthesize_stream`).
  Sentences are synthesised in parallel (2 workers) and concatenated into
  one 24 kHz WAV.
- Emotion runs in a background thread. The reply never waits for it.
- No disk for the input, no ffmpeg, reused Gnani/Groq clients (no new
  connection per request), short history (last 6 turns), short answers.

Target (real keys, same Wi-Fi): **first sound ~0.9–1.2 s after button release**,
full short answer ~2 s. The `/upload` JSON returns `timings_ms` so you can
prove it: `stt_ms`, `llm_first_token_ms`, `llm_total_ms`, `tts_ms`, `total_ms`.

Gnani numbers behind this: STT P95 ~200 ms, Timbre sub-250 ms p95. The socket
itself only saves ~50–100 ms per request — the model time dominates, and
streaming is what cuts it.

## ESP32 — no firmware change

`POST /upload` takes the same multipart `audio` field and returns the same
JSON keys your `.ino` already parses: `text`, `ai_response`, `emotion`,
`has_audio`, `audio_url`. Keep your working wiring exactly as-is.

Only change in `esp32_robot/esp32_robot.ino`:
```cpp
String server_url = "http://YOUR_PC_IP:5050";  // e.g. http://192.168.1.5:5050
```
Find your PC IP with `ipconfig` (Windows) and use the same Wi-Fi as the robot.

## Setup (15 minutes)

1. Register at gnani.ai/internship, get your key at **app.gnani.ai/voice**
   (5,000 programme credits). Get a Groq key if you don't have one.
2. Copy this folder to your PC (or `git clone` your repo and replace `server.py`).
3. `copy .env.example .env` — paste `GNANI_API_KEY` and `GROQ_API_KEY`.
4. `pip install -r requirements.txt`
5. `python server.py` — or double-click `run_server.bat` on Windows.
6. Check `http://localhost:5050/health` — should say `gnani_configured: true`.

## Test without keys / without the robot

```bash
MOCK_GNANI=1 python test_pipeline.py
```
This posts a fake wav, checks the ESP32 JSON contract, checks the WAV is
valid 24 kHz, and prints timings. It must say `ALL TESTS PASSED`.

Quick TTS check (real keys):
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"text":"Namaste! Kaisi ho?"}' http://localhost:5050/test-tts --output test.wav
```

Real end-to-end check: hold the robot button, say in Hinglish
*“mujhe ek kahani sunao, dinosaur wali?”*, release, time it. Then read
`timings_ms` in the server log — if `total_ms` is over ~2000 ms, check
`llm_total_ms` first (long answer?) then `tts_ms`.

## Files

- `server.py` — the whole pipeline. Read the header comment first.
- `EVON_SETUP.md` — how to run Evon v3.3 with vLLM, and how to prove it.
- `requirements.txt` — Flask, Groq, OpenAI client (for Evon via vLLM), gnani-vachana, dotenv. No torch, no ffmpeg.
- `test_pipeline.py` — mock-mode contract test.
- `templates/` — copied from the original repo (`/`, `/report` still work).
- `.env.example`, `run_server.bat`

## Honest limits

- **Not tested live with real Gnani keys yet.** The Gnani calls were verified
  against the real installed `gnani-vachana` package (signatures, voices,
  `transcribe_bytes` → `transcript`, `synthesize_stream` → raw PCM), and the
  pipeline passes in mock mode — but your first real-key run is still the
  test. Run `/test-tts` first, then one `/upload` from the robot.
- Prisma v2.5 is the default model (omit `model=`). `prisma-v3.0` exists but
  is opt-in and not needed here.
- Evon v3.3 is **optional, via local vLLM** — it is not on the Gnani API
  platform, so there is no Gnani API key for it. See `EVON_SETUP.md`:
  request weights at `gnani/gnani-evon-v3.3-30B-A3B`, run
  `vllm serve` on an H100 / A100 GPU, set `LLM_PROVIDER=auto`.
  `server.py` tries Evon first and falls back to Groq automatically if the
  vLLM server is down. Check `/llm-test` — it reports `llm_provider_used`.
  If it says `groq`, Evon was down. Do not claim the demo ran on Evon if
  it ran on Groq. Default `LLM_PROVIDER=groq` is the safe demo setting.
- Emotion is now a keyword heuristic, not the BERT model. It is fast and
  good enough for OLED eyes (happy / sad / angry / scared / excited /
  neutral). If the judges ask, say so plainly — don't claim the BERT ran.
- The robot still waits for the full WAV before playing (your `.ino` does
  a GET after the JSON). True play-while-generating would need a firmware
  change to stream audio chunks — don't attempt that before the deadline.
