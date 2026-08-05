#!/usr/bin/env python3
"""三个核心任务：每日签到、评论领金币、发弹幕领金币（带失败重试）。"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import log, COMMENT_TEXT, DANMAKU_TEXT, MAX_RETRIES
from ui import find_and_click, click_contains, save_screenshot, get_input, tap_relative
from launch import navigate_to_task
from video import enter_first_video


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


def do_comment(driver, wait):
    """执行评论领金币：首页进入任意视频 → 切换到讨论 tab → 输入评论 → 发送。"""
    log("开始执行：评论领金币")
    if not run_with_retry(enter_first_video, "进入视频详情页", driver):
        log("无法进入视频详情页，评论任务失败")
        return False
    time.sleep(2)

    # 切换到「讨论」tab
    if not find_and_click(driver, ["讨论"], timeout=5):
        log("未找到讨论 tab，尝试按坐标点击")
        try:
            tap_relative(driver, 0.33, 0.40)
            time.sleep(2)
        except Exception as e:
            log(f"坐标点击讨论 tab 失败: {e}")

    save_screenshot(driver, "05_comment_page")

    edit = get_input(driver, [
        "//android.widget.EditText[contains(@hint,'评论')]",
        "//android.widget.EditText[contains(@hint,'说点')]",
        "//android.widget.EditText[contains(@hint,'写点什么')]",
        "//android.widget.EditText",
    ])
    if not edit:
        log("未找到评论输入框")
        return False
    edit.click()
    edit.clear()
    edit.send_keys(COMMENT_TEXT)
    log(f"已填写评论: {COMMENT_TEXT}")
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
    """执行发弹幕领金币：首页进入任意视频 → 点击发弹幕入口 → 输入弹幕 → 发送。"""
    log("开始执行：发弹幕领金币")
    if not run_with_retry(enter_first_video, "进入视频详情页", driver):
        log("无法进入视频详情页，弹幕任务失败")
        return False
    time.sleep(2)

    save_screenshot(driver, "07_danmaku_page")

    # 优先点击「点我发弹幕」入口
    if not (find_and_click(driver, ["点我发弹幕"], timeout=5) or
            click_contains(driver, ["发弹幕", "弹幕"], timeout=3)):
        log("未通过文字找到弹幕入口，尝试按坐标点击右下角弹幕按钮")
        try:
            tap_relative(driver, 0.82, 0.43)
            time.sleep(2)
        except Exception as e:
            log(f"坐标点击弹幕入口失败: {e}")

    time.sleep(2)
    save_screenshot(driver, "07_danmaku_input")

    edit = get_input(driver, [
        "//android.widget.EditText[contains(@hint,'弹幕')]",
        "//android.widget.EditText[contains(@hint,'点我发弹幕')]",
        "//android.widget.EditText[contains(@hint,'发言')]",
        "//android.widget.EditText",
    ])
    if not edit:
        log("未找到弹幕输入框")
        return False
    edit.click()
    edit.clear()
    edit.send_keys(DANMAKU_TEXT)
    log(f"已填写弹幕: {DANMAKU_TEXT}")
    time.sleep(1)
    clicked = find_and_click(driver, ["发送", "发布", "提交"], timeout=6)
    time.sleep(2)
    save_screenshot(driver, "08_danmaku_done")
    if clicked:
        log("弹幕已发送")
        return True
    log("未找到发送按钮")
    return False
