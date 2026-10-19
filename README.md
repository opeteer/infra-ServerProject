# Infra SIA Project

Infrastruktur runtime untuk **SIA Project**, dilengkapi dengan PostgreSQL, Watchtower (HTTP Webhook mode), Nginx Reverse Proxy, dan Cloudflare Quick Tunnel.

## Layanan yang Berjalan

1. **`postgres`** (Port 5432 internal): Database relasional PostgreSQL 16.
2. **`web`** (Port 8020 internal): Container aplikasi `gerardomayella/sia-web:latest`.
3. **`watchtower`** (Port 8080 internal): Mode HTTP Webhook, pasif hingga menerima request `POST /v1/update`.
4. **`proxy`** (Port 80 internal): Nginx yang merutekan traffic publik ke `web` dan endpoint `/v1/update` ke `watchtower`.
5. **`cloudflared`**: Cloudflare Quick Tunnel yang mengekspos `proxy` ke internet dengan HTTPS gratis.

---

## Panduan Penggunaan

### 1. Menjalankan Semua Layanan
```bash
docker compose up -d
```

### 2. Melihat Link Publik Cloudflare Tunnel
```bash
docker logs sia-tunnel
```
Salin URL `https://*.trycloudflare.com` yang muncul di log.

### 3. Mendaftarkan Webhook URL ke GitHub Secrets
Jalankan perintah ini di terminal (ganti URL dengan link yang didapat dari langkah 2):
```bash
gh secret set WATCHTOWER_WEBHOOK_URL --body "https://URL-DARI-LOGS.trycloudflare.com" --repo opeteer/siaProject
```

### 4. Menghentikan Layanan
```bash
docker compose down
```

### 5. Memeriksa Log Watchtower (Riwayat Auto-Deploy)
```bash
docker logs -f sia-watchtower
```
