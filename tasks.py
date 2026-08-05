#!/usr/bin/env python3
"""三个核心任务：每日签到、评论领金币、发弹幕领金币（带失败重试）。"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import log, COMMENT_TEXT, DANMAKU_TEXT, MAX_RETRIES, COMMENT_COUNT
from ui import find_and_click, click_contains, save_screenshot, get_input, tap_relative, tap_right_of_element, save_ui_dump, log_ui_summary
from launch import navigate_to_task
from video import enter_first_video, enter_video_by_index, go_home, start_video_playback


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


def _press_send_key(driver):
    """按键盘发送键（IME action / 右下角绿色 ✓）。适用于文字按钮不可见的 Compose 界面。"""
    try:
        log("按键盘发送键(KEYCODE_ENTER=66)")
        driver.press_keycode(66)  # KEYCODE_ENTER
        time.sleep(1)
        return True
    except Exception as e:
        log(f"按键盘发送键失败: {e}")
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
    """执行评论领金币：依次在 COMMENT_COUNT 个不同视频下评论。"""
    log(f"开始执行：评论领金币（目标 {COMMENT_COUNT} 条）")
    success = 0
    for i in range(COMMENT_COUNT):
        log(f"--- 评论第 {i + 1}/{COMMENT_COUNT} 条 ---")
        # 进入视频失败时立即跳到下一条，不要整条重试（避免把单次运行拖到十几分钟）
        if not enter_video_by_index(driver, i):
            log("无法进入视频详情页，跳过本条")
            go_home(driver)
            continue
        time.sleep(1)
        # 诊断：仅首条评论保存详情页控件树，避免每条都 dump 拖慢速度
        if i == 0:
            save_ui_dump(driver, f"ui_detail_{i + 1}")
            log_ui_summary(driver)

        # 切换到「讨论」tab
        if not find_and_click(driver, ["讨论"], timeout=5):
            log("未找到讨论 tab，尝试按坐标点击")
            try:
                tap_relative(driver, 0.33, 0.40)
                time.sleep(2)
            except Exception as e:
                log(f"坐标点击讨论 tab 失败: {e}")

        save_screenshot(driver, f"05_comment_{i + 1}_page")

        edit = get_input(driver, [
            "//android.widget.EditText[contains(@hint,'评论')]",
            "//android.widget.EditText[contains(@hint,'说点')]",
            "//android.widget.EditText[contains(@hint,'写点什么')]",
            "//android.widget.EditText",
        ])
        if not edit:
            log("未找到评论输入框，跳过本条")
            go_home(driver)
            continue
        edit.click()
        edit.clear()
        edit.send_keys(COMMENT_TEXT)
        log(f"已填写评论: {COMMENT_TEXT}")
        time.sleep(0.5)

        # 优先按键盘发送键（IME action / 右下角 ✓），再兜底点文字按钮
        # 优先点击输入框右侧的「发送」按钮（截图中蓝色文字按钮在输入框右边）
        clicked = False
        try:
            tap_right_of_element(driver, edit, rx=0.92)
            log("已点击输入框右侧发送按钮")
            clicked = True
        except Exception as e:
            log(f"坐标点击发送按钮失败: {e}")

        # 兜底：按键盘发送键 / 文字按钮
        if not clicked:
            clicked = _press_send_key(driver)
        if not clicked:
            clicked = find_and_click(driver, ["发送", "发布", "提交", "评论", "发送评论"], timeout=3)

        time.sleep(1.5)
        save_screenshot(driver, f"06_comment_{i + 1}_done")
        if clicked:
            success += 1
            log(f"第 {i + 1} 条评论已发送")
        else:
            log(f"第 {i + 1} 条评论发送失败")
        go_home(driver)

    log(f"评论任务完成：成功 {success}/{COMMENT_COUNT} 条")
    return success > 0


def do_danmaku(driver, wait):
    """执行发弹幕领金币：进入视频详情页 → 启动播放 → 点击弹幕入口 → 输入 → 发送。

    关键点：必须先播放视频，否则弹幕无法发送。
    """
    log("开始执行：发弹幕领金币")
    if not run_with_retry(enter_first_video, "进入视频详情页", driver):
        log("无法进入视频详情页，弹幕任务失败")
        return False
    time.sleep(2)
    # 诊断：保存详情页控件树
    save_ui_dump(driver, "ui_detail_danmaku")
    log_ui_summary(driver)

    # 必须先启动播放，否则弹幕无法发送
    start_video_playback(driver)
    time.sleep(2)

    save_screenshot(driver, "07_danmaku_page")

    # 点击弹幕输入入口
    if not (find_and_click(driver, ["点我发弹幕"], timeout=5) or
            click_contains(driver, ["发弹幕", "弹幕"], timeout=3)):
        log("未通过文字找到弹幕入口，尝试按坐标点击")
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

    # 优先点击输入框右侧的「发送」按钮
    clicked = False
    try:
        tap_right_of_element(driver, edit, rx=0.92)
        log("已点击弹幕输入框右侧发送按钮")
        clicked = True
    except Exception as e:
        log(f"坐标点击弹幕发送按钮失败: {e}")

    # 兜底：按键盘发送键 / 文字按钮
    if not clicked:
        clicked = _press_send_key(driver)
    if not clicked:
        clicked = find_and_click(driver, ["发送", "发布", "提交"], timeout=3)

    time.sleep(2)
    save_screenshot(driver, "08_danmaku_done")
    if clicked:
        log("弹幕已发送")
        return True
    log("弹幕发送失败：未找到发送按钮且键盘发送键无效")
    return False
