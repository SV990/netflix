#!/usr/bin/env python3
"""
奈飞工厂 APP 自动任务脚本（Appium + UiAutomator2）
覆盖：每日签到 / 评论领金币 / 发弹幕领金币
特性：失败自动重试、飞书卡片通知（含状态/时间/运行链接/可选截图）
账号密码、飞书 Webhook、APK 下载链接均通过环境变量注入，请勿硬编码。
"""
import os
import sys
import time
import json
import urllib.request
import traceback
import requests
from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

APK_URL = os.environ.get("APK_DOWNLOAD_URL", "").strip()
APK_PATH = os.environ.get("APK_PATH", "/tmp/app.apk")
APP_USERNAME = os.environ.get("APP_USERNAME", "").strip()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
APPIUM_HOST = os.environ.get("APPIUM_HOST", "http://127.0.0.1:4723")
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/tmp/screenshots")
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
# 内嵌截图需要飞书自建应用的凭证（自定义机器人 webhook 本身无法上传图片）
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()
COMMENT_TEXT = os.environ.get("COMMENT_TEXT", "内容很赞，支持一下！")
DANMAKU_TEXT = os.environ.get("DANMAKU_TEXT", "前排支持")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))
SCREENSHOT_BASE_URL = os.environ.get("SCREENSHOT_BASE_URL", "").strip()
# 七牛云对象存储（用于托管截图，飞书卡片中以可点击链接展示）
QINIU_AK = os.environ.get("QINIU_AK", "").strip()
QINIU_SK = os.environ.get("QINIU_SK", "").strip()
QINIU_BUCKET = os.environ.get("QINIU_BUCKET", "").strip()
QINIU_DOMAIN = os.environ.get("QINIU_DOMAIN", "tja9zism0.hn-bkt.clouddn.com").strip()

PKG = "com.nfgcz.app"
ACTIVITY = "com.yy.myuko.app.MainActivityTinker"

# 任务完成结果汇总
results = {
    "每日签到": False,
    "评论领金币": False,
    "发弹幕领金币": False,
}

# 用于卡片消息的截图文件名（按执行顺序）
SHOT_NAMES = [
    "01_after_launch", "02_after_login", "03_task_page",
    "04_after_checkin", "05_comment_page", "06_comment_done",
    "07_danmaku_page", "08_danmaku_done",
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _is_challenge_file(path):
    """判断下载到的是否为反爬挑战页（HTML）而非 APK。"""
    try:
        with open(path, "rb") as f:
            head = f.read(2000)
    except Exception:
        return False
    if head[:4] == b"PK\x03\x04":  # APK 本质是 ZIP
        return False
    return b"<html" in head.lower() or b"arg1" in head


def _download_via_playwright(url, path):
    """用 Playwright 无头浏览器绕过反爬挑战页并下载文件。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="load", timeout=60000)
            with page.expect_download(timeout=60000) as dl:
                try:
                    page.click("text=下载", timeout=5000)
                except Exception:
                    pass
            dl.value.save_as(path)
        finally:
            browser.close()


def download_apk():
    if os.path.exists(APK_PATH):
        log(f"APK 已存在: {APK_PATH}")
        return
    if not APK_URL:
        log("未设置 APK_DOWNLOAD_URL，跳过下载，依赖预装 APK")
        return

    # 1) 直链尝试（GitHub Release / 对象存储直链）
    try:
        log(f"尝试直链下载: {APK_URL}")
        urllib.request.urlretrieve(APK_URL, APK_PATH)
        if _is_challenge_file(APK_PATH):
            log("下载内容疑似反爬页面，改用无头浏览器绕过")
            os.remove(APK_PATH)
            raise RuntimeError("challenge page")
        log("直链下载成功")
        return
    except Exception as e:
        log(f"直链下载失败: {e}")

    # 2) 反爬挑战页（蓝奏云 / dmpdmp 等）：用 Playwright 无头浏览器绕过
    try:
        log("尝试用无头浏览器绕过反爬...")
        _download_via_playwright(APK_URL, APK_PATH)
        if _is_challenge_file(APK_PATH):
            os.remove(APK_PATH)
            raise RuntimeError("still challenge page")
        log("无头浏览器下载成功")
        return
    except Exception as e:
        log(f"无头浏览器绕过失败: {e}")

    log("无法下载 APK：请改用可直接下载的 APK 直链（推荐 GitHub Release 附件）")


def install_apk():
    if not os.path.exists(APK_PATH):
        log("APK 文件不存在，跳过安装")
        return
    log("正在安装 APK...")
    rc = os.system(f"adb install -r -t '{APK_PATH}'")
    if rc != 0:
        log("安装命令返回非零，继续执行")


def find_and_click(driver, texts, timeout=5):
    """按文本列表逐个尝试点击，命中一个即返回 True。"""
    for t in texts:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[@text='{t}']"))
            )
            el.click()
            return True
        except Exception:
            continue
    return False


def save_screenshot(driver, name):
    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
        driver.save_screenshot(path)
        log(f"截图已保存: {path}")
    except Exception as e:
        log(f"截图保存失败: {e}")


def click_contains(driver, keywords, timeout=3):
    """点击文本包含任一关键字的可见元素（用于按钮文案不固定时）。返回命中的关键字或 None。"""
    for kw in keywords:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(@text,'{kw}')]"))
            )
            el.click()
            return kw
        except Exception:
            continue
    return None


def swipe_right(driver, duration=700):
    """在屏幕中央从右向左滑动（用于翻引导页，进入下一页）。"""
    size = driver.get_window_size()
    x, y = size["width"], size["height"]
    start_x, start_y = int(x * 0.85), int(y * 0.5)
    end_x = int(x * 0.15)
    driver.swipe(start_x, start_y, end_x, start_y, duration)


def handle_launch_interferences(driver, max_swipes=6):
    """处理首次启动的引导页、开屏广告、隐私协议与权限弹窗。
    采用「固定次数滑动 + 每轮尝试点结束按钮」策略，避免被 onboarding 文案判定卡死。
    """
    log("检查并处理启动引导页/广告/弹窗")
    finish_texts = ["跳过", "跳过广告", "立即体验", "进入", "开始体验", "开始", "马上体验",
                    "开启", "立即开启", "知道了", "同意并继续", "同意", "确定", "下一步",
                    "完成", "进入奈飞", "立即进入"]
    finish_kw = ["跳过", "体验", "进入", "开启", "同意", "完成", "开始", "下一步"]
    perm_texts = ["允许", "仅使用期间允许", "ALLOW", "ALWAYS", "始终允许"]
    perm_kw = ["允许", "同意"]
    tab_xpath = "//*[@text='首页' or @text='推荐' or @text='我的' or @text='任务' or @text='福利' or @text='分类' or @text='视频']"

    for i in range(max_swipes + 2):
        time.sleep(1.5)

        # 1) 尝试点结束/同意按钮（精确）
        if find_and_click(driver, finish_texts, timeout=2):
            log("点击了启动页结束/同意按钮（精确）")
            time.sleep(2.5)
        else:
            # 模糊匹配（按钮文案不固定时）
            hit = click_contains(driver, finish_kw, timeout=2)
            if hit:
                log(f"点击了启动页结束按钮（模糊匹配: {hit}）")
                time.sleep(2.5)

        # 2) 权限弹窗
        if find_and_click(driver, perm_texts, timeout=2):
            log("处理了系统权限弹窗（精确）")
            time.sleep(1.5)
        else:
            click_contains(driver, perm_kw, timeout=2)
            time.sleep(1.5)

        # 3) 是否已到达主界面
        if driver.find_elements(By.XPATH, tab_xpath):
            log("已到达 APP 主界面")
            return

        # 4) 固定滑动翻页（加强手势 + 长等待，不依赖 onboarding 文案判定）
        log(f"第 {i+1} 次尝试滑动翻页")
        swipe_right(driver, duration=700)
        time.sleep(2.5)

    # 兜底：最后再精确点一次结束按钮
    find_and_click(driver, finish_texts, timeout=3)
    log("启动引导处理结束（已达最大滑动次数）")


def is_login_page(driver):
    """判断是否已在账号密码登录页（图2）。"""
    edits = driver.find_elements(By.XPATH, "//android.widget.EditText")
    if len(edits) >= 2:
        return True
    markers = [
        "//*[@text='登录注册']",
        "//*[contains(@text,'邮箱/手机号')]",
        "//*[contains(@text,'请输入密码')]",
        "//android.widget.EditText[contains(@hint,'邮箱') or contains(@hint,'手机号')]",
    ]
    for xp in markers:
        if driver.find_elements(By.XPATH, xp):
            return True
    return False


def try_login(driver, wait):
    """从「我的」页进入登录页并填写账号密码登录。"""
    if is_login_page(driver):
        log("当前已在登录页")
    else:
        log("先进入「我的」页")
        if find_and_click(driver, ["我的"], timeout=5):
            log("已点击「我的」tab")
            time.sleep(2)
        else:
            log("未找到「我的」tab，尝试直接找登录入口")

        log("尝试点击「未登录」进入登录页")
        if not find_and_click(driver, ["未登录"], timeout=5):
            # fallback：点击包含「未登录」文字的最近可点击父元素
            try:
                el = driver.find_element(
                    By.XPATH,
                    "//*[contains(@text,'未登录')]/ancestor::*[@clickable='true'][1]",
                )
                el.click()
                log("已点击未登录区域")
            except Exception:
                pass
        time.sleep(3)

    if not is_login_page(driver):
        log("未能进入登录页")
        return False

    edits = driver.find_elements(By.XPATH, "//android.widget.EditText")
    log(f"检测到登录页，共 {len(edits)} 个输入框")

    # 优先按 hint/text 定位；找不到则取前两个 EditText
    username_input = get_input(driver, [
        "//android.widget.EditText[contains(@hint,'邮箱') or contains(@hint,'手机号')]",
        "//android.widget.EditText[contains(@text,'邮箱') or contains(@text,'手机号')]",
    ]) or (edits[0] if edits else None)
    pwd_input = get_input(driver, [
        "//android.widget.EditText[contains(@hint,'密码')]",
        "//android.widget.EditText[contains(@text,'密码')]",
    ]) or (edits[1] if len(edits) >= 2 else None)

    if not username_input or not pwd_input:
        log("登录页输入框定位失败")
        return False

    username_input.click()
    username_input.clear()
    username_input.send_keys(APP_USERNAME)
    log("已填写账号")
    time.sleep(1)

    pwd_input.click()
    pwd_input.clear()
    pwd_input.send_keys(APP_PASSWORD)
    log("已填写密码")
    time.sleep(1)

    if find_and_click(driver, ["登录"], timeout=5):
        log("已点击登录")
        time.sleep(5)
        return True

    log("未找到登录按钮")
    return False


def navigate_to_task(driver, wait):
    """点击底部 tab 进入任务中心。"""
    log("正在进入任务页")
    for txt in ["任务", "任务中心"]:
        if find_and_click(driver, [txt], timeout=5):
            log(f"已点击 tab '{txt}'")
            time.sleep(3)
            return True
    log("未找到任务 tab")
    return False


def do_checkin(driver, wait):
    """执行每日签到。"""
    log("正在进入任务页")
    navigate_to_task(driver, wait)
    log("正在查找签到按钮")
    xpaths = [
        "//*[contains(@text, '签到') and not(contains(@text, '已')) and not(contains(@text, '完成'))]",
        "//*[contains(@content-desc, '签到') and not(contains(@content-desc, '已'))]",
        "//*[@text='签到']",
        "//*[@text='立即签到']",
        "//*[@text='点击签到']",
    ]
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            text = el.get_attribute("text") or el.get_attribute("content-desc") or ""
            log(f"找到签到元素: {text}")
            el.click()
            time.sleep(3)
            log("已点击签到")
            return True
        except Exception:
            continue

    log("尝试点击顶部今天区域")
    for txt in ["今天", "第1天"]:
        try:
            el = driver.find_element(By.XPATH, f"//*[@text='{txt}']/..")
            el.click()
            time.sleep(2)
            log("已点击今天区域")
            return True
        except Exception:
            continue

    log("未找到可点击的签到按钮，可能今日已签到")
    return False


def get_input(driver, hints):
    """按 hint / text 关键字查找输入框，返回首个命中元素。"""
    for xp in hints:
        try:
            el = driver.find_element(By.XPATH, xp)
            return el
        except Exception:
            continue
    return None


def do_comment(driver, wait):
    """执行评论领金币：进入评论场景 → 输入评论 → 发送。"""
    log("开始执行：评论领金币")
    navigate_to_task(driver, wait)
    if not find_and_click(driver, ["评论领金币"]):
        try:
            driver.find_element(By.XPATH, "//*[contains(@text,'评论')]").click()
        except Exception:
            pass
    time.sleep(4)
    save_screenshot(driver, "05_comment_page")

    edit = get_input(driver, [
        "//android.widget.EditText[contains(@hint,'评论')]",
        "//android.widget.EditText[contains(@hint,'说点')]",
        "//android.widget.EditText[contains(@hint,'写')]",
        "//android.widget.EditText",
    ])
    if not edit:
        log("未找到评论输入框")
        return False
    edit.click()
    edit.clear()
    edit.send_keys(COMMENT_TEXT)
    time.sleep(1)
    clicked = find_and_click(driver, ["发送", "发布", "提交", "评论", "发送评论"], timeout=6)
    time.sleep(2)
    save_screenshot(driver, "06_comment_done")
    if clicked:
        log("评论已发送")
        return True
    log("未找到发送按钮")
    return False


def do_danmaku(driver, wait):
    """执行发弹幕领金币：进入播放/弹幕场景 → 输入弹幕 → 发送。"""
    log("开始执行：发弹幕领金币")
    navigate_to_task(driver, wait)
    if not find_and_click(driver, ["发弹幕领金币", "弹幕领金币"]):
        try:
            driver.find_element(By.XPATH, "//*[contains(@text,'弹幕')]").click()
        except Exception:
            pass
    time.sleep(4)
    save_screenshot(driver, "07_danmaku_page")

    find_and_click(driver, ["弹幕"], timeout=3)
    time.sleep(1)

    edit = get_input(driver, [
        "//android.widget.EditText[contains(@hint,'弹幕')]",
        "//android.widget.EditText[contains(@text,'弹幕')]",
        "//android.widget.EditText",
    ])
    if not edit:
        log("未找到弹幕输入框")
        return False
    edit.click()
    edit.clear()
    edit.send_keys(DANMAKU_TEXT)
    time.sleep(1)
    clicked = find_and_click(driver, ["发送", "发布", "提交"], timeout=6)
    time.sleep(2)
    save_screenshot(driver, "08_danmaku_done")
    if clicked:
        log("弹幕已发送")
        return True
    log("未找到发送按钮")
    return False


def run_with_retry(fn, name, *args, **kwargs):
    """带重试地执行任务函数。"""
    for i in range(1, MAX_RETRIES + 1):
        try:
            ok = fn(*args, **kwargs)
        except Exception as e:
            ok = False
            log(f"{name} 第{i}次执行异常: {e}")
        if ok:
            log(f"{name} 成功（第{i}次）")
            return True
        if i < MAX_RETRIES:
            log(f"{name} 第{i}次未成功，5 秒后重试...")
            time.sleep(5)
    log(f"{name} 重试 {MAX_RETRIES} 次后仍失败")
    return False


def get_tenant_access_token():
    """用自建应用的 app_id/app_secret 换取 tenant_access_token。"""
    if not (FEISHU_APP_ID and FEISHU_APP_SECRET):
        return None
    try:
        r = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10,
        )
        data = r.json()
        if data.get("code") != 0:
            log(f"获取 tenant_access_token 失败: {data}")
            return None
        return data.get("tenant_access_token")
    except Exception as e:
        log(f"获取 tenant_access_token 异常: {e}")
        return None


def upload_image_to_feishu(path):
    """上传本地图片到飞书，返回 image_key（失败返回 None）。"""
    token = get_tenant_access_token()
    if not token:
        return None
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    try:
        with open(path, "rb") as f:
            r = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": (os.path.basename(path), f, "image/png")},
                timeout=30,
            )
        data = r.json()
        if data.get("code") != 0:
            log(f"上传图片失败 {os.path.basename(path)}: {data}")
            return None
        return data.get("data", {}).get("image_key")
    except Exception as e:
        log(f"上传图片异常 {os.path.basename(path)}: {e}")
        return None


def upload_to_qiniu(local_path, key):
    """上传截图到七牛云，返回公开访问 URL；未配置或失败返回 None。"""
    if not (QINIU_AK and QINIU_SK and QINIU_BUCKET and QINIU_DOMAIN):
        return None
    try:
        from qiniu import Auth, put_file
    except ImportError:
        log("未安装 qiniu 依赖，跳过七牛云上传（pip install qiniu）")
        return None
    try:
        q = Auth(QINIU_AK, QINIU_SK)
        token = q.upload_token(QINIU_BUCKET, key, 3600)
        ret, info = put_file(token, key, local_path)
        if info.status_code == 200:
            return f"https://{QINIU_DOMAIN}/{key}"
        log(f"七牛云上传失败 {key}: {info}")
        return None
    except Exception as e:
        log(f"七牛云上传异常 {key}: {e}")
        return None


def notify_feishu():
    if not FEISHU_WEBHOOK:
        log("未配置 FEISHU_WEBHOOK，跳过飞书通知")
        return

    fields = []
    for k, v in results.items():
        fields.append({
            "is_short": True,
            "text": {"tag": "lark_md", "content": f"**{k}**\n{'✅ 已完成' if v else '⚠️ 未成功'}"},
        })

    elements = [{"tag": "div", "fields": fields}, {"tag": "hr"}]

    # 截图展示优先级：飞书自建应用内嵌图（image_key）> 七牛云公开链接 > SCREENSHOT_BASE_URL 链接
    qiniu_urls = {}
    if QINIU_AK and QINIU_SK and QINIU_BUCKET and QINIU_DOMAIN:
        log("正在上传截图到七牛云...")
        for n in SHOT_NAMES:
            p = os.path.join(SCREENSHOT_DIR, f"{n}.png")
            if not os.path.exists(p) or os.path.getsize(p) == 0:
                continue
            url = upload_to_qiniu(p, f"{n}.png")
            if url:
                qiniu_urls[n] = url
        if qiniu_urls:
            log(f"已上传 {len(qiniu_urls)} 张截图到七牛云")

    if FEISHU_APP_ID and FEISHU_APP_SECRET:
        for n in SHOT_NAMES:
            p = os.path.join(SCREENSHOT_DIR, f"{n}.png")
            if not os.path.exists(p):
                continue
            if os.path.getsize(p) > 9 * 1024 * 1024:
                log(f"截图 {n} 超过 9MB，跳过内嵌")
                continue
            key = upload_image_to_feishu(p)
            if key:
                elements.append({
                    "tag": "img",
                    "img_key": key,
                    "alt": {"tag": "plain_text", "content": n},
                })
    elif qiniu_urls:
        links = "\n".join(f"- [{n}]({u})" for n, u in qiniu_urls.items())
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**截图（七牛云）：**\n{links}"},
        })
    elif SCREENSHOT_BASE_URL:
        base = SCREENSHOT_BASE_URL.rstrip("/")
        links = "\n".join(
            f"- [{n}]({base}/{n}.png)"
            for n in SHOT_NAMES
            if os.path.exists(os.path.join(SCREENSHOT_DIR, f"{n}.png"))
        )
        if links:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**截图：**\n{links}"},
            })

    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        srv = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        rid = os.environ.get("GITHUB_RUN_ID", "")
        run_url = f"{srv}/{repo}/actions/runs/{rid}"

    note = f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
    if run_url:
        note += f" ｜ [查看运行]({run_url})"
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": note}]})

    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "奈飞工厂 每日任务"},
                "template": "blue",
            },
            "elements": elements,
        },
    }
    try:
        r = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        log(f"飞书卡片通知状态: {r.status_code} {r.text[:160]}")
    except Exception as e:
        log(f"飞书通知失败: {e}")


def main():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    if not APP_USERNAME or not APP_PASSWORD:
        log("错误：环境变量 APP_USERNAME 和 APP_PASSWORD 必须设置")
        sys.exit(1)

    download_apk()
    install_apk()

    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.device_name = "emulator-5554"
    options.app_package = PKG
    options.app_activity = ACTIVITY
    options.no_reset = True
    options.new_command_timeout = 300
    options.set_capability("settings[waitForIdleTimeout]", 100)
    options.set_capability("settings[waitForSelectorTimeout]", 10000)

    log(f"连接 Appium: {APPIUM_HOST}")
    driver = webdriver.Remote(APPIUM_HOST, options=options)
    wait = WebDriverWait(driver, 30)

    try:
        log("等待 APP 启动")
        time.sleep(8)
        save_screenshot(driver, "01_after_launch")

        # 处理首次启动引导页/开屏广告/隐私协议/权限弹窗
        handle_launch_interferences(driver)
        save_screenshot(driver, "01_after_onboarding")

        run_with_retry(try_login, "登录", driver, wait)
        save_screenshot(driver, "02_after_login")

        results["每日签到"] = run_with_retry(do_checkin, "每日签到", driver, wait)
        save_screenshot(driver, "04_after_checkin")

        results["评论领金币"] = run_with_retry(do_comment, "评论领金币", driver, wait)

        results["发弹幕领金币"] = run_with_retry(do_danmaku, "发弹幕领金币", driver, wait)

    except Exception as e:
        log(f"运行出错: {e}")
        traceback.print_exc()
        save_screenshot(driver, "99_error")
    finally:
        driver.quit()
        notify_feishu()


if __name__ == "__main__":
    main()
