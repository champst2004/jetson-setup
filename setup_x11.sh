#!/bin/bash

GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }

# ─── Menu ─────────────────────────────────────────────────
echo ""
echo "================================"
echo "   X11 Setup — GPU Selection"
echo "================================"
echo "  1) iGPU (Tegra integrated)"
echo "  2) dGPU (RTX 6000 Ada)"
echo "================================"
read -p "Select option [1 or 2]: " choice

case $choice in
    1) info "Selected: iGPU" ;;
    2) info "Selected: dGPU" ;;
    *) err "Invalid option. Please enter 1 or 2."; exit 1 ;;
esac

# ─── Step 1 ───────────────────────────────────────────────
echo ""
echo "==> Step 1: Stopping display manager and killing Xorg..."
sudo service gdm stop 2>&1
if [ $? -eq 0 ]; then ok "GDM stopped"; else err "GDM stop failed (may not be running — continuing)"; fi

sudo pkill -9 Xorg 2>&1
if [ $? -eq 0 ]; then ok "Xorg killed"; else ok "No Xorg process found (already clean)"; fi

# Wait for Xorg to fully exit then clean stale locks
sleep 2
if [ -f /tmp/.X0-lock ]; then
    sudo rm -f /tmp/.X0-lock
    sudo rm -f /tmp/.X11-unix/X0
    ok "Removed stale X lock files"
else
    ok "No stale lock files found"
fi

# ─── Step 2: Start X server ───────────────────────────────
echo ""
echo "==> Step 2: Starting X server..."

if [ "$choice" = "1" ]; then
    xinit -- :0 vt7 -sharevts -novtswitch &
else
    cd /etc/X11 && xinit -- :0 vt7 -sharevts -novtswitch -config xorg.conf.pci &
fi

XINIT_PID=$!
sleep 4

if ps -p $XINIT_PID > /dev/null 2>&1; then
    ok "X server started (PID $XINIT_PID)"
else
    err "X server failed to start — check ~/.local/share/xorg/Xorg.0.log"
    grep -iE "\(EE\)" ~/.local/share/xorg/Xorg.0.log 2>/dev/null | tail -5
    exit 1
fi

# ─── Step 3: DISPLAY + screensaver ────────────────────────
echo ""
echo "==> Step 3: Setting DISPLAY and disabling screensaver/DPMS..."
export DISPLAY=:0

xset s off 2>&1
if [ $? -eq 0 ]; then ok "Screensaver disabled"; else err "xset s off failed"; fi

xset s noblank 2>&1
if [ $? -eq 0 ]; then ok "Screen blanking disabled"; else err "xset s noblank failed"; fi

xset -dpms 2>&1
if [ $? -eq 0 ]; then ok "DPMS disabled"; else err "xset -dpms failed"; fi

xdpyinfo > /dev/null 2>&1
if [ $? -eq 0 ]; then ok "Display :0 is reachable"; else err "Display :0 not reachable"; fi

# ─── Step 4: GPU env vars ─────────────────────────────────
echo ""
echo "==> Step 4: Setting GPU environment variables..."

if [ "$choice" = "1" ]; then
    export __GL_DeviceModalityPreference=1
    export EGLVisibleDGPUDevices=2
    export CUDA_VISIBLE_DEVICES=1
    ok "__GL_DeviceModalityPreference=1 (iGPU)"
    ok "EGLVisibleDGPUDevices=2 (iGPU)"
    ok "CUDA_VISIBLE_DEVICES=1 (iGPU)"
else
    export __GL_DeviceModalityPreference=0
    export EGLVisibleDGPUDevices=1
    export CUDA_VISIBLE_DEVICES=0
    ok "__GL_DeviceModalityPreference=0 (dGPU)"
    ok "EGLVisibleDGPUDevices=1 (dGPU)"
    ok "CUDA_VISIBLE_DEVICES=0 (dGPU)"
fi

echo ""
ok "Setup complete — ready to run test suite."
