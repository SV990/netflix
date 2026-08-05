#!/usr/bin/env bash
# 在 Android 模拟器就绪后执行：等待启动完成 -> 启动 Appium -> 运行签到脚本。
# 注意：android-emulator-runner 是逐行用 sh -c 执行 script，
# 因此这里把多行逻辑放进独立脚本，由 workflow 的 `bash run_checkin.sh` 单行调用。
set -uo pipefail

echo "== 等待模拟器启动完成 =="
adb wait-for-device
adb devices -l
for i in $(seq 1 30); do
  if [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
    echo "模拟器启动完成"
    break
  fi
  sleep 5
done
echo "boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"

echo "== 启动 Appium 并等待就绪 =="
appium --address 127.0.0.1 --port 4723 --log-level error > /tmp/appium.log 2>&1 &
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:4723/status >/dev/null 2>&1; then
    echo "Appium 已就绪"
    break
  fi
  sleep 2
done
curl -s http://127.0.0.1:4723/status | head -c 300 || true
echo

echo "== 运行签到脚本 =="
python checkin.py
