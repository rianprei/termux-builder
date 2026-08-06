#!/data/data/com.termux/files/usr/bin/bash
set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
fail()  { echo -e "${RED}[x]${NC} $1" >&2; exit 1; }
step()  { echo -e "${BLUE}[>]${NC} $1"; }

echo
echo -e "${BOLD}termux-builder installer v1.0.0${NC}"
echo

[ -n "$PREFIX" ] || fail "Not running in Termux"

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm*|x86_64|i686) ;;
  *) fail "Unsupported architecture: $ARCH" ;;
esac

step "Updating package index..."
pkg update -y -qq 2>/dev/null

step "Installing build tools..."
pkg install -y openjdk-17 aapt2 apksigner dx python git -qq 2>/dev/null || true

step "Installing Python dependencies..."
pip install --quiet pyyaml requests 2>/dev/null || pip install pyyaml requests

step "Installing Kotlin..."
pkg install -y kotlin -qq 2>/dev/null || warn "Kotlin not available — Java-only builds will work"

INSTALL_DIR="$HOME/.termux-builder"
REPO_URL="https://github.com/rianprei/termux-builder"

step "Downloading termux-builder..."
if command -v git >/dev/null 2>&1; then
  if [ -d "$INSTALL_DIR/src" ]; then
    cd "$INSTALL_DIR/src" && git pull -q 2>/dev/null || true
  else
    mkdir -p "$INSTALL_DIR"
    git clone -q --depth 1 "$REPO_URL.git" "$INSTALL_DIR/src" 2>/dev/null || {
      warn "git clone failed — downloading via wget"
      mkdir -p "$INSTALL_DIR/src"
      wget -qO- "${REPO_URL}/archive/main.tar.gz" | tar xz -C "$INSTALL_DIR/src" --strip-components=1
    }
  fi
else
  mkdir -p "$INSTALL_DIR/src"
  wget -qO- "${REPO_URL}/archive/main.tar.gz" | tar xz -C "$INSTALL_DIR/src" --strip-components=1
fi

step "Installing termux-builder CLI..."
cd "$INSTALL_DIR/src"
pip install --quiet -e . 2>/dev/null || pip install -e .

step "Setting up Android SDK (android.jar)..."
SDK_DIR="$INSTALL_DIR/sdk"
API=34
PLATFORM_DIR="$SDK_DIR/platforms/android-${API}"
JAR_PATH="$PLATFORM_DIR/android.jar"

if [ ! -f "$JAR_PATH" ]; then
  mkdir -p "$PLATFORM_DIR"
  JAR_URL="https://github.com/nicbarker/android-jar/raw/main/android-${API}/android.jar"
  step "Downloading android.jar (API $API)..."
  wget -qO "$JAR_PATH" "$JAR_URL" 2>/dev/null || {
    warn "android.jar download failed — run: termux-builder setup --api $API"
  }
fi

ENV_LINE="export ANDROID_SDK=\"$SDK_DIR\""
for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
  [ -f "$RC" ] || continue
  grep -q "ANDROID_SDK" "$RC" 2>/dev/null && continue
  echo "$ENV_LINE" >> "$RC"
done
export ANDROID_SDK="$SDK_DIR"

step "Verifying installation..."
echo
if command -v termux-builder >/dev/null 2>&1; then
  info "termux-builder $(termux-builder --version 2>/dev/null || echo 'installed')"
else
  info "termux-builder available via: python -m builder"
fi

if command -v javac >/dev/null 2>&1; then
  info "javac: $(javac -version 2>&1 | head -1)"
fi

if command -v aapt2 >/dev/null 2>&1; then
  info "aapt2: OK"
fi

if [ -f "$JAR_PATH" ]; then
  SIZE=$(du -h "$JAR_PATH" | cut -f1)
  info "android.jar: $SIZE (API $API)"
fi

echo
echo -e "${GREEN}${BOLD}Installation complete!${NC}"
echo
echo "Quick start:"
echo "  termux-builder init myapp --package com.example.myapp"
echo "  cd myapp"
echo "  termux-builder build ."
echo
echo "Diagnose:"
echo "  termux-builder doctor"
echo
