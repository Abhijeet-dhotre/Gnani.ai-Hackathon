"""Test the low-latency pipeline with NO keys, NO ESP32, NO network to Gnani.

Run:  MOCK_GNANI=1 python test_pipeline.py
It:
  1. Builds a 1-second silent 16kHz WAV in memory (like the ESP32 sends).
  2. POSTs it to /upload via Flask's test client.
  3. Checks the JSON contract the ESP32 .ino expects.
  4. Checks the returned WAV is a valid 24kHz mono file and plays back length > 0.
  5. Prints the timings_ms so you can see the pipeline overhead in mock mode
     (real STT/TTS times will be larger — see README for real targets).

Real-key test (after you have keys):
  python server.py            # in one terminal
  curl -X POST -F "audio=@test.wav;type=audio/wav" http://localhost:5050/upload
  curl -X POST -H "Content-Type: application/json" -d "{\"text\":\"Namaste! Kaisi ho?\"}" \
    http://localhost:5050/test-tts --output test-out.wav
"""
import io
import os
import struct
import sys
import wave

os.environ["MOCK_GNANI"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402


def make_wav(seconds=1.0, sample_rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    buf.seek(0)
    return buf.read()


def main():
    wav = make_wav()
    print(f"test wav: {len(wav)} bytes, 16kHz mono")
    client = server.app.test_client()

    r = client.get("/health")
    print("GET /health:", r.status_code, r.get_json())
    assert r.status_code == 200

    r = client.post("/upload", data={"audio": (io.BytesIO(wav), "xiao.wav")},
                    content_type="multipart/form-data")
    print("POST /upload:", r.status_code)
    data = r.get_json()
    print("JSON:", data)
    assert r.status_code == 200, data
    for key in ("text", "ai_response", "emotion", "has_audio", "audio_url", "timings_ms"):
        assert key in data, f"missing key for ESP32 contract: {key}"
    assert data["has_audio"] is True
    assert data["models"]["stt"] == "prisma-v2.5"
    assert data["models"]["tts"] == "timbre-v2.5"
    assert "llm_provider" in data["models"], "upload must report which LLM answered"
    print("llm_provider used:", data["models"]["llm_provider"])
    print("timings_ms:", data["timings_ms"])

    r = client.post("/llm-test", json={"text": "mujhe ek kahani sunao"})
    print("POST /llm-test:", r.status_code, r.get_json())
    assert r.status_code == 200
    assert r.get_json()["llm_provider_used"] in ("mock", "groq", "evon")

    r = client.get(data["audio_url"])
    print("GET", data["audio_url"], ":", r.status_code, "bytes:", len(r.data))
    assert r.status_code == 200 and len(r.data) > 44
    assert r.data[:4] == b"RIFF", "audio must be a WAV file for the ESP32 player"
    # Parse the WAV header the ESP32 parses: sample rate at bytes 24-27.
    sr = struct.unpack("<I", r.data[24:28])[0]
    print("WAV sample rate:", sr, "Hz (ESP32 expects 24000)")
    assert sr == 24000, sr

    r = client.post("/test-tts", json={"text": "Namaste! Kaisi ho?"})
    print("POST /test-tts:", r.status_code, "bytes:", len(r.data))
    assert r.status_code == 200 and r.data[:4] == b"RIFF"

    r = client.get("/conversations")
    assert r.status_code == 200 and len(r.get_json()) >= 1
    print("conversations saved:", len(r.get_json()))

    print("\nALL TESTS PASSED — pipeline contract OK in mock mode.")
    print("Next: put real keys in .env, run python server.py, and re-run with")
    print("MOCK_GNANI=0 to measure real Prisma + Timbre timings.")


if __name__ == "__main__":
    main()
