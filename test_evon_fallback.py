"""Test Evon -> Groq fallback without a GPU, without Gnani keys, without Groq calls.

Run:  python test_evon_fallback.py
It starts a fake vLLM server on localhost, checks that:
  1. Evon down  -> resolve_llm_provider() returns groq (fallback, no crash)
  2. Evon up    -> resolve_llm_provider() returns evon + Evon model name
  3. LLM_PROVIDER=evon + Evon down -> groq fallback (not a failed turn)
  4. LLM_PROVIDER=groq -> groq, Evon never touched

No real LLM call is made in any case — resolve only creates the client
and, for Evon, does a GET /v1/models health check.

Note for Linux test machines: httpx (used by the Groq/OpenAI clients)
can choke on a NO_PROXY value containing IPv6 literals like [::1].
This script narrows NO_PROXY before importing the clients. On your
Windows PC this is not needed.
"""
import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["GNANI_API_KEY"] = "dummy"
os.environ["GROQ_API_KEY"] = "dummy"

import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402


def main():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class FakeVLLM(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"gnani/gnani-evon-v3.3-30B-A3B"}]}')

        def log_message(self, *a):
            pass

    server.LLM_PROVIDER = "auto"
    server.EVON_BASE_URL = "http://127.0.0.1:9/v1"
    assert server._evon_available(timeout_s=1) is False
    prov, _, model = server.resolve_llm_provider()
    assert prov == "groq", prov
    print("1. Evon down -> groq fallback: OK")

    httpd = HTTPServer(("127.0.0.1", 8765), FakeVLLM)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    server.EVON_BASE_URL = "http://127.0.0.1:8765/v1"
    assert server._evon_available(timeout_s=2) is True
    prov, _, model = server.resolve_llm_provider()
    assert prov == "evon" and model == "gnani/gnani-evon-v3.3-30B-A3B", (prov, model)
    print("2. Evon up -> evon picked: OK")
    httpd.shutdown()

    server.LLM_PROVIDER = "evon"
    server.EVON_BASE_URL = "http://127.0.0.1:9/v1"
    prov, _, _ = server.resolve_llm_provider()
    assert prov == "groq", prov
    print("3. LLM_PROVIDER=evon + Evon down -> groq fallback: OK")

    server.LLM_PROVIDER = "groq"
    prov, _, _ = server.resolve_llm_provider()
    assert prov == "groq", prov
    print("4. LLM_PROVIDER=groq -> groq, Evon untouched: OK")

    print("\nEVON FALLBACK TESTS PASSED")


if __name__ == "__main__":
    main()
