#!/usr/bin/env python3
"""
==============================================================================
Rocky Provisioning Bot - Webhook API Service (V2 - Concurrency-Safe & Extended)
==============================================================================
Bot ini mendengarkan request HTTP POST dari GitHub Actions untuk secara
otomatis mendaftarkan, mengkonfigurasi, dan menyalakan kontainer baru di server.
Zero-Touch Provisioning (Meniadakan konfigurasi manual gateway & compose).
==============================================================================
"""

import os
import sys
import json
import logging
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTER_SCRIPT = os.path.join(BASE_DIR, 'register-app.py')
ENV_FILE = os.path.join(BASE_DIR, '.env')

# Global concurrency lock untuk memastikan eksekusi register-app.py berjalan serial (atomic)
provision_lock = threading.Lock()

def load_env():
    env_vars = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")
    return env_vars

env_config = load_env()
BOT_PORT = int(os.environ.get('BOT_PORT', env_config.get('BOT_PORT', 8090)))
BOT_HOST = os.environ.get('BOT_HOST', '0.0.0.0')
AUTH_TOKEN = os.environ.get('BOT_TOKEN', env_config.get('BOT_TOKEN', env_config.get('WATCHTOWER_TOKEN', '')))

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class ProvisionRequestHandler(BaseHTTPRequestHandler):
    def send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        clean_path = self.path.split('?')[0].rstrip('/')
        if clean_path in ['/health', '/api/provision/health', '/api/provision', '']:
            self.send_json(200, {
                "status": "online",
                "service": "Rocky Provisioning Bot API",
                "version": "2.0.0",
                "message": "Ready to receive provisioning requests from GitHub Actions"
            })
        else:
            self.send_json(404, {"error": "Not Found"})

    def do_POST(self):
        clean_path = self.path.split('?')[0].rstrip('/')
        if clean_path not in ['/provision', '/api/provision']:
            self.send_json(404, {"error": f"Endpoint '{clean_path}' not found. Use /api/provision"})
            return

        # 1. Validasi Autentikasi Token
        if AUTH_TOKEN:
            auth_header = self.headers.get('Authorization', '')
            expected_header = f"Bearer {AUTH_TOKEN}"
            if auth_header != expected_header:
                logging.warning(f"Unauthorized access attempt from {self.client_address[0]}")
                self.send_json(401, {
                    "status": "error",
                    "error": "Unauthorized. Invalid or missing Authorization Bearer token."
                })
                return

        # 2. Baca Body JSON
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length <= 0:
                self.send_json(400, {"status": "error", "error": "Request body cannot be empty"})
                return

            body = self.rfile.read(content_length).decode('utf-8')
            payload = json.loads(body)
        except Exception as e:
            logging.error(f"Failed to parse JSON body: {e}")
            self.send_json(400, {"status": "error", "error": f"Malformed JSON: {str(e)}"})
            return

        # 3. Validasi Field Wajib
        app_name = payload.get('name') or payload.get('app_name')
        image = payload.get('image')

        if not app_name or not image:
            self.send_json(400, {
                "status": "error",
                "error": "Missing required fields: 'name' and 'image' are mandatory."
            })
            return

        title = payload.get('title') or app_name
        port = str(payload.get('port', 3000))
        subpath = payload.get('path') or f"/{app_name}/"
        icon = payload.get('icon', '🚀')
        desc = payload.get('desc', 'Aplikasi web di server rocky.')
        tags = payload.get('tags', 'Web,Docker')
        if isinstance(tags, list):
            tags = ','.join(tags)

        # Extended fields: WebSocket, Volumes, Environment, Flags
        websocket = payload.get('websocket', False)
        if isinstance(websocket, str):
            websocket = websocket.lower() in ['true', '1', 'yes']

        volumes = payload.get('volumes', [])
        if isinstance(volumes, str):
            volumes = [v.strip() for v in volumes.split(',') if v.strip()]

        custom_env = payload.get('env', []) or payload.get('environment', [])
        if isinstance(custom_env, dict):
            custom_env = [f"{k}={v}" for k, v in custom_env.items()]
        elif isinstance(custom_env, str):
            custom_env = [e.strip() for e in custom_env.split(',') if e.strip()]

        preserve = payload.get('preserve', True)
        force = payload.get('force', False)

        logging.info(
            f"Received provisioning request for app: '{app_name}' "
            f"(Image: {image}, Port: {port}, WS: {websocket}, Vols: {len(volumes)}, Env: {len(custom_env)})"
        )

        # 4. Susun Argumen CLI register-app.py
        cmd = [
            sys.executable,
            REGISTER_SCRIPT,
            '--name', app_name,
            '--title', title,
            '--image', image,
            '--port', port,
            '--path', subpath,
            '--icon', icon,
            '--desc', desc,
            '--tags', tags,
            '--json-output'
        ]

        if websocket:
            cmd.append('--websocket')

        if not preserve:
            cmd.append('--no-preserve')

        if force:
            cmd.append('--force')

        for vol in volumes:
            cmd.extend(['--volume', str(vol)])

        for env_item in custom_env:
            cmd.extend(['--env', str(env_item)])

        # 5. Eksekusi register-app.py di bawah perlindungan Mutex Lock
        try:
            with provision_lock:
                proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, check=True)
                output_json = json.loads(proc.stdout)

            logging.info(f"App '{app_name}' successfully provisioned and deployed!")
            self.send_json(200, output_json)

        except subprocess.CalledProcessError as e:
            logging.error(f"register-app.py failed: {e.stderr}")
            self.send_json(500, {
                "status": "error",
                "error": "Failed to execute register-app.py",
                "details": e.stderr
            })
        except Exception as e:
            logging.error(f"Unexpected error during provisioning: {e}")
            self.send_json(500, {
                "status": "error",
                "error": str(e)
            })

def run_server():
    server_address = (BOT_HOST, BOT_PORT)
    httpd = ThreadedHTTPServer(server_address, ProvisionRequestHandler)
    logging.info(f"🤖 Rocky Provisioning Bot listening on {BOT_HOST}:{BOT_PORT}")
    logging.info(f"🔑 Auth Token configured: {'Yes (Protected)' if AUTH_TOKEN else 'No (Warning: Open)'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down bot server...")
        httpd.server_close()

if __name__ == '__main__':
    run_server()
