#!/usr/bin/env python3
"""视频详情页进入逻辑：首页随机点击一个视频进入播放页。"""
import time

from selenium.webdriver.common.by import By

from config import log
from ui import find_and_click, tap_relative
from launch import dismiss_common_popups


def is_video_detail_page(driver):
    """判断当前是否已进入视频详情/播放页。"""
    markers = ["详情", "讨论", "点我发弹幕", "选集", "立即观看"]
    for m in markers:
        if driver.find_elements(By.XPATH, f"//*[contains(@text,'{m}')]"):
            return True
    return False


def enter_first_video(driver):
    """从首页点击第一个视频进入播放详情页。若已在详情页则直接返回。"""
    if is_video_detail_page(driver):
        log("当前已在视频详情页，无需重新进入")
        return True

    log("回到首页准备进入视频")
    if not find_and_click(driver, ["首页"], timeout=5):
        log("未找到首页 tab，尝试按坐标点击底部首页位置")
        try:
            tap_relative(driver, 0.17, 0.93)
            time.sleep(2)
        except Exception as e:
            log(f"坐标点击首页失败: {e}")

    # 首页可能出现的系统公告/广告弹窗
    for _ in range(3):
        if not dismiss_common_popups(driver):
            break
    time.sleep(2)

    size = driver.get_window_size()
    w, h = size["width"], size["height"]
    # 常见视频卡片位置：顶部横幅、热门/猜你喜欢第一行/第二行
    candidates = [
        (0.50, 0.28),  # 首页顶部横幅
        (0.20, 0.55),  # 热门/猜你喜欢 第一行左
        (0.50, 0.55),  # 第一行中
        (0.80, 0.55),  # 第一行右
        (0.25, 0.74),  # 第二行左
        (0.50, 0.74),
    ]

    for rx, ry in candidates:
        if is_video_detail_page(driver):
            log("成功进入视频详情页")
            return True
        x, y = int(w * rx), int(h * ry)
        log(f"尝试点击首页视频区域 ({rx},{ry}) -> ({x},{y})")
        try:
            driver.tap([(x, y)])
            time.sleep(4)
        except Exception as e:
            log(f"点击失败: {e}")

    log("未能通过坐标点击进入视频详情页")
    return is_video_detail_page(driver)
