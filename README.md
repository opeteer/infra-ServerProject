# Rocky Server Infrastructure & Gateway Platform

Infrastruktur terpadu untuk server **`rocky`**, berfungsi sebagai **Central Reverse Proxy Gateway (`server-proxy`)**, **Pusat CD Webhook Tunggal (`server-watchtower`)**, dan penyaji **Web Grafis Launchpad** untuk seluruh proyek web internal.

---

## 🏗️ Layanan yang Berjalan

1. **`server-proxy`** (Port 8080 host $\rightarrow$ 80 container): Nginx Gateway yang menyajikan Web Grafis di `/`, mem-proxy aplikasi web (seperti SIA USD di `/sia/`), dan mengarahkan webhook ke Watchtower di `/v1/update`.
2. **`server-watchtower`** (Port 8080 internal): Mesin otomatisasi CD tunggal berbasis HTTP Webhook yang memantau dan memperbarui semua kontainer web berlabel `com.centurylinklabs.watchtower.enable=true`.
3. **`sia-web`** (Port 8020 internal): Kontainer aplikasi SIA USD (`ghcr.io/opeteer/sia-web:latest`).
4. **`sia-postgres`** (Port 5432 internal): Database relasional PostgreSQL 16.
5. **`sia-tunnel`**: Cloudflare Quick Tunnel (opsional/alternatif).
6. **Tailscale Funnel**: Mengekspos `server-proxy` (port 8080) ke internet secara aman melalui HTTPS domain publik Tailscale (`https://rocky.<tailnet>.ts.net`).

---

## 🚀 Panduan Operasional

### 1. Menjalankan Gateway & Seluruh Layanan (Otomatis)
Gunakan skrip otomasi yang telah disiapkan:
```bash
./funnel.sh start
```
Skrip ini akan memastikan Docker Compose menyala, mengaktifkan Tailscale Funnel di background, dan mencetak status URL publik.

### 2. Memeriksa Status & URL Publik
```bash
./funnel.sh status
```

### 3. Menghentikan Layanan
```bash
# Menghentikan Tailscale Funnel
./funnel.sh stop

# Menghentikan kontainer Docker
docker compose down
```

### 4. Menjadikan Service Otomatis Saat Boot (Systemd)
Agar Gateway & Tailscale Funnel otomatis berjalan setiap kali server dinyalakan:
```bash
sudo cp tailscale-funnel-sia.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tailscale-funnel-sia.service
```

---

## 📋 Panduan Standarisasi: Menambahkan Repositori Web Baru

Semua repositori web baru yang akan di-hosting di server `rocky` cukup mengikuti 5 langkah standarisasi berikut:

```
[Repo Baru di GitHub] ---> [GitHub Actions Build & Push GHCR] ---> [POST https://rocky.ts.net/v1/update]
                                                                                |
                                                                                v
                                                                    [server-watchtower]
                                                                                |
                                                                                v
                                                                    [Update Kontainer Baru]
```

### Langkah 1: Siapkan `Dockerfile` Multi-Stage di Repo Proyek Anda
Pastikan proyek Anda memiliki `Dockerfile` yang mem-publish aplikasi ke sebuah port internal (contoh: port 3000, 8000, dll.).

### Langkah 2: Buat GitHub Actions Workflow (`.github/workflows/deploy.yml`)
Salin template workflow berikut ke repositori proyek baru Anda:

```yaml
name: Build, Publish and Deploy

on:
  push:
    branches: [ "main" ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}

      - name: Trigger Central Watchtower CD on Server Rocky
        run: |
          echo "🚀 Memicu Central Watchtower di server rocky..."
          curl -s -X POST \
            -H "Authorization: Bearer ${{ secrets.WATCHTOWER_TOKEN }}" \
            --max-time 15 \
            "${{ secrets.WATCHTOWER_WEBHOOK_URL }}" || true
```

> **Catatan Secret:** Daftarkan 2 secret di repository GitHub baru Anda (`Settings -> Secrets and variables -> Actions`):
> * `WATCHTOWER_TOKEN`: Isi dengan token yang ada di `.env` server (`WATCHTOWER_TOKEN`).
> * `WATCHTOWER_WEBHOOK_URL`: Isi dengan `https://rocky.<tailnet>.ts.net/v1/update`.

### Langkah 3: Daftarkan Kontainer Baru di `compose.yaml` Server
Buka `infra-ServerProject/compose.yaml` di server dan tambahkan blok service baru:

```yaml
  proyek-baru:
    image: ghcr.io/username/proyek-baru:latest
    container_name: proyek-baru-web
    restart: unless-stopped
    environment:
      - PORT=3000
    labels:
      - "com.centurylinklabs.watchtower.enable=true"  # Wajib agar di-update oleh Central Watchtower
```

### Langkah 4: Daftarkan Routing di `nginx.conf`
Buka `infra-ServerProject/nginx.conf` dan tambahkan blok routing sebelum block `location /`:

```nginx
        # Proyek Baru: Nama Layanan
        location /proyek-baru/ {
            proxy_pass http://proyek-baru:3000/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Prefix /proyek-baru;
        }
```

### Langkah 5: Daftarkan Kartu Layanan di Web Grafis Launchpad
Buka `infra-ServerProject/gateway-ui/index.html` dan tambahkan kartu baru di dalam `<div class="grid ...">`:

```html
<div class="glass rounded-xl p-6 hover:border-emerald-500/50 transition-all duration-300 flex flex-col justify-between group shadow-lg">
  <div>
    <div class="flex items-start justify-between mb-4">
      <div class="w-12 h-12 rounded-lg bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-bold text-xl">
        🚀
      </div>
      <span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5">
        <span class="w-2 h-2 rounded-full bg-emerald-400"></span> Live
      </span>
    </div>
    <h3 class="text-xl font-bold text-white group-hover:text-emerald-400 transition-colors">
      Nama Proyek Baru
    </h3>
    <p class="text-slate-400 text-sm mt-2 leading-relaxed">
      Deskripsi singkat mengenai aplikasi atau layanan baru ini.
    </p>
  </div>
  <div class="mt-6 pt-4 border-t border-slate-800/80 flex items-center justify-between">
    <span class="font-mono text-xs text-slate-500">Path: /proyek-baru/</span>
    <a href="/proyek-baru/" class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-sm transition-all shadow-md">
      Buka Web &rarr;
    </a>
  </div>
</div>
```

Setelah itu, jalankan:
```bash
docker compose up -d
```
Aplikasi baru langsung otomatis terintegrasi ke gateway dan otomatis di-deploy setiap kali push ke GitHub!
