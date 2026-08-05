#!/usr/bin/env python3
"""底层 UI 操作封装：按文本点击、模糊匹配点击、截图、滑动、坐标点击、定位输入框。"""
import os

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import log, SCREENSHOT_DIR


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


def click_contains(driver, keywords, timeout=3):
    """点击文本包含任一关键字的可见元素（按钮文案不固定时）。
    返回命中的关键字或 None。"""
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


def save_screenshot(driver, name):
    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
        driver.save_screenshot(path)
        log(f"截图已保存: {path}")
    except Exception as e:
        log(f"截图保存失败: {e}")


def save_ui_dump(driver, name):
    """保存当前页面的控件树（XML）到 SCREENSHOT_DIR，便于分析真实布局。"""
    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(SCREENSHOT_DIR, f"{name}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log(f"UI 控件树已保存: {path}")
    except Exception as e:
        log(f"UI 控件树保存失败: {e}")


def log_ui_summary(driver, max_nodes=40):
    """把当前页面的控件结构直接打到日志（Compose 页面通常没有 text/clickable，
    因此这里同时打印：(1) 有文字/描述的节点；(2) 面积最大的若干节点及其 class+bounds。

    这样在 GitHub Actions 日志里就能看清真实布局，无需下载 artifact。
    """
    try:
        import re as _re
        import xml.etree.ElementTree as ET
        root = ET.fromstring(driver.page_source)
        rows = []
        for n in root.iter("node"):
            a = n.attrib
            rows.append((
                (a.get("text") or "").strip(),
                (a.get("content-desc") or "").strip(),
                a.get("class", ""),
                a.get("bounds", ""),
            ))
        # (1) 有文字/描述的节点
        shown = 0
        for t, d, cls, b in rows:
            if (t or d) and shown < max_nodes:
                log(f"  [UI] text='{t}' desc='{d}' class={cls} bounds={b}")
                shown += 1
        # (2) 面积最大的若干节点（Compose 即使无 text，也能借此推断视频卡片位置）
        sized = []
        for t, d, cls, b in rows:
            nums = _re.findall(r"\d+", b)
            if len(nums) >= 4:
                x1, y1, x2, y2 = map(int, nums[:4])
                sized.append(((x2 - x1) * (y2 - y1), cls, b, t or d))
        sized.sort(reverse=True)
        for area, cls, b, label in sized[:15]:
            log(f"  [BIG] class={cls} bounds={b} {'text=' + label if label else '(no-text)'}")
        log(f"UI 摘要：文字节点 {shown} 个，最大面积节点已打印（用于定位视频卡片/讨论/弹幕入口）")
    except Exception as e:
        log(f"UI 摘要失败: {e}")


def swipe_right(driver, duration=700):
    """屏幕中央从右向左滑动（翻引导页，进入下一页）。"""
    size = driver.get_window_size()
    x, y = size["width"], size["height"]
    start_x, start_y = int(x * 0.85), int(y * 0.5)
    end_x = int(x * 0.15)
    driver.swipe(start_x, start_y, end_x, start_y, duration)


def tap_relative(driver, rx, ry):
    """按屏幕相对坐标点击（rx/ry 范围 0.0~1.0）。返回点击的绝对坐标。"""
    size = driver.get_window_size()
    x, y = int(size["width"] * rx), int(size["height"] * ry)
    driver.tap([(x, y)])
    return x, y


def get_input(driver, hints):
    """按 hint / text 关键字查找输入框，返回首个命中元素。"""
    for xp in hints:
        try:
            el = driver.find_element(By.XPATH, xp)
            return el
        except Exception:
            continue
    return None
