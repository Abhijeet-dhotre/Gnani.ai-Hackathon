# Evon v3.3 — how to run it as the LLM

Evon v3.3 is Gnani's own LLM: `gnani/gnani-evon-v3.3-30B-A3B` on Hugging Face,
30B MoE / ~3.5B active per token, 128K context, 11 Indian languages,
Apache 2.0. It is **not** on the Gnani API platform, so your 5,000 challenge
credits do not cover it and there is no Gnani API key for it. You run the
open weights yourself with vLLM, which exposes an OpenAI-compatible API
that `server.py` already talks to.

## Step 1 — Request access (do this first, approval may take time)

1. Open https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B
2. Click Request access / agree to the Apache 2.0 terms, with the Hugging Face
   account you will use to download.
3. Create a Hugging Face token (Settings → Access Tokens, Read) — you need it
   for `huggingface-cli login` on the GPU machine only. Never paste it in chat.

If access is not approved in time, **do not wait** — keep `LLM_PROVIDER=groq`
for the demo. The fallback exists exactly for this case.

## Step 2 — GPU (this is the real blocker)

BF16 weights are ~60 GB. The model card lists H100 80GB, H200 or A100.
Your laptop cannot run it. Colab T4 (16 GB) cannot run it.

Realistic options, cheapest first:
- **Colab L4 (24 GB)** — try only with a quantised build if one is published;
  full BF16 will not fit. Test, do not assume.
- **RunPod / Vast.ai H100 or A100** — rent by the hour, install vLLM there,
  expose the port, point `EVON_BASE_URL` at it. Shut it down after testing.
- **Any single-GPU node with 80 GB VRAM** — the intended setup.

Do not try to run it on the ESP32 server PC unless that PC has such a GPU.

## Step 3 — Start vLLM (on the GPU machine)

```bash
pip install -U "vllm>=0.12.0" "transformers>=5.3.0"
huggingface-cli login
vllm serve gnani/gnani-evon-v3.3-30B-A3B \
  --port 8000 \
  --max-model-len 8192
```

Notes:
- `--max-model-len 8192` is enough for kid answers (we send max 120 output
  tokens + short history) and saves VRAM vs the full 128K context.
- If vLLM complains about tool calling, add `--enable-auto-tool-choice
  --tool-call-parser hermes` — we do not use tools, so this is optional.
- Wait until the log says the server is ready and `GET /v1/models` returns
  the model. First start downloads ~60 GB and takes a long time.

If the vLLM server is on another machine (RunPod / Colab), replace
`localhost` with its public IP / tunnel URL in `EVON_BASE_URL`, e.g.
`http://203.0.113.10:8000/v1`. Keep the port open only while testing.

## Step 4 — Point SafeToy at it

In the SafeToy `.env` on your robot server PC:

```
LLM_PROVIDER=auto
EVON_BASE_URL=http://localhost:8000/v1
EVON_MODEL=gnani/gnani-evon-v3.3-30B-A3B
EVON_ENABLE_THINKING=0
```

`auto` means: try Evon first, fall back to Groq automatically if Evon is
down. `evon` means: Evon only, fail the turn if it is down — use it only
when you have proven Evon works. `groq` means: Groq only, the safe demo
setting.

`EVON_ENABLE_THINKING=0` is important. Evon is a reasoning model — with
thinking on it spends seconds reasoning before the first word. With it off
(`chat_template_kwargs: {enable_thinking: False}` in the code) it answers
directly. Temperature is 0.6 and top_p 0.95 for Evon, per the model card.

## Step 5 — Prove it before filming

```bash
curl http://localhost:8000/v1/models
curl -X POST -H "Content-Type: application/json" \
  -d '{"text":"mujhe ek kahani sunao"}' http://localhost:5050/llm-test
```

`/llm-test` returns `llm_provider_used`. It must say `evon`.
If it says `groq`, your vLLM server was down and the fallback kicked in —
fix vLLM, do not claim Evon in the video.

Then do one full robot turn and check `/upload` JSON: `models.llm_provider`
must say `evon`, and `timings_ms.llm_total_ms` is your real Evon time.
If Evon is much slower than Groq for the same short answer, keep Groq for
the filmed demo and name Evon as integrated + tested in the submission.
Do not claim the demo ran on Evon if it ran on Groq.

## Honest limits

- No free Colab T4 run of full Evon is expected to work. Do not promise it.
- Quantised / FP8 builds, if published later, change the VRAM math — check
  the model repo before renting a GPU.
- Evon safety: the model card says do not deploy without safety evaluation
  on your target languages. Our server still runs the same input + output
  safety check on Evon replies, so an unsafe Evon reply is replaced, just
  like a Groq one.
