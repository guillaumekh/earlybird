"""Shared test helpers: puts src/ on the path, fake audio, fake collector."""
import json
import math
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def words(samples):
    """Pack 18-bit samples the way the microphone delivers them."""
    return bytearray(struct.pack("<%di" % len(samples), *(s << 14 for s in samples)))


def sine(amplitude, n=3200, period=32, offset=0):
    return [offset + int(amplitude * math.sin(2 * math.pi * i / period)) for i in range(n)]


def sine_db(amplitude):
    return 20 * math.log10(amplitude / math.sqrt(2) / 2**17)


class Collector:
    """A local HTTP server recording the requests it receives."""

    def __init__(self, status=200):
        self.status = status
        self.requests = []
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                collector.requests.append((self.path, dict(self.headers), json.loads(body)))
                self.send_response(collector.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
