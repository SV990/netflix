#!/usr/bin/env python3
"""视频详情页进入与播放控制：首页点击不同视频进入详情页、启动播放。"""
import re
import time

from selenium.webdriver.common.by import By

from config import log, PKG
from ui import find_and_click, click_contains, tap_relative, save_ui_dump, log_ui_summary
from launch import dismiss_common_popups, ensure_app_foreground

# 首页视频卡片候选点击位置（相对坐标，兜底用）。
VIDEO_CANDIDATES = [
    (0.50, 0.30),
    (0.20, 0.52),
    (0.50, 0.52),
    (0.80, 0.52),
    (0.20, 0.72),
    (0.50, 0.72),
    (0.80, 0.72),
]


def _parse_bounds(bounds):
    """解析 uiautomator 的 bounds 字符串 '[x1,y1][x2,y2]' -> (x1,y1,x2,y2)。"""
    nums = re.findall(r"\d+", bounds or "")
    if len(nums) >= 4:
        return int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
    return None


def is_home_feed(driver):
    """判断是否停在 APP 的首页/底部 Tab 页（首页/推荐/我的/任务 等 tab 可见）。"""
    for t in ["首页", "推荐", "我的", "任务", "视频", "福利", "分类", "发现", "精选"]:
        try:
            if driver.find_elements(By.XPATH, f"//*[@text='{t}']"):
                return True
        except Exception:
            continue
    return False


def is_video_detail_page(driver):
    """判断当前是否已进入视频详情/播放页。

    判定策略（针对 Compose 页面 text 多为空的特点）：
      1) 不在本 APP 内 → 不是；
      2) 仍能看到首页/底部 Tab → 说明还在 feed，不是详情页；
      3) 命中详情页特征文字或视频播放控件 → 是；
      4) 在 APP 内且看不到首页 Tab → 默认视为已进入详情页（最稳，避免纯 Compose 漏判）。
    """
    try:
        if driver.current_package != PKG:
            return False
    except Exception:
        return False
    if is_home_feed(driver):
        return False
    markers = ["详情", "讨论", "点我发弹幕", "选集", "立即观看", "简介", "收藏", "相关推荐", "发弹幕", "评论"]
    for m in markers:
        try:
            if driver.find_elements(By.XPATH, f"//*[contains(@text,'{m}')]"):
                return True
        except Exception:
            continue
    for cls in ["VideoView", "TextureView", "SurfaceView"]:
        try:
            if driver.find_elements(By.XPATH, f"//*[contains(@class,'{cls}')]"):
                return True
        except Exception:
            continue
    # 在 APP 内、看不到首页 Tab，默认已经进入详情页
    return True


def go_home(driver):
    """尽量返回 APP 首页 feed（关键：绝不能退到系统桌面）。"""
    ensure_app_foreground(driver)  # 先保证在 APP 内
    # 优先点底部主 tab 回到 feed
    if find_and_click(driver, ["首页", "推荐", "视频", "发现", "精选"], timeout=5):
        log("已点击主 tab 回到 feed")
        time.sleep(2)
    else:
        # 兜底：最多两次 back（不过度，避免退出 APP）
        for _ in range(2):
            try:
                driver.back()
                time.sleep(1.5)
            except Exception:
                break
            if find_and_click(driver, ["首页", "推荐", "视频", "发现"], timeout=3):
                break
    # 首页可能出现的系统公告/广告弹窗
    for _ in range(3):
        if not dismiss_common_popups(driver):
            break
    time.sleep(2)
    ensure_app_foreground(driver)  # 若 back 误退到桌面，这里拉回
    # 仅在 APP 内时才保存 dump（避免把桌面控件树当成首页）
    if driver.current_package == PKG:
        save_ui_dump(driver, "ui_home")
        log_ui_summary(driver)


def find_video_card(driver):
    """在首页内容区找视频卡片候选。

    注意：该 APP 用 Compose 编写，uiautomator 节点多半没有 text / clickable='true'，
    因此这里收集「所有含 bounds 的节点」，按面积筛选（排除底部 tab 与顶部状态栏，
    且只取面积在 4%~60% 屏之间的区块，视频卡片通常落在此区间），返回面积最大的若干候选。
    """
    try:
        els = driver.find_elements(By.XPATH, "//*")
    except Exception:
        return []
    size = driver.get_window_size()
    w, h = size["width"], size["height"]
    cands = []
    for el in els:
        try:
            b = _parse_bounds(el.get_attribute("bounds"))
            if not b:
                continue
            x1, y1, x2, y2 = b
            if y2 > h * 0.9 or y1 < h * 0.06:   # 排除底部 tab / 顶部状态栏
                continue
            area = (x2 - x1) * (y2 - y1)
            ratio = area / (w * h)
            if 0.04 <= ratio <= 0.6:            # 视频卡片面积区间
                cands.append((area, el))
        except Exception:
            continue
    cands.sort(key=lambda x: x[0], reverse=True)
    return [el for _, el in cands[:5]]           # 返回面积最大的前 5 个候选


def swipe_feed_up(driver):
    """在首页 feed 上向上滑动，切换/加载下一个视频。"""
    size = driver.get_window_size()
    w, h = size["width"], size["height"]
    try:
        driver.swipe(int(w * 0.5), int(h * 0.75), int(w * 0.5), int(h * 0.25), 600)
    except Exception as e:
        log(f"滑动feed失败: {e}")
    time.sleep(2)


def enter_video_by_index(driver, index=0):
    """进入第 index 个视频的详情页。

    策略（针对 Compose 无 text 的鲁棒版本）：
      1) 确保 APP 在前台；
      2) 回到首页 feed 并等待加载；
      3) 按 index 先向上滑动 feed 若干次，确保进入「不同」视频；
      4) 依次尝试：面积最大候选元素 → 多个 feed 坐标点（每次只等 2 秒，快速失败）。
      全程以 is_video_detail_page 校验是否真正进入详情页。
    """
    ensure_app_foreground(driver)
    go_home(driver)
    time.sleep(2)

    # 不同 index => 不同位置，保证 5 条评论落在不同视频
    for _ in range(min(index, 6)):
        swipe_feed_up(driver)

    # feed 内容区候选点击点（相对坐标）。优先卡片中部，再覆盖多列。
    feed_taps = [
        (0.50, 0.52), (0.50, 0.42), (0.50, 0.64),
        (0.25, 0.52), (0.75, 0.52),
        (0.25, 0.42), (0.75, 0.64), (0.50, 0.30),
    ]
    size = driver.get_window_size()
    w, h = size["width"], size["height"]

    # 方式一：元素定位（按面积找视频卡片候选，逐个尝试）
    cards = find_video_card(driver)
    log(f"元素定位找到 {len(cards)} 个候选视频卡片")
    for off in range(max(len(cards), 1)):
        if is_video_detail_page(driver):
            log("成功进入视频详情页")
            return True
        if cards:
            card = cards[(index + off) % len(cards)]
            try:
                card.click()
                time.sleep(2.5)
                log("已点击视频卡片（元素定位）")
                if is_video_detail_page(driver):
                    return True
            except Exception as e:
                log(f"点击视频卡片失败: {e}")

        # 方式二：坐标兜底
        pos = feed_taps[(index + off) % len(feed_taps)]
        log(f"点击视频区域 ({pos[0]},{pos[1]})")
        try:
            driver.tap([(int(w * pos[0]), int(h * pos[1]))])
            time.sleep(2.5)
        except Exception as e:
            log(f"点击失败: {e}")
        if is_video_detail_page(driver):
            log("成功进入视频详情页")
            return True

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
