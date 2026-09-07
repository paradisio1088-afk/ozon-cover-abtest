#!/bin/bash
# Ставит фоновую задачу ротации (launchd). Запускает worker.py каждые 30 минут,
# пока Mac включён. Логи — data/worker.log и data/launchd.*.log
set -euo pipefail

LABEL="com.ozon.cover-abtest"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/data"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/worker.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/data/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Служба установлена: $LABEL"
echo "  проверка:  launchctl list | grep $LABEL"
echo "  запуск сейчас:  launchctl start $LABEL"
echo "  удалить:  launchctl unload \"$PLIST\" && rm \"$PLIST\""
