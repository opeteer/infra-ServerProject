#!/usr/bin/env python3
"""
==============================================================================
Script Otomasi Registrasi Aplikasi Baru untuk Rocky Server Gateway (V2 - Robust)
==============================================================================
Didesain untuk dipanggil oleh Rocky Provisioning Bot atau CLI secara mandiri.
Fitur Utama:
  1. Smart Merge compose.yaml (Mempertahankan komentar YAML, volume, dan environment lama)
  2. Pendaftaran named volume otomatis di blok root volumes:
  3. Pembuatan rute Nginx modular dengan dukungan WebSocket & Streaming timeout
  4. Proteksi rute kustom (tidak menimpa rute lama kecuali diminta dengan --force)
  5. File locking fcntl & atomic write untuk proteksi konkurensi
  6. Pendaftaran kartu layanan di gateway-ui/apps.json
  7. docker compose up -d <app> & hot-reload Nginx gateway
  8. Respons JSON terstruktur untuk bot dan CI/CD
==============================================================================
"""

import os
import sys
import json
import argparse
import subprocess
import fcntl
import contextlib

# Gunakan ruamel.yaml untuk round-trip parsing (mempertahankan komentar), dengan fallback ke PyYAML
try:
    from ruamel.yaml import YAML
    RUAMEL_AVAILABLE = True
except ImportError:
    RUAMEL_AVAILABLE = False
    import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMPOSE_FILE = os.path.join(BASE_DIR, 'compose.yaml')
ROUTES_DIR = os.path.join(BASE_DIR, 'conf.d', 'routes')
APPS_JSON_FILE = os.path.join(BASE_DIR, 'gateway-ui', 'apps.json')
LOCK_FILE = os.path.join(BASE_DIR, '.compose.lock')


@contextlib.contextmanager
def file_lock(lock_path: str):
    """File lock berbasis fcntl untuk mencegah race condition antar-proses."""
    with open(lock_path, 'a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def normalize_path(path: str) -> str:
    path = path.strip()
    if not path.startswith('/'):
        path = '/' + path
    if not path.endswith('/'):
        path = path + '/'
    return path


def load_compose():
    if not os.path.exists(COMPOSE_FILE):
        return {}
    with open(COMPOSE_FILE, 'r') as f:
        if RUAMEL_AVAILABLE:
            y = YAML()
            y.preserve_quotes = True
            return y.load(f) or {}
        else:
            return yaml.safe_load(f) or {}


def save_compose(data):
    tmp_file = f"{COMPOSE_FILE}.tmp"
    with open(tmp_file, 'w') as f:
        if RUAMEL_AVAILABLE:
            y = YAML()
            y.preserve_quotes = True
            y.indent(mapping=2, sequence=4, offset=2)
            y.dump(data, f)
        else:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    os.replace(tmp_file, COMPOSE_FILE)


def update_compose(app_name: str, image: str, port: int, volumes: list = None, env_vars: list = None, preserve: bool = True):
    volumes = volumes or []
    env_vars = env_vars or []

    with file_lock(LOCK_FILE):
        data = load_compose()

        if 'services' not in data or data['services'] is None:
            data['services'] = {}

        existing = data['services'].get(app_name) if preserve else None

        if existing:
            # Smart Merge: Pertahankan konfigurasi service lama
            existing['image'] = image
            existing.setdefault('container_name', f"{app_name}-web")
            existing.setdefault('restart', 'unless-stopped')

            # Pastikan network server-net terhubung
            networks = existing.setdefault('networks', [])
            if 'server-net' not in networks:
                networks.append('server-net')

            # Pastikan label watchtower terpasang
            labels = existing.setdefault('labels', [])
            wt_label = "com.centurylinklabs.watchtower.enable=true"
            if wt_label not in labels:
                labels.append(wt_label)

            # Merge environment variables
            current_env = existing.setdefault('environment', [])
            if isinstance(current_env, list):
                env_map = {}
                for item in current_env:
                    if '=' in str(item):
                        k, v = str(item).split('=', 1)
                        env_map[k] = v
                    else:
                        env_map[str(item)] = ''

                # Update / enforce PORT
                env_map['PORT'] = str(port)

                # Gabungkan env_vars baru
                for item in env_vars:
                    if '=' in str(item):
                        k, v = str(item).split('=', 1)
                        env_map[k] = v
                    else:
                        env_map[str(item)] = ''

                merged_env = []
                for k, v in env_map.items():
                    merged_env.append(f"{k}={v}" if v else k)
                existing['environment'] = merged_env

            elif isinstance(current_env, dict):
                current_env['PORT'] = str(port)
                for item in env_vars:
                    if '=' in str(item):
                        k, v = str(item).split('=', 1)
                        current_env[k] = v

            # Merge volumes
            current_vols = existing.setdefault('volumes', [])
            for vol in volumes:
                if vol not in current_vols:
                    current_vols.append(vol)

            service_def = existing
        else:
            # Service baru
            env_list = [f"PORT={port}"]
            for ev in env_vars:
                if not any(ev.split('=')[0] == x.split('=')[0] for x in env_list):
                    env_list.append(ev)

            service_def = {
                'image': image,
                'container_name': f"{app_name}-web",
                'restart': 'unless-stopped',
                'networks': ['server-net'],
                'environment': env_list,
                'labels': ["com.centurylinklabs.watchtower.enable=true"]
            }
            if volumes:
                service_def['volumes'] = list(volumes)
            data['services'][app_name] = service_def

        # Pastikan network global server-net terdefinisi
        if 'networks' not in data or data['networks'] is None:
            data['networks'] = {}
        if 'server-net' not in data['networks']:
            data['networks']['server-net'] = {'name': 'server-net', 'driver': 'bridge'}

        # Otomatis daftarkan named volumes di root volumes:
        all_vols = service_def.get('volumes', [])
        if all_vols:
            if 'volumes' not in data or data['volumes'] is None:
                data['volumes'] = {}
            for vol in all_vols:
                source = str(vol).split(':')[0].strip()
                # Named volume: tidak diawali dengan /, ./, ../, atau ~
                if not (source.startswith('/') or source.startswith('./') or source.startswith('../') or source.startswith('~')):
                    if source not in data['volumes']:
                        data['volumes'][source] = None

        save_compose(data)


def create_nginx_route(app_name: str, subpath: str, port: int, websocket: bool = False, force: bool = False):
    os.makedirs(ROUTES_DIR, exist_ok=True)
    conf_path = os.path.join(ROUTES_DIR, f"{app_name}.conf")
    container_name = f"{app_name}-web"
    clean_subpath = subpath.rstrip('/')

    # Jika rute sudah ada dan tidak diforce, pertahankan konfigurasi yang ada
    if os.path.exists(conf_path) and not force:
        return False, f"File rute '{conf_path}' sudah ada; konfigurasi lama dipertahankan."

    ws_block = ""
    if websocket:
        ws_block = """
    # Dukungan WebSocket & Realtime Communication
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    # Optimasi Streaming Media & Unduhan File Besar
    proxy_buffering off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    client_max_body_size 500M;
"""

    content = f"""# ==============================================================================
# Route Plug-in: {app_name} (Auto-generated by register-app)
# ==============================================================================

# Normalisasi trailing slash untuk path {clean_subpath}
location = {clean_subpath} {{
    return 301 {subpath};
}}

location {subpath} {{
    proxy_pass http://{container_name}:{port}/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix {clean_subpath};
{ws_block}}}
"""
    with open(conf_path, 'w') as f:
        f.write(content)
    return True, f"File rute '{conf_path}' berhasil dibuat (WebSocket: {websocket})."


def update_apps_json(app_id: str, name: str, subpath: str, icon: str, desc: str, tags: list, preserve: bool = True):
    with file_lock(LOCK_FILE):
        apps = []
        if os.path.exists(APPS_JSON_FILE):
            try:
                with open(APPS_JSON_FILE, 'r') as f:
                    apps = json.load(f)
            except Exception:
                apps = []

        DEFAULT_DESC = "Aplikasi web di server rocky."
        DEFAULT_ICON = "🚀"

        found = False
        for i, app in enumerate(apps):
            if app.get('id') == app_id:
                found = True
                if preserve:
                    if icon == DEFAULT_ICON and 'icon' in app:
                        icon = app['icon']
                    if desc == DEFAULT_DESC and 'desc' in app:
                        desc = app['desc']
                    if tags == ['Web', 'Docker'] and 'tags' in app:
                        tags = app['tags']
                    if (name == app_id or not name) and 'name' in app:
                        name = app['name']

                app_entry = {
                    "id": app_id,
                    "name": name,
                    "path": subpath,
                    "icon": icon,
                    "desc": desc,
                    "tags": tags,
                    "status": "Live"
                }
                if 'color' in app:
                    app_entry['color'] = app['color']
                apps[i] = app_entry
                break

        if not found:
            app_entry = {
                "id": app_id,
                "name": name,
                "path": subpath,
                "icon": icon,
                "desc": desc,
                "tags": tags,
                "status": "Live"
            }
            apps.append(app_entry)

        with open(APPS_JSON_FILE, 'w') as f:
            json.dump(apps, f, indent=2, ensure_ascii=False)
            f.write('\n')


def run_command(cmd: list):
    try:
        res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, check=True)
        return True, res.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip()
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Otomasi Registrasi Aplikasi ke Gateway Server Rocky (V2)")
    parser.add_argument('--name', '-n', required=True, help="Nama identifier aplikasi (misal: kasir)")
    parser.add_argument('--title', '-t', help="Judul tampilan aplikasi (misal: 'Sistem Kasir')")
    parser.add_argument('--image', '-i', required=True, help="Image Docker (misal: ghcr.io/opeteer/kasir:latest)")
    parser.add_argument('--port', '-p', type=int, default=3000, help="Port internal kontainer (default: 3000)")
    parser.add_argument('--path', '-u', help="Subpath URL (misal: /kasir/)")
    parser.add_argument('--icon', default="🚀", help="Emoji icon (default: 🚀)")
    parser.add_argument('--desc', default="Aplikasi web di server rocky.", help="Deskripsi singkat aplikasi")
    parser.add_argument('--tags', default="Web,Docker", help="Daftar tag dipisahkan koma (misal: Node.js,React)")
    parser.add_argument('--websocket', action='store_true', default=False, help="Aktifkan dukungan WebSocket & streaming timeout")
    parser.add_argument('--volume', '-v', action='append', default=[], help="Daftar volume persisten (dapat ditentukan berulang)")
    parser.add_argument('--env', '-e', action='append', default=[], help="Daftar environment variable tambahan KEY=VAL")
    parser.add_argument('--preserve', dest='preserve', action='store_true', default=True, help="Pertahankan konfigurasi lama jika ada (default: True)")
    parser.add_argument('--no-preserve', dest='preserve', action='store_false', help="Abaikan konfigurasi lama dan buat baru")
    parser.add_argument('--force', action='store_true', default=False, help="Paksa penulisan ulang file rute Nginx jika sudah ada")
    parser.add_argument('--json-output', action='store_true', help="Keluarkan hasil murni dalam format JSON")

    args = parser.parse_args()

    app_id = args.name.lower().strip().replace(' ', '-')
    title = args.title or args.name
    subpath = normalize_path(args.path or f"/{app_id}/")
    tags = [t.strip() for t in args.tags.split(',') if t.strip()]

    result = {
        "status": "pending",
        "app_id": app_id,
        "name": title,
        "path": subpath,
        "image": args.image,
        "port": args.port,
        "websocket": args.websocket,
        "volumes": args.volume,
        "env": args.env
    }

    try:
        # 1. Update compose.yaml dengan Smart Merge
        update_compose(
            app_name=app_id,
            image=args.image,
            port=args.port,
            volumes=args.volume,
            env_vars=args.env,
            preserve=args.preserve
        )

        # 2. Buat atau pertahankan Nginx route
        route_created, route_msg = create_nginx_route(
            app_name=app_id,
            subpath=subpath,
            port=args.port,
            websocket=args.websocket,
            force=args.force
        )
        result["route_action"] = route_msg

        # 3. Update gateway-ui/apps.json
        update_apps_json(app_id, title, subpath, args.icon, args.desc, tags, preserve=args.preserve)

        # 4. Nyalakan kontainer jika docker tersedia
        container_started, container_msg = run_command(['docker', 'compose', 'up', '-d', app_id])

        # 5. Reload Nginx gateway
        reload_ok, reload_msg = run_command([os.path.join(BASE_DIR, 'funnel.sh'), 'reload'])

        result["status"] = "success"
        result["container_started"] = container_started
        result["reload_ok"] = reload_ok
        result["message"] = f"Aplikasi '{title}' berhasil diproses di subpath {subpath}!"

        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print("==================================================")
            print("🎉 PROSES REGISTRASI APLIKASI SELESAI!")
            print(f"📦 ID Aplikasi     : {app_id}")
            print(f"🌐 Path URL Akses  : {subpath}")
            print(f"🐳 Image Kontainer : {args.image}")
            print(f"🔌 Port Internal   : {args.port}")
            print(f"⚡ WebSocket       : {'Aktif' if args.websocket else 'Non-aktif'}")
            print(f"📁 Rute Status     : {route_msg}")
            print("==================================================")

        sys.exit(0)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"❌ Terjadi kesalahan: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
