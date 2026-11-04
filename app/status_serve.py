"""Read-only status for explicitly allowed tailnet callers."""
import argparse
import hmac
import ipaddress
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from plugins import system_status


KEYS = ("host", "cpu_pct", "mem", "disks", "net", "uptime_s", "failed_system", "generation", "rev", "built")
FORBIDDEN = b"Forbidden\n"
NOT_FOUND = b"Not found\n"
TOO_LARGE = b"Status unavailable\n"


class StatusServer(ThreadingHTTPServer):
    def __init__(self, address, allowed, token):
        self.allowed = frozenset(allowed)
        self.token = token
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(address, StatusHandler)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(2)
        return sock, address

    def verify_request(self, request, client_address):
        return client_address[0] in self.allowed          # a stranger is dropped before it can hold a slot or a thread

    def handle_error(self, request, client_address):
        pass                                              # (the default prints the caller and a traceback to the journal)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def log_error(self, *args):
        pass

    def reply(self, code, body, content_type="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.client_address[0] not in self.server.allowed:      # who asks comes first: a stranger learns nothing, not even paths
            return self.reply(403, FORBIDDEN)
        if self.path != "/v1/status":
            return self.reply(404, NOT_FOUND)
        auth = self.headers.get("Authorization", "").encode("utf-8")
        if not hmac.compare_digest(auth, b"Bearer " + self.server.token):
            return self.reply(403, FORBIDDEN)
        status = system_status(user=False)
        body = json.dumps({**{key: status[key] for key in KEYS}, "failed": None}, separators=(",", ":")).encode("utf-8")
        if len(body) > 16 * 1024:
            return self.reply(500, TOO_LARGE)
        self.reply(200, body, "application/json")

    def __getattr__(self, name):
        if name.startswith("do_"):
            return lambda: self.reply(403, FORBIDDEN) if self.client_address[0] not in self.server.allowed else self.reply(404, NOT_FOUND)
        raise AttributeError(name)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True, type=ipaddress.IPv4Address)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--allow", required=True, action="append", type=ipaddress.IPv4Address)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args(argv)
    with open(args.token_file, "rb") as file:
        token = file.read().rstrip()
    if not token:
        parser.error("token file is empty")
    threading.stack_size(256 * 1024)
    with StatusServer((str(args.address), args.port), [str(ip) for ip in args.allow], token) as server:
        print(f"nixi-status listening on {args.address}:{args.port}", file=sys.stderr, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
