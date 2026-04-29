from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import socket
import sys
import tempfile
import threading
import webbrowser


ROOT = Path(__file__).resolve().parent
BACKUP_PATH = ROOT / "sydrro-backup.json"


def is_port_in_use(port):
    try:
        with socket.create_connection(("localhost", port), timeout=0.2):
            return True
    except OSError:
        return False


class SydrroHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.endswith((".html", ".xlsx", ".json")) or self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/backup":
            self.send_backup()
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] == "/api/backup":
            self.receive_backup()
            return
        self.send_error(404, "Not Found")

    def send_backup(self):
        if not BACKUP_PATH.exists():
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"message":"backup not found"}')
            return

        payload = BACKUP_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def receive_backup(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self.send_error(400, "Empty backup")
            return
        if length > 20 * 1024 * 1024:
            self.send_error(413, "Backup too large")
            return

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            if data.get("app") != "SYDRRO-TECH":
                raise ValueError("Invalid app marker")
        except Exception as exc:
            self.send_error(400, f"Invalid backup JSON: {exc}")
            return

        fd, tmp_name = tempfile.mkstemp(prefix="sydrro-backup-", suffix=".json", dir=ROOT)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp_name, BACKUP_PATH)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

        payload = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    os.chdir(ROOT)
    args = [arg for arg in sys.argv[1:] if arg != "--open"]
    preferred_port = int(args[0]) if args else 8787
    open_browser = "--open" in sys.argv[1:]

    server = None
    port = preferred_port
    for candidate in range(preferred_port, preferred_port + 30):
        if is_port_in_use(candidate):
            continue
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), SydrroHandler)
            port = candidate
            break
        except OSError:
            continue

    if server is None:
        raise RuntimeError(f"No available local port from {preferred_port} to {preferred_port + 29}")

    url = f"http://127.0.0.1:{port}/SYDRRO-TECH-V3.8.html?v={os.getpid()}"
    print(f"SYDRRO-TECH local server: {url}", flush=True)
    print(f"Auto backup file: {BACKUP_PATH}", flush=True)

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    server.serve_forever()


if __name__ == "__main__":
    main()
