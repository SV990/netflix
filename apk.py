#!/usr/bin/env python3
"""APK 下载（直链 + 反爬绕过）与安装。"""
import os
import urllib.request

from config import log, APK_URL, APK_PATH


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
