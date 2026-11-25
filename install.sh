#!/usr/bin/env bash
# نصب / به‌روزرسانی سرویس تبدیل صدا به متن روی Ubuntu
# اجرا (از داخل پوشهٔ پروژه):
#   sudo APP_PASSWORD='رمز' bash install.sh            ← نصب اول
#   sudo bash install.sh                               ← به‌روزرسانی (رمز قبلی حفظ می‌شود)
#   sudo PORT=8096 bash install.sh                     ← تغییر پورت
set -euo pipefail

SERVICE=voice-to-text
APP_USER=v2t
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR=/var/lib/voice-to-text
ENV_FILE=/etc/voice-to-text.env
UNIT_FILE=/etc/systemd/system/${SERVICE}.service

say()  { echo -e "\n\033[1;34m==> $*\033[0m"; }
fail() { echo -e "\n\033[1;31m✗ $*\033[0m" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "این اسکریپت باید با sudo اجرا شود:  sudo bash install.sh"
[[ "$APP_DIR" != /home/* && "$APP_DIR" != /root/* ]] || fail "پروژه باید در /opt/voice-to-text باشد، نه در پوشهٔ خانه. راهنمای README را ببینید."

# ---------- پورت: از اجرای قبلی یا مقدار پیش‌فرض
OLD_PORT=""
[ -f "$ENV_FILE" ] && OLD_PORT="$(grep -E '^PORT=' "$ENV_FILE" | cut -d= -f2 | tr -d '"' || true)"
PORT="${PORT:-${OLD_PORT:-8095}}"
[[ "$PORT" =~ ^[0-9]+$ ]] || fail "پورت نامعتبر است: $PORT"

# ---------- رمز عبور
OLD_PASS=""
[ -f "$ENV_FILE" ] && OLD_PASS="$(grep -E '^APP_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | sed 's/^"//; s/"$//' || true)"
APP_PASSWORD="${APP_PASSWORD:-$OLD_PASS}"
[ -n "$APP_PASSWORD" ] || fail "رمز عبور تعیین نشده. این‌طور اجرا کنید:  sudo APP_PASSWORD='رمز' bash install.sh"
[[ "$APP_PASSWORD" != *'"'* && "$APP_PASSWORD" != *'\'* ]] || fail "رمز عبور نباید علامت \" یا \\ داشته باشد."

# ---------- بررسی آزاد بودن پورت (اگر سرویس خودمان نیست)
if ss -ltnH "sport = :$PORT" | grep -q . && ! systemctl is-active --quiet "$SERVICE"; then
  ss -ltnp "sport = :$PORT" || true
  fail "پورت $PORT را برنامهٔ دیگری استفاده می‌کند. با پورت دیگری اجرا کنید، مثلاً:  sudo PORT=8096 bash install.sh"
fi

say "نصب پیش‌نیازها (python3-venv و ffmpeg)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ffmpeg >/dev/null

say "ساخت کاربر سیستمی $APP_USER و پوشهٔ داده"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

say "نصب کتابخانه‌های پایتون"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

say "ساخت فایل تنظیمات $ENV_FILE"
SECRET_KEY=""
[ -f "$ENV_FILE" ] && SECRET_KEY="$(grep -E '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2 | tr -d '"' || true)"
[ -n "$SECRET_KEY" ] || SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
umask 077
cat > "$ENV_FILE" <<EOF
APP_PASSWORD="$APP_PASSWORD"
SECRET_KEY="$SECRET_KEY"
DATA_DIR="$DATA_DIR"
PORT="$PORT"
MAX_UPLOAD_MB="500"
EOF
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "ساخت سرویس systemd"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Voice to Text (OpenAI transcription web app)
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl restart "$SERVICE"

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  say "باز کردن پورت $PORT در فایروال"
  ufw allow "$PORT/tcp" >/dev/null
fi

sleep 2
if systemctl is-active --quiet "$SERVICE"; then
  IP="$(curl -s -4 --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
  echo -e "\n\033[1;32m✓ نصب کامل شد.\033[0m"
  echo "  آدرس:  http://$IP:$PORT"
  echo "  وضعیت: sudo systemctl status $SERVICE"
  echo "  لاگ:   sudo journalctl -u $SERVICE -n 50"
else
  journalctl -u "$SERVICE" -n 30 --no-pager || true
  fail "سرویس اجرا نشد. خروجی بالا را برای بررسی بفرستید."
fi
