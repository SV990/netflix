#!/usr/bin/env python3
"""奈飞工厂 APP 自动任务 —— 入口编排。

流程：下载/安装 APK → 连接 Appium → 处理启动干扰 → 登录 →
     处理登录后弹窗 → 每日签到 → 评论领金币 → 发弹幕领金币 → 飞书通知。

账号密码、飞书 Webhook、APK 下载链接、七牛云密钥均通过环境变量注入。
"""
import os
import sys
import time
import traceback

from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.webdriver.support.ui import WebDriverWait

from config import (
    log, APP_USERNAME, APP_PASSWORD, APPIUM_HOST, ANDROID_DEVICE,
    PKG, ACTIVITY, SCREENSHOT_DIR, TASK_RESULTS,
)
from apk import download_apk, install_apk
from launch import handle_launch_interferences, try_login, dismiss_common_popups, handle_onboarding_pages
from tasks import run_with_retry, do_checkin, do_comment, do_danmaku
from ui import save_screenshot
from notify import notify_feishu


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
    options.device_name = ANDROID_DEVICE
    options.udid = ANDROID_DEVICE
    options.app_package = PKG
    options.app_activity = ACTIVITY
    options.no_reset = True
    options.new_command_timeout = 300
    options.set_capability("settings[waitForIdleTimeout]", 100)
    options.set_capability("settings[waitForSelectorTimeout]", 10000)

    log(f"连接 Appium: {APPIUM_HOST}  设备: {ANDROID_DEVICE}")
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

        # 登录后常见弹窗（系统公告、升级提示）
        for _ in range(3):
            if not dismiss_common_popups(driver):
                break
        save_screenshot(driver, "03_home_page")

        TASK_RESULTS["每日签到"] = run_with_retry(do_checkin, "每日签到", driver, wait)
        save_screenshot(driver, "04_after_checkin")

        # 登录/签到后可能出现 onboarding 引导页（如「个性推荐」），先处理掉再进入任务
        handle_onboarding_pages(driver)
        save_screenshot(driver, "04_after_onboarding")

        # 注意：do_comment / do_danmaku 内部已各自循环/重试，这里务必直接调用，
        # 不要再包一层 run_with_retry，否则整段任务会重跑、把单次运行时间拖到十几分钟。
        TASK_RESULTS["评论领金币"] = do_comment(driver, wait)

        TASK_RESULTS["发弹幕领金币"] = do_danmaku(driver, wait)

    except Exception as e:
        log(f"运行出错: {e}")
        traceback.print_exc()
        save_screenshot(driver, "99_error")
    finally:
        driver.quit()
        notify_feishu()


if __name__ == "__main__":
    main()
