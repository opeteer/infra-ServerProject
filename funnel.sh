#!/usr/bin/env bash
# ==============================================================================
# Script Otomasi Tailscale Funnel & Docker Compose untuk SIA Project
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Baca environment variable jika ada .env
if [ -f .env ]; then
  PROXY_PORT="${PROXY_PORT:-$(grep -E '^PROXY_PORT=' .env | cut -d '=' -f2 | tr -d ' "\r')}"
fi
PROXY_PORT="${PROXY_PORT:-8080}"

run_tailscale() {
  tailscale "$@"
}

cleanup_listeners() {
  # Hentikan proses foreground tailscale yang mungkin masih berjalan di background
  pkill -f "tailscale (funnel|serve)" 2>/dev/null || true
  # Reset konfigurasi serve/funnel yang menggantung
  tailscale funnel reset 2>/dev/null || true
  tailscale serve reset 2>/dev/null || true
}

start_funnel() {
  echo "🚀 [1/3] Memastikan Docker Compose berjalan..."
  if command -v docker >/dev/null 2>&1; then
    docker compose up -d
  else
    echo "⚠️ Docker tidak ditemukan di PATH, melewati docker compose up."
  fi

  echo "🌐 [2/3] Menjalankan Tailscale Funnel di port ${PROXY_PORT} (background mode)..."
  
  # Jalankan perintah dan tangkap outputnya
  SET_OUTPUT=$(tailscale funnel --bg --yes "${PROXY_PORT}" 2>&1 || true)

  # Jika terdeteksi konflik listener lama, bersihkan dan coba lagi
  if echo "$SET_OUTPUT" | grep -q "foreground listener already exists"; then
    echo "⚠️ Terdeteksi sesi listener foreground lama. Membersihkan sesi..."
    cleanup_listeners
    sleep 1
    SET_OUTPUT=$(tailscale funnel --bg --yes "${PROXY_PORT}" 2>&1 || true)
  fi

  if echo "$SET_OUTPUT" | grep -q "Access denied"; then
    echo "❌ Akses ditolak oleh Tailscale."
    echo "💡 Solusi: Jalankan sekali perintah berikut di terminal:"
    echo "   sudo tailscale set --operator=\$USER"
    exit 1
  fi

  if echo "$SET_OUTPUT" | grep -q "foreground listener already exists"; then
    echo "❌ Masih terdapat foreground listener yang mengunci port 443 di tailscaled."
    echo "💡 Solusi cepat: Restart daemon tailscaled untuk melepaskan listener lama:"
    echo "   sudo systemctl restart tailscaled"
    echo "   Setelah itu jalankan kembali: ./funnel.sh start"
    exit 1
  fi

  echo "✅ [3/3] Tailscale Funnel berhasil aktif secara otomatis!"
  echo ""
  echo "📋 Informasi Status & Public URL:"
  tailscale funnel status
}

stop_funnel() {
  echo "🛑 Menghentikan Tailscale Funnel..."
  cleanup_listeners
  echo "✅ Tailscale Funnel telah dihentikan/direset."
}

status_funnel() {
  echo "📋 Status Tailscale Funnel:"
  run_tailscale funnel status
}

case "$1" in
  start|"")
    start_funnel
    ;;
  stop)
    stop_funnel
    ;;
  status)
    status_funnel
    ;;
  restart)
    stop_funnel
    sleep 1
    start_funnel
    ;;
  *)
    echo "Penggunaan: $0 {start|stop|status|restart}"
    exit 1
    ;;
esac
