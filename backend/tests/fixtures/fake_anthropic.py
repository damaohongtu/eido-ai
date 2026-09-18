"""Deterministic, offline Anthropic endpoint for the opt-in Docker test."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        if self.headers.get("Transfer-Encoding") == "chunked":
            chunks = []
            while size := int(self.rfile.readline().strip(), 16):
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            self.rfile.readline()
            raw = b"".join(chunks)
        else:
            raw = self.rfile.read(size)
        body = json.loads(raw)
        if self.headers.get("x-api-key") != "test-master-provider-key":
            self.send_error(401)
            return
        if self.path.startswith("/v1/messages/count_tokens"):
            result = {"input_tokens": 32}
        else:
            markers = re.findall(r"EIDO_MARKER_[A-Z0-9]+", json.dumps(body.get("messages", [])))
            result = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body.get("model", "test-model"),
                "content": [{"type": "text", "text": markers[0] if markers else "OK"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 32, "output_tokens": 8},
            }
        self.send_response(200)
        if body.get("stream") and "content" in result:
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = [
                {
                    "type": "message_start",
                    "message": {**result, "content": [], "stop_reason": None},
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": result["content"][0]["text"]},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 8},
                },
                {"type": "message_stop"},
            ]
            for event in events:
                self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
        else:
            data = json.dumps(result).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 9000), Handler).serve_forever()
