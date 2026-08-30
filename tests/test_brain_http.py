"""The HTTP path against a real socket.

Everything else mocks `stream_deltas`. This spins up a server that speaks the
same SSE dialect as llama-server, so the urllib request, the headers, the
chunked read and the error paths are all genuinely exercised — with no model.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from marvind.brain import BrainError, generate, stream_sentences, wait_for_server
from marvind.config import BrainConfig

TOKENS = ["I have", " no idea.", " Nobody tells", " me anything.", " It is late"]


class FakeLlamaServer(BaseHTTPRequestHandler):
    """Minimal stand-in for llama-server's /health and /v1/chat/completions."""

    healthy = True
    fail_with: int | None = None
    received: dict | None = None

    def log_message(self, *args):  # keep pytest output clean
        pass

    def do_GET(self):
        status = 200 if type(self).healthy else 503
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).received = json.loads(body)

        if type(self).fail_with is not None:
            self.send_error(type(self).fail_with, "model not loaded")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for token in TOKENS:
            chunk = json.dumps({"choices": [{"delta": {"content": token}}]})
            self.wfile.write(f"data: {chunk}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


@pytest.fixture
def server():
    FakeLlamaServer.healthy = True
    FakeLlamaServer.fail_with = None
    FakeLlamaServer.received = None

    httpd = HTTPServer(("127.0.0.1", 0), FakeLlamaServer)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield BrainConfig(base_url=f"http://127.0.0.1:{httpd.server_port}", request_timeout_s=10.0)
    httpd.shutdown()
    httpd.server_close()


MESSAGES = [{"role": "system", "content": "you are marvin"}, {"role": "user", "content": "weather?"}]


def test_streams_sentences_over_a_real_connection(server):
    assert list(stream_sentences(server, MESSAGES)) == [
        "I have no idea.",
        "Nobody tells me anything.",
        "It is late",
    ]


def test_the_server_receives_the_assembled_messages_and_sampling_settings(server):
    generate(server, MESSAGES)
    assert FakeLlamaServer.received["messages"] == MESSAGES
    assert FakeLlamaServer.received["stream"] is True
    assert FakeLlamaServer.received["temperature"] == server.temperature


def test_generate_returns_the_joined_reply_with_timings(server):
    reply = generate(server, MESSAGES)
    assert reply.text.startswith("I have no idea.")
    assert len(reply.sentences) == 3
    assert 0 < reply.first_sentence_s <= reply.total_s


def test_an_http_error_from_the_server_becomes_a_brain_error(server):
    FakeLlamaServer.fail_with = 503
    with pytest.raises(BrainError, match="HTTP 503"):
        generate(server, MESSAGES)


def test_an_unreachable_server_names_the_url_it_tried(server):
    dead = BrainConfig(base_url="http://127.0.0.1:1", request_timeout_s=2.0)
    with pytest.raises(BrainError, match="cannot reach llama-server at http://127.0.0.1:1"):
        list(stream_sentences(dead, MESSAGES))


def test_wait_for_server_returns_once_health_is_green(server):
    wait_for_server(server, timeout_s=5.0)


def test_wait_for_server_gives_up_and_reports_the_last_error(server):
    FakeLlamaServer.healthy = False
    with pytest.raises(BrainError, match="not ready"):
        wait_for_server(server, timeout_s=1.5)
