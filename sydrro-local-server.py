from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
from datetime import datetime, timezone
import ipaddress
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser
import zipfile


ROOT = Path(__file__).resolve().parent
BACKUP_PATH = ROOT / "sydrro-backup.json"
DATA_XLSX_PATH = ROOT / "data.xlsx"
DB_PATH = ROOT / "sydrro-data.sqlite3"
APP_HTML_FILE = "SYDRRO-TECH.html"
STATE_RECORD_ID = "default"


def is_port_in_use(port, host="localhost"):
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def app_url(port, host="127.0.0.1"):
    return f"http://{host}:{port}/{APP_HTML_FILE}"


def existing_app_server_ready(port, host="127.0.0.1"):
    try:
        with urlopen(app_url(port, host), timeout=0.8) as response:
            return response.status < 500
    except (OSError, URLError):
        return False


def get_lan_ipv4_addresses():
    addresses = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

    def score(ip):
        address = ipaddress.ip_address(ip)
        if address in ipaddress.ip_network("192.168.0.0/16"):
            return (0, ip)
        if address in ipaddress.ip_network("10.0.0.0/8"):
            return (1, ip)
        if address in ipaddress.ip_network("172.16.0.0/12"):
            return (2, ip)
        return (3, ip)

    return sorted(addresses, key=score)


def open_browser_url(url):
    try:
        if webbrowser.open(url, new=2):
            return
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.startfile(url)  # noqa: S606 - opens a local browser URL for the user.
            return
        except OSError:
            pass
    print(f"Open this URL manually: {url}", flush=True)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def default_state():
    return {
        "app": "SYDRRO-TECH",
        "version": 3,
        "exportedAt": utc_now_iso(),
        "rawData": [],
        "shippingStatus": {},
        "returnStatus": {},
        "currentActionFilter": "all",
        "currentActionDayOffset": 0,
        "inventoryData": [],
        "customModels": [],
    }


def normalize_state_payload(data):
    if not isinstance(data, dict):
        raise ValueError("State payload must be a JSON object")
    if data.get("app") != "SYDRRO-TECH":
        raise ValueError("Invalid app marker")

    normalized = default_state()
    try:
        normalized["version"] = int(data.get("version") or normalized["version"])
    except (TypeError, ValueError):
        normalized["version"] = default_state()["version"]
    normalized["exportedAt"] = data.get("exportedAt") or normalized["exportedAt"]
    normalized["rawData"] = data.get("rawData") if isinstance(data.get("rawData"), list) else []
    normalized["shippingStatus"] = data.get("shippingStatus") if isinstance(data.get("shippingStatus"), dict) else {}
    normalized["returnStatus"] = data.get("returnStatus") if isinstance(data.get("returnStatus"), dict) else {}
    normalized["currentActionFilter"] = data.get("currentActionFilter") or "all"
    try:
        normalized["currentActionDayOffset"] = int(data.get("currentActionDayOffset") or 0)
    except (TypeError, ValueError):
        normalized["currentActionDayOffset"] = 0
    normalized["inventoryData"] = data.get("inventoryData") if isinstance(data.get("inventoryData"), list) else []
    normalized["customModels"] = data.get("customModels") if isinstance(data.get("customModels"), list) else []
    return normalized


def connect_db():
    return sqlite3.connect(DB_PATH, timeout=10)


def init_db():
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def write_backup_mirror(state):
    fd, tmp_name = tempfile.mkstemp(prefix="sydrro-backup-", suffix=".json", dir=ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_name, BACKUP_PATH)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def save_state(data):
    init_db()
    state = normalize_state_payload(data)
    state["exportedAt"] = utc_now_iso()
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO app_state (id, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (STATE_RECORD_ID, payload, state["exportedAt"]),
        )
        conn.commit()
    write_backup_mirror(state)
    return state


def load_state():
    init_db()
    with connect_db() as conn:
        row = conn.execute("SELECT payload FROM app_state WHERE id = ?", (STATE_RECORD_ID,)).fetchone()
    if row:
        return normalize_state_payload(json.loads(row[0]))

    if BACKUP_PATH.exists():
        try:
            state = normalize_state_payload(json.loads(BACKUP_PATH.read_text(encoding="utf-8")))
            return save_state(state)
        except Exception as exc:
            print(f"Could not migrate backup JSON into SQLite: {exc}", file=sys.stderr, flush=True)

    return save_state(default_state())


class SydrroHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.endswith((".html", ".xlsx", ".json")) or self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/state":
            self.send_state()
            return
        if self.path.split("?", 1)[0] == "/api/backup":
            self.send_state()
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] == "/api/state":
            self.receive_state()
            return
        if self.path.split("?", 1)[0] == "/api/backup":
            self.receive_state()
            return
        if self.path.split("?", 1)[0] == "/api/data-xlsx":
            self.receive_data_xlsx()
            return
        self.send_error(404, "Not Found")

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_state(self):
        try:
            state = load_state()
        except Exception as exc:
            self.send_error(500, f"Could not read app state: {exc}")
            return
        payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def receive_data_xlsx(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self.send_error(400, "Empty workbook payload")
            return
        if length > 30 * 1024 * 1024:
            self.send_error(413, "Workbook payload too large")
            return

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            if data.get("app") != "SYDRRO-TECH":
                raise ValueError("Invalid app marker")
            if data.get("file") != "data.xlsx":
                raise ValueError("Invalid workbook target")
            workbook_bytes = base64.b64decode(data.get("contentBase64") or "", validate=True)
            if len(workbook_bytes) > 20 * 1024 * 1024:
                raise ValueError("Workbook too large")
            if not zipfile.is_zipfile(io.BytesIO(workbook_bytes)):
                raise ValueError("Workbook is not a valid xlsx file")
        except Exception as exc:
            self.send_error(400, f"Invalid workbook payload: {exc}")
            return

        fd, tmp_name = tempfile.mkstemp(prefix="data-", suffix=".xlsx", dir=ROOT)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(workbook_bytes)
            os.replace(tmp_name, DATA_XLSX_PATH)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

        payload = json.dumps({"ok": True, "bytes": len(workbook_bytes)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def receive_state(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self.send_error(400, "Empty state")
            return
        if length > 20 * 1024 * 1024:
            self.send_error(413, "State payload too large")
            return

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            state = save_state(data)
        except Exception as exc:
            self.send_error(400, f"Invalid state JSON: {exc}")
            return

        self.send_json({"ok": True, "updatedAt": state["exportedAt"]})


def main():
    init_db()
    os.chdir(ROOT)
    raw_args = sys.argv[1:]
    open_browser = "--open" in raw_args
    lan_mode = "--lan" in raw_args
    host = "0.0.0.0" if lan_mode else "127.0.0.1"
    args = [arg for arg in raw_args if arg not in ("--open", "--lan")]
    preferred_port = int(args[0]) if args else 8787

    if is_port_in_use(preferred_port) and existing_app_server_ready(preferred_port):
        url = f"{app_url(preferred_port)}?v=existing"
        if not lan_mode:
            print(f"SYDRRO-TECH local server is already running: {url}", flush=True)
            if open_browser:
                open_browser_url(url)
            return
        print(f"Port {preferred_port} already has a local SYDRRO-TECH server.", flush=True)
        print("A LAN server will start on the next available port.", flush=True)

    server = None
    port = preferred_port
    for candidate in range(preferred_port, preferred_port + 30):
        if is_port_in_use(candidate):
            continue
        try:
            server = ThreadingHTTPServer((host, candidate), SydrroHandler)
            port = candidate
            break
        except OSError:
            continue

    if server is None:
        raise RuntimeError(f"No available local port from {preferred_port} to {preferred_port + 29}")

    local_url = f"{app_url(port)}?v={os.getpid()}"
    print(f"SYDRRO-TECH local server: {local_url}", flush=True)
    if lan_mode:
        lan_urls = [f"{app_url(port, ip)}?v={os.getpid()}" for ip in get_lan_ipv4_addresses()]
        if lan_urls:
            print("Open this URL on your phone while connected to the same Wi-Fi:", flush=True)
            for index, lan_url in enumerate(lan_urls):
                tip = "  (try this first)" if index == 0 else ""
                print(f"  {lan_url}{tip}", flush=True)
        else:
            print("LAN mode is enabled, but no LAN IPv4 address was detected.", flush=True)
    print(f"Unified SQLite data source: {DB_PATH}", flush=True)
    print(f"JSON mirror file: {BACKUP_PATH}", flush=True)

    if open_browser:
        threading.Timer(0.6, lambda: open_browser_url(local_url)).start()

    server.serve_forever()


if __name__ == "__main__":
    main()
