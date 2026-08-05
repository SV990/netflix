#!/usr/bin/env python3
"""奈飞工厂自动任务 —— 全局配置与常量。

所有敏感信息（账号密码、飞书 Webhook、七牛云密钥、APK 下载地址）均通过
环境变量注入，请勿把明文写进代码或提交到仓库。
"""
import os
import time

# ---- 账号 / 服务端 ----
APK_URL = os.environ.get("APK_DOWNLOAD_URL", "").strip()
APK_PATH = os.environ.get("APK_PATH", "/tmp/app.apk")
APP_USERNAME = os.environ.get("APP_USERNAME", "").strip()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
APPIUM_HOST = os.environ.get("APPIUM_HOST", "http://127.0.0.1:4723")
# 本地/远程 ADB 设备序列号。雷电/MuMu/真机/多开时改成 adb devices 里看到的序列号。
ANDROID_DEVICE = os.environ.get("ANDROID_DEVICE", "emulator-5554")
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots")

# ---- 飞书 ----
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
# 内嵌截图需要飞书自建应用凭证（自定义机器人 webhook 本身无法上传图片）
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()

# ---- 任务文案 ----
DEFAULT_TEXT = "生活慢慢，欢喜常在"
COMMENT_TEXT = os.environ.get("COMMENT_TEXT", DEFAULT_TEXT)
DANMAKU_TEXT = os.environ.get("DANMAKU_TEXT", DEFAULT_TEXT)

# ---- 重试 / 反馈 ----
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))
SCREENSHOT_BASE_URL = os.environ.get("SCREENSHOT_BASE_URL", "").strip()

# ---- 七牛云对象存储（用于托管截图，飞书卡片中以可点击链接展示）----
QINIU_AK = os.environ.get("QINIU_AK", "").strip()
QINIU_SK = os.environ.get("QINIU_SK", "").strip()
QINIU_BUCKET = os.environ.get("QINIU_BUCKET", "").strip()
QINIU_DOMAIN = os.environ.get("QINIU_DOMAIN", "tja9zism0.hn-bkt.clouddn.com").strip()

# ---- APP 标识 ----
PKG = "com.nfgcz.app"
ACTIVITY = "com.yy.myuko.app.MainActivityTinker"

# 任务完成结果汇总（由 main 填充，notify 读取）
TASK_RESULTS = {
    "每日签到": False,
    "评论领金币": False,
    "发弹幕领金币": False,
}

# 用于飞书卡片的截图文件名（按执行顺序）
SHOT_NAMES = [
    "01_after_launch", "02_after_login", "03_home_page",
    "04_after_checkin", "05_comment_page", "06_comment_done",
    "07_danmaku_page", "08_danmaku_done",
]


def log(msg):
    """统一日志输出，带时间戳。"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
