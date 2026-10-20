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
  # Coba eksekusi langsung sebagai current user
  if tailscale "$@" 2>/dev/null; then
    return 0
  fi

  # Jika gagal karena izin / access denied, coba dengan sudo
  if command -v sudo >/dev/null 2>&1; then
    sudo tailscale "$@"
  else
    echo "❌ Gagal menjalankan tailscale. Pastikan user memiliki hak operator:"
    echo "   Jalankan sekali di terminal: sudo tailscale set --operator=\$USER"
    return 1
  fi
}

start_funnel() {
  echo "🚀 [1/3] Memastikan Docker Compose berjalan..."
  if command -v docker >/dev/null 2>&1; then
    docker compose up -d
  else
    echo "⚠️ Docker tidak ditemukan di PATH, melewati docker compose up."
  fi

  echo "🌐 [2/3] Menjalankan Tailscale Funnel di port ${PROXY_PORT} (background mode)..."
  if ! run_tailscale funnel --bg --yes "${PROXY_PORT}"; then
    echo "❌ Gagal mengaktifkan Tailscale Funnel."
    echo "💡 Solusi: Jalankan perintah berikut sekali saja di terminal host:"
    echo "   sudo tailscale set --operator=\$USER"
    exit 1
  fi

  echo "✅ [3/3] Tailscale Funnel berhasil aktif secara otomatis!"
  echo ""
  echo "📋 Informasi Status & Public URL:"
  run_tailscale funnel status
}

stop_funnel() {
  echo "🛑 Menghentikan Tailscale Funnel..."
  run_tailscale funnel reset
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
