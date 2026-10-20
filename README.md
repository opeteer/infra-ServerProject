# Rocky Server Modular Infrastructure & Gateway Platform

Infrastruktur runtime terpadu dan modular untuk server **`rocky`**. Dirancang menggunakan arsitektur **Plug & Play** berbasis **Central Reverse Proxy Gateway (`server-proxy`)**, **Central CD Webhook (`server-watchtower`)**, **Shared Docker Network (`server-net`)**, dan **Dynamic Web Grafis Launchpad**.

File inti server bersifat **permanen**; menambahkan atau menghapus proyek web tidak akan pernah menyentuh file inti server.

---

## 🏛️ 1. Arsitektur Sistem

Server `rocky` mengadopsi pola **Enterprise Edge Gateway, Self-Service Provisioning Bot, & Centralized Continuous Deployment (CD)**:

```mermaid
flowchart TD
    Client["🌐 Klien Publik / Internet<br/>(https://rocky...ts.net)"] --> TS["🛡️ Tailscale Funnel<br/>(Enkripsi HTTPS & Zero Open Port Firewall)"]
    
    subgraph HostServer["🖥️ Server Rocky (infra-ServerProject)"]
        TS --> Proxy["🔀 server-proxy (Nginx Gateway Engine)"]
        WT["⚙️ server-watchtower (Central CD Webhook)"]
        Bot["🤖 Rocky Provisioning Bot API (:8090)"]
        Net["🌐 Docker Network: server-net"]
        
        Proxy -->|"Path / (Root)"| WebGrafis["🖥️ Dynamic Web Grafis Launchpad<br/>(index.html membaca apps.json)"]
        Proxy -->|"Path /v1/update"| WT
        Proxy -->|"Path /api/provision"| Bot
        
        Bot -->|"1. Injeksi Rute"| ModularRoutes["📁 conf.d/routes/"]
        Bot -->|"2. Injeksi Kartu"| AppsJSON["gateway-ui/apps.json"]
        Bot -->|"3. docker compose up & reload"| Containers["📦 Kontainer Layanan (server-net)"]
        
        ModularRoutes --> Proxy
        Proxy --> Containers
        WT -.->|"Auto-Update via Docker Socket"| Containers
    end

    subgraph GitHubEcosystem["🐙 GitHub Repositories (CI/CD)"]
        Repo["Repo Web Baru"] -->|"1. Push Image"| GHCR["ghcr.io"]
        Repo -.->|"2. POST /api/provision (Auto-Setup)"| Proxy
        Repo -.->|"3. POST /v1/update (Auto-Deploy)"| Proxy
    end
```

### Karakteristik Utama Arsitektur:
1. **Edge Security**: Tailscale Funnel mengisolasi server dari internet publik. Tidak ada port 80/443 yang dibuka di router fisik/IP publik langsung, melainkan melalui tunnel terenkripsi Tailscale.
2. **Zero-Coupling Gateway**: `server-proxy` (Nginx) memuat rute secara dinamis dari file `conf.d/routes/*.conf`. Kerusakan sintaks pada satu proyek baru tidak akan mempengaruhi proyek lainnya.
3. **Zero-Touch Provisioning Bot**: Bot API mandiri di endpoint `/api/provision` membaca payload GitHub Actions dan otomatis mendaftarkan kontainer baru tanpa perlu login ke terminal server.
4. **Single Central CD**: Hanya ada **1 instance Watchtower** untuk seluruh server yang mendengarkan endpoint `/v1/update`. Tidak ada overhead duplikasi proses CD.
5. **Data-Driven Front Door**: Halaman beranda `/` menyajikan Web Grafis yang merender katalog proyek secara otomatis dari data JSON (`apps.json`).

---

## 🐳 2. Spesifikasi & Standar Teknologi Kontainer

Untuk menjaga efisiensi memori, keamanan, dan portabilitas di server `rocky`, setiap repositori web baru **wajib** mengikuti standar kontainerisasi berikut:

### A. Engine & Format Kontainer
* **Format**: OCI-Compliant Container (*Open Container Initiative*).
* **Runtime**: Docker Engine / Docker Compose.
* **Registry**: **GitHub Container Registry (`ghcr.io`)** – Terintegrasi langsung dengan GitHub Actions dengan hak akses token bawaan (`GITHUB_TOKEN`).

### B. Kebijakan Base Image (*Base Image Policy*)
* **Wajib Menggunakan Base Image Minimalis**:
  * Gunakan varian **Alpine Linux** (misal: `node:20-alpine`, `python:3.12-alpine`, `golang:1.23-alpine`, `eclipse-temurin:21-alpine`) atau **Distroless**.
  * ❌ **Dilarang keras** menggunakan base image OS penuh seperti `ubuntu:latest` atau `debian:latest` untuk runtime aplikasi karena ukurannya yang besar (> 500MB) dan memiliki *attack surface* kerentanan keamanan yang tinggi.
* **Target Ukuran Image Akhir**: Idealnya di bawah **150 MB** (khusus Node/Go/Python) atau di bawah **250 MB** (Java/Spring Boot).

### C. Wajib Menerapkan Multi-Stage Build
Setiap Dockerfile harus memisahkan tahap kompilasi (*builder*) dengan tahap produksi (*runner*):
* **Stage 1 (Builder)**: Mengunduh dependensi lengkap, compilers, SDK, dan mem-build source code.
* **Stage 2 (Runner / Production)**: Hanya menyalin file biner/distribusi yang telah jadi ke runtime yang bersih tanpa *devDependencies* atau compiler tools.

### D. Keamanan Kontainer (*Security Best Practices*)
1. **Non-Root User**: Jalankan aplikasi menggunakan user non-root (misal: `USER node` pada Node.js atau user khusus `appuser`), bukan sebagai `root`.
2. **Environment Port Flexibility**: Aplikasi harus membaca port dari environment variable `PORT` (dengan default fallback).
3. **Stateless Runtime**: Simpan file unggahan (*uploads*) atau data persisten pada database atau Docker Volume terpisah, bukan di dalam layer kontainer lokal.

---

## 📦 3. Apa Saja yang Perlu Dibuat di Dalam Repo Web Baru?

Setiap kali Anda membuat atau mengonfigurasi repositori web baru, pastikan file-file berikut ada di dalam root repo Anda:

```
repo-web-baru/
├── Dockerfile                  # [Wajib] Multi-stage container build
├── .dockerignore               # [Wajib] Mencegah sampah lokal masuk ke image
└── .github/
    └── workflows/
        └── deploy.yml          # [Wajib] Pipeline otomatisasi CI/CD & webhook
```

### 1. File `.dockerignore`
Wajib ada di root repo agar file sementara lokal tidak ikut terkirim ke Docker Daemon:
```text
.git
.github
node_modules
build
dist
.env
.env.local
*.log
.DS_Store
Thumbs.db
```

### 2. File `Dockerfile` (Contoh Multi-Stage Berdasarkan Teknologi)

#### Pilihan A: Node.js / React / Vue / Vite / SPA (Disajikan Nginx Ringan)
```dockerfile
# Stage 1: Build source code
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Production web server
FROM nginx:alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

#### Pilihan B: Node.js Backend / Express / NestJS
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=builder /app/dist ./dist
USER node
EXPOSE 3000
CMD ["node", "dist/main.js"]
```

#### Pilihan C: Python (FastAPI / Flask)
```dockerfile
FROM python:3.12-alpine AS runner
WORKDIR /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Pilihan D: Go (Golang)
```dockerfile
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o server .

FROM scratch AS runner
WORKDIR /app
COPY --from=builder /app/server .
EXPOSE 8080
CMD ["/app/server"]
```

### 3. File GitHub Actions Workflow Zero-Touch (`.github/workflows/deploy.yml`)
Salin file workflow berikut ke repositori baru Anda (`.github/workflows/deploy.yml`). Alur ini **100% Zero-Touch**: Otomatis mem-build image, memanggil **Rocky Provisioning Bot** untuk mendaftarkan dan menyalakan kontainer (meniadakan semua langkah manual di server), lalu memicu Watchtower:

```yaml
name: Build, Push to GHCR, and Auto-Deploy via Bot

on:
  push:
    branches:
      - main
  workflow_dispatch: # Mendukung pemicu manual dari tab Actions di GitHub

jobs:
  build-push-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GitHub Container Registry (GHCR)
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and Push Docker Image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./Dockerfile
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/${{ github.event.repository.name }}:latest
            ghcr.io/${{ github.repository_owner }}/${{ github.event.repository.name }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      # ======================================================================
      # OTOMASI BOT: Meniadakan Bagian B (Mendaftarkan Kontainer, Rute & Web)
      # ======================================================================
      - name: Auto-Provision via Rocky Bot API
        if: ${{ env.WATCHTOWER_URL != '' }}
        env:
          WATCHTOWER_URL: ${{ secrets.WATCHTOWER_WEBHOOK_URL }}
        run: |
          BASE_URL="${WATCHTOWER_URL%/v1/update}"
          echo "🤖 Menghubungi Rocky Provisioning Bot di ${BASE_URL}/api/provision..."
          
          # Payload otomatis membaca nama repo Anda
          curl -s -X POST \
            -H "Authorization: Bearer ${{ secrets.WATCHTOWER_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d '{
              "name": "${{ github.event.repository.name }}",
              "title": "${{ github.event.repository.name }}",
              "image": "ghcr.io/${{ github.repository_owner }}/${{ github.event.repository.name }}:latest",
              "port": 3000,
              "path": "/${{ github.event.repository.name }}/",
              "icon": "🚀",
              "desc": "Aplikasi ${{ github.event.repository.name }} di server rocky.",
              "tags": "Web,Docker,AutoDeployed"
            }' \
            "${BASE_URL}/api/provision" || true
          
          echo "🚀 Memicu update Watchtower..."
          curl -f -X POST \
            -H "Authorization: Bearer ${{ secrets.WATCHTOWER_TOKEN }}" \
            "${BASE_URL}/v1/update?async=true" || true
          echo "✅ Sinyal deployment dan provisioning selesai!"
```

---

## 🔄 4. Penjelasan Detail Alur CI/CD (Berdasarkan Standar `siaProject`)

Alur Continuous Integration & Continuous Deployment (CI/CD) berjalan otomatis tanpa intervensi manual:

```mermaid
sequenceDiagram
    autonumber
    actor Dev as 👨‍💻 Developer
    participant GH as 🐙 GitHub Repository
    participant GHA as ⚙️ GitHub Actions Runner
    participant GHCR as 📦 GitHub Container Registry (ghcr.io)
    participant Proxy as 🔀 server-proxy (Nginx Gateway)
    participant WT as 🛠️ server-watchtower (Central CD)
    participant Container as 🚀 App Container (server-net)

    Dev->>GH: git push origin main (atau Manual Dispatch)
    GH->>GHA: Memicu workflow deploy.yml
    GHA->>GHA: Checkout kode & Set up Buildx + Cache GHA
    GHA->>GHCR: Login otomatis dengan GITHUB_TOKEN
    GHA->>GHCR: Build & Push Image (:latest & :${{ github.sha }})
    GHA->>Proxy: POST /v1/update?async=true (Bearer Token)
    Proxy->>WT: Meneruskan webhook ke Watchtower
    WT-->>GHA: HTTP 200 OK (Sinyal diterima secara asinkron)
    GHA-->>Dev: Pipeline CI/CD Sukses ✅
    
    critical Proses Update di Latar Belakang (Server)
        WT->>GHCR: Cek hash image terbaru
        WT->>GHCR: Pull image baru
        WT->>Container: Hentikan kontainer lama & nyalakan kontainer baru
    end
    Note over Container: Aplikasi baru aktif seketika tanpa downtime!
```

### Keunggulan Alur Ini:
1. **GitHub Actions Cache (`type=gha`)**: Mempercepat proses build Docker hingga 70-80% pada push berikutnya karena layer-layer yang tidak berubah otomatis di-cache oleh GitHub.
2. **Dual-Tagging (`:latest` & `:${{ github.sha }}`)**: Menjaga fleksibilitas deployment live (`:latest`) sekaligus menyediakan riwayat rollback yang terlacak berdasarkan commit hash (`:${{ github.sha }}`).
3. **Panggilan Asinkron (`?async=true`)**: Mencegah GitHub Actions mengalami *timeout* atau menggantung menunggu Watchtower selesai mengunduh image. GitHub Actions akan langsung sukses begitu server menerima instruksi.
4. **Proteksi Secret (`if: ${{ env.WATCHTOWER_URL != '' }}`)**: Pipeline build tidak akan crash jika secret webhook belum disetel di repository baru.

---

## 🛠️ 5. Panduan Langkah Onboarding (*Step-by-Step Onboarding*)

Tersedia **2 Metode** untuk mendaftarkan repositori web baru:

---

### ⚡ METODE 1: 100% Otomatis via Bot (*Rekomendasi - Zero Server Touch*)
Jika Anda menggunakan file workflow [deploy.yml](file:///home/opeteer/infra-ServerProject/README.md#3-file-github-actions-workflow-zero-touch-githubworkflowsdeployyml) di atas:
1. **Di GitHub Repo Baru**: Commit file `Dockerfile`, `.dockerignore`, dan `.github/workflows/deploy.yml`.
2. **Daftarkan 2 Secrets di GitHub** (`Settings` $\rightarrow$ `Secrets and variables` $\rightarrow$ `Actions`):
   * **`WATCHTOWER_TOKEN`**: Isi token dari [.env](file:///home/opeteer/infra-ServerProject/.env) server Anda.
   * **`WATCHTOWER_WEBHOOK_URL`**: `https://rocky.<tailnet>.ts.net`
3. **Lakukan Push**: `git push origin main`.
4. **SELESAI!** Rocky Provisioning Bot akan otomatis mendaftarkan kontainer di `compose.yaml`, membuat rute Nginx, mendaftarkan kartu di dashboard, menyalakan kontainer, dan memuat ulang Nginx. Anda **tidak perlu membuka server sama sekali**.

---

### 🔧 METODE 2: Manual via CLI Script / Server (*Alternatif*)
Gunakan metode ini jika Anda ingin mendaftarkan aplikasi secara manual dari terminal server Rocky:

#### Opsi 2A: Menggunakan Skrip Otomasi Cepat (1 Detik)
Cukup jalankan satu baris perintah di server:
```bash
./funnel.sh register \
  --name "nama-proyek" \
  --image "ghcr.io/username/nama-proyek:latest" \
  --port 3000 \
  --path "/nama-proyek/" \
  --icon "🚀" \
  --desc "Deskripsi singkat aplikasi"
```

#### Opsi 2B: Manual Step-by-Step
1. **Daftarkan Kontainer di [compose.yaml](file:///home/opeteer/infra-ServerProject/compose.yaml)** di bawah network `server-net`:
   ```yaml
     nama-proyek:
       image: ghcr.io/username/nama-proyek:latest
       container_name: nama-proyek-web
       restart: unless-stopped
       networks:
         - server-net
       environment:
         - PORT=3000
       labels:
         - "com.centurylinklabs.watchtower.enable=true"
   ```
   Lalu jalankan: `docker compose up -d nama-proyek`
2. **Buat File Rute Mandiri** di `conf.d/routes/<nama-proyek>.conf`:
   ```nginx
   location /nama-proyek/ {
       proxy_pass http://nama-proyek-web:3000/;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
   }
   ```
3. **Daftarkan Kartu di [gateway-ui/apps.json](file:///home/opeteer/infra-ServerProject/gateway-ui/apps.json)**:
   ```json
   {
     "id": "nama-proyek",
     "name": "Nama Proyek Web Anda",
     "path": "/nama-proyek/",
     "icon": "🚀",
     "desc": "Deskripsi singkat layanan baru ini.",
     "tags": ["Node.js", "Tailwind", "PostgreSQL"],
     "status": "Live"
   }
   ```
4. **Muat Ulang Gateway**:
   ```bash
   ./funnel.sh reload
   ```

**Selesai!** 
* Web langsung muncul di Launchpad beranda `https://rocky...ts.net/`.
* Dapat diakses via URL `https://rocky...ts.net/nama-proyek/`.
* Setiap kali Anda melakukan `git push` di repositori tersebut, GitHub Actions akan otomatis memicu Central Watchtower untuk mengunduh dan me-restart kontainer aplikasi tersebut tanpa mengganggu aplikasi lainnya!

---

## ⚙️ 6. Perintah Manajemen Server ([`funnel.sh`](file:///home/opeteer/infra-ServerProject/funnel.sh))

```bash
# Menjalankan Gateway & Tailscale Funnel
./funnel.sh start

# Memeriksa status dan public URL
./funnel.sh status

# Hot-reload Nginx saat ada rute/app baru tanpa downtime
./funnel.sh reload

# Mendaftarkan aplikasi baru via CLI
./funnel.sh register --name "kasir" --image "ghcr.io/opeteer/kasir:latest" --port 3000 --path "/kasir/"

# Menghentikan Tailscale Funnel
./funnel.sh stop
```

---

## 🤖 7. Integrasi Bot Otomasi Mandiri (*Custom ChatOps / Provisioning Bot*)

Jika Anda membangun **Bot Anda Sendiri** (Telegram Bot, Discord Bot, Webhook Service, atau CLI Assistant), bot Anda cukup mengeksekusi skrip [`register-app.sh`](file:///home/opeteer/infra-ServerProject/register-app.sh) di server:

### A. Perintah yang Dipanggil oleh Bot Anda
```bash
./register-app.sh \
  --name "kasir" \
  --title "Sistem Kasir Toko" \
  --image "ghcr.io/opeteer/kasir:latest" \
  --port 3000 \
  --path "/kasir/" \
  --icon "💳" \
  --desc "Aplikasi Kasir POS & Inventaris" \
  --tags "Node.js,Vue,PostgreSQL" \
  --json-output
```

### B. Format Output JSON yang Diterima Bot Anda
Skrip akan mengembalikan respons JSON terstruktur dengan *exit code* `0` (sukses) atau `1` (gagal):

```json
{
  "status": "success",
  "app_id": "kasir",
  "name": "Sistem Kasir Toko",
  "path": "/kasir/",
  "image": "ghcr.io/opeteer/kasir:latest",
  "port": 3000,
  "container_started": true,
  "reload_ok": true,
  "message": "Aplikasi 'Sistem Kasir Toko' berhasil didaftarkan dan aktif di subpath /kasir/!"
}
```

### C. Contoh Integrasi Singkat di Bot Anda (Python):
```python
import subprocess
import json

def register_new_app(name, image, port, path, icon="🚀"):
    cmd = [
        "/home/opeteer/infra-ServerProject/register-app.sh",
        "--name", name,
        "--image", image,
        "--port", str(port),
        "--path", path,
        "--icon", icon,
        "--json-output"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(res.stdout)
    
    if data.get("status") == "success":
        return f"✅ Berhasil! Web Anda sudah aktif di: https://rocky.ts.net{data['path']}"
    else:
        return f"❌ Gagal: {data.get('error')}"
```
Dengan skrip ini, bot Anda cukup memanggil 1 baris perintah subprocess dan seluruh proses konfigurasi server langsung selesai secara instan!

