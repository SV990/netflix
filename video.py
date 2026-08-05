#!/usr/bin/env python3
"""视频详情页进入与播放控制：首页点击不同视频进入详情页、启动播放。"""
import re
import time

from selenium.webdriver.common.by import By

from config import log
from ui import find_and_click, click_contains, tap_relative, save_ui_dump, log_ui_summary
from launch import dismiss_common_popups

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


def is_video_detail_page(driver):
    """判断当前是否已进入视频详情/播放页。

    Compose 页面 text 多为空，因此除文字标记外，额外识别视频播放控件
    （VideoView / TextureView / SurfaceView），只要出现即视为已进详情页。
    """
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
    # 诊断：保存首页真实控件树，并直接在日志打印关键节点（无需下载 artifact 即可分析布局）
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

    策略：
      1) 回到首页并等待加载；
      2) 按 index 先向上滑动 feed 若干次，确保进入「不同」视频；
      3) 优先点击「面积最大的可点击元素」（视频卡片）；
      4) 失败则用坐标候选兜底。
    """
    go_home(driver)
    time.sleep(2)

    # 不同 index => 不同位置，保证 5 条评论落在不同视频
    for _ in range(min(index, 6)):
        swipe_feed_up(driver)

    # 方式一：元素定位（按面积找视频卡片候选，逐个尝试点不同位置）
    cards = find_video_card(driver)
    log(f"元素定位找到 {len(cards)} 个候选视频卡片")
    for off in range(len(cards)):
        if is_video_detail_page(driver):
            log("成功进入视频详情页")
            return True
        card = cards[(index + off) % len(cards)]
        try:
            card.click()
            time.sleep(2)
            log("已点击视频卡片（元素定位）")
        except Exception as e:
            log(f"点击视频卡片失败: {e}")
    if is_video_detail_page(driver):
        log("成功进入视频详情页")
        return True

    # 方式二：坐标兜底（每个候选只等 1.5 秒，快速失败，避免无谓拖时长）
    size = driver.get_window_size()
    w, h = size["width"], size["height"]
    for off in range(len(VIDEO_CANDIDATES)):
        if is_video_detail_page(driver):
            log("成功进入视频详情页")
            return True
        pos = VIDEO_CANDIDATES[(index + off) % len(VIDEO_CANDIDATES)]
        log(f"坐标兜底点击 ({pos[0]},{pos[1]})")
        try:
            driver.tap([(int(w * pos[0]), int(h * pos[1]))])
            time.sleep(1.5)
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
