#!/usr/bin/env python3
"""视频详情页进入与播放控制：首页点击不同视频进入详情页、启动播放。"""
import time

from selenium.webdriver.common.by import By

from config import log
from ui import find_and_click, click_contains, tap_relative
from launch import dismiss_common_popups

# 首页视频卡片候选点击位置（相对坐标）。
# 索引不同 => 点首页不同位置 => 进入不同视频，用于评论多次 / 弹幕。
VIDEO_CANDIDATES = [
    (0.50, 0.30),
    (0.20, 0.52),
    (0.50, 0.52),
    (0.80, 0.52),
    (0.20, 0.72),
    (0.50, 0.72),
    (0.80, 0.72),
]


def is_video_detail_page(driver):
    """判断当前是否已进入视频详情/播放页。"""
    markers = ["详情", "讨论", "点我发弹幕", "选集", "立即观看", "简介", "收藏", "推荐"]
    for m in markers:
        if driver.find_elements(By.XPATH, f"//*[contains(@text,'{m}')]"):
            return True
    return False


def go_home(driver):
    """尽量返回 APP 首页（处理详情页 / 评论页 / 键盘）。"""
    for _ in range(3):
        try:
            driver.back()
            time.sleep(1.5)
        except Exception:
            break
    if not find_and_click(driver, ["首页"], timeout=5):
        try:
            tap_relative(driver, 0.17, 0.93)
            time.sleep(2)
        except Exception:
            pass
    # 首页可能出现的系统公告/广告弹窗
    for _ in range(3):
        if not dismiss_common_popups(driver):
            break
    time.sleep(2)


def enter_video_by_index(driver, index=0):
    """进入第 index 个视频的详情页（不同 index 点首页不同位置 => 不同视频）。"""
    go_home(driver)
    size = driver.get_window_size()
    w, h = size["width"], size["height"]
    tried = set()
    for off in range(len(VIDEO_CANDIDATES) + 1):
        if is_video_detail_page(driver):
            log("成功进入视频详情页")
            return True
        pos = VIDEO_CANDIDATES[(index + off) % len(VIDEO_CANDIDATES)]
        if pos in tried:
            continue
        tried.add(pos)
        x, y = int(w * pos[0]), int(h * pos[1])
        log(f"尝试点击首页视频区域 (idx={index + off}) -> ({x},{y})")
        try:
            driver.tap([(x, y)])
            time.sleep(4)
        except Exception as e:
            log(f"点击失败: {e}")
    log("未能进入视频详情页")
    return is_video_detail_page(driver)


def enter_first_video(driver):
    """兼容旧调用：进入第一个视频详情页。"""
    return enter_video_by_index(driver, 0)


def start_video_playback(driver):
    """在视频详情页启动播放（弹幕任务的前置条件）。

    策略：1) 优先点击播放类文字按钮；2) 否则点击播放器中央
    （暂停态通常显示大播放按钮）。点击后等待缓冲。
    """
    log("尝试启动视频播放（弹幕任务前置条件）")
    # 1) 文字按钮（最稳妥）
    if find_and_click(driver, [
        "立即观看", "播放", "开始观看", "免费观看", "观看视频",
        "开始播放", "播放视频", "立即播放",
    ], timeout=4):
        log("已点击播放文字按钮，等待加载")
        time.sleep(6)
        return True
    # 2) 点击播放器中央（暂停态通常显示大播放按钮，点击即播放）
    try:
        size = driver.get_window_size()
        w, h = size["width"], size["height"]
        x, y = int(w * 0.5), int(h * 0.22)
        driver.tap([(x, y)])
        log(f"已点击播放器中央 ({x},{y})，等待加载")
        time.sleep(6)
        return True
    except Exception as e:
        log(f"点击播放器中央失败: {e}")
    return False
