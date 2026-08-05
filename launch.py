#!/usr/bin/env python3
"""启动流程：处理引导页/广告/权限弹窗、登录、进入任务页。"""
import time
import re
import xml.etree.ElementTree as ET

from selenium.webdriver.common.by import By

from config import log, APP_USERNAME, APP_PASSWORD, PKG, ACTIVITY
from ui import find_and_click, click_contains, swipe_right, tap_relative, get_input, save_ui_dump, log_ui_summary


def _parse_nodes(src):
    """把 page_source 解析成 [(label, x1,y1,x2,y2), ...]，label 取 text/content-desc。"""
    nodes = []
    try:
        root = ET.fromstring(src)
    except Exception:
        return nodes
    for n in root.iter("node"):
        a = n.attrib
        label = (a.get("text") or a.get("content-desc") or "").strip()
        bounds = a.get("bounds", "")
        if label and bounds:
            nums = [int(x) for x in re.findall(r"\d+", bounds)]
            if len(nums) >= 4:
                nodes.append((label, nums[0], nums[1], nums[2], nums[3]))
    return nodes


def _tap_label(driver, kws, nodes):
    """在节点列表里找 label 含任一关键词的节点，点其几何中心。返回是否命中。"""
    for label, x1, y1, x2, y2 in nodes:
        if any(kw in label for kw in kws):
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            try:
                driver.tap([(cx, cy)])
                return True
            except Exception:
                return False
    return False


def _parse_all_bounds(src):
    """解析所有带 bounds 的节点（不依赖 text/content-desc），返回 [(class,x1,y1,x2,y2), ...]。

    Compose 引导页通常没有任何文字/描述，必须靠几何特征识别。
    """
    nodes = []
    try:
        root = ET.fromstring(src)
    except Exception:
        return nodes
    for n in root.iter("node"):
        a = n.attrib
        bounds = a.get("bounds", "")
        nums = [int(x) for x in re.findall(r"\d+", bounds)]
        if len(nums) >= 4:
            nodes.append((a.get("class", ""), nums[0], nums[1], nums[2], nums[3]))
    return nodes


def is_onboarding_page(xml, w, h):
    """基于几何特征判断是否为 onboarding/引导页。

    典型特征：APP 内、没有首页/底部 Tab/详情页文字、且存在一个占屏较大的媒体区
    （居中插画，或近似全屏引导大图）+ 底部若干指示小点。

    注意：早期版本的严格上下界会把「近似全屏」的引导大图排除掉，导致误判为普通页、
    从而只滑动不点击。这里放宽上界以兼容全屏引导图。
    """
    nodes = _parse_all_bounds(xml)
    if not nodes:
        return False
    # 若出现首页/详情/任务等特征文字，直接判定不是 onboarding
    home_or_detail = ["首页", "推荐", "我的", "任务", "福利", "分类", "视频",
                      "详情", "讨论", "点我发弹幕", "选集", "签到", "评论", "弹幕"]
    if any(k in xml for k in home_or_detail):
        return False
    big = 0
    dots = 0
    for cls, x1, y1, x2, y2 in nodes:
        bw, bh = x2 - x1, y2 - y1
        # 大媒体区：占屏较宽且较高，位于中上部（含近似全屏/全屏引导大图，不再加 y2 上界）
        if (0.55 * w < bw) and (0.45 * h < bh) and (y1 < 0.6 * h):
            big += 1
        # 底部指示点：靠近底部、宽高较小、水平居中
        if y1 > 0.82 * h and bh < 0.12 * h and bw < 0.2 * w:
            cx = (x1 + x2) / 2
            if 0.2 * w < cx < 0.8 * w:
                dots += 1
    return (big >= 1 and dots >= 1) or (big >= 1 and not any(
        k in xml for k in ["首页", "推荐", "我的", "任务", "详情", "讨论"]))


def handle_onboarding_pages(driver, max_swipes=4):
    """处理 Compose 多页 onboarding/引导页（如「流畅播放→高清画质→丰富片库→个性推荐」）。

    真实流程（截图确认）：
      - 共 4 页滑动引导，底部有 3~5 个指示点；
      - 最后一页（个性推荐）底部中央有蓝色「立即开启」按钮；
      - 点击后进入首页，并立即弹出「系统公告」。

    这些页面通常不暴露 text/content-desc，因此策略：
      1) 先尝试按文字点「立即开启/开启/完成/下一步」等；
      2) 文字找不到则按坐标点底部中央按钮（y≈0.82，截图按钮位置）；
      3) 仍未离开则向右滑动翻下一页，重复 1~2；
      4) 最多滑动 max_swipes 次。
    """
    log("检查 onboarding/引导页")
    try:
        size = driver.get_window_size()
        w, h = size["width"], size["height"]
    except Exception as e:
        log(f"获取屏幕尺寸失败: {e}")
        return False

    home_markers = ["首页", "推荐", "我的", "任务", "福利", "分类", "视频"]
    finish_texts = ["立即开启", "开启", "立即体验", "开始体验", "进入", "开始",
                    "完成", "下一步", "知道了", "我知道了"]

    for i in range(max_swipes + 1):
        try:
            xml = driver.page_source
        except Exception:
            xml = ""
        if any(kw in xml for kw in home_markers):
            log("已到达 APP 主界面")
            return True
        if not is_onboarding_page(xml, w, h):
            log("当前页面不是 onboarding 页，结束处理")
            return True

        log(f"检测到 onboarding 页（第 {i+1}/{max_swipes+1} 页），尝试点击结束按钮")
        # 1) 先按文字点（最后一页可能暴露「立即开启」等）
        nodes = _parse_nodes(xml)
        if _tap_label(driver, finish_texts, nodes):
            time.sleep(1.5)
            try:
                xml2 = driver.page_source
            except Exception:
                xml2 = ""
            if any(kw in xml2 for kw in home_markers):
                log("点击结束按钮后到达主界面")
                return True
            if xml2 and not is_onboarding_page(xml2, w, h):
                log("点击结束按钮后离开 onboarding 页")
                return True
            continue

        # 2) 按坐标点底部中央蓝色按钮（截图中「立即开启」约位于 y=0.82）
        for ry in [0.82, 0.85, 0.78, 0.88]:
            tap_relative(driver, 0.50, ry)
            time.sleep(1.2)
            try:
                xml2 = driver.page_source
            except Exception:
                xml2 = ""
            if any(kw in xml2 for kw in home_markers):
                log("坐标点击底部按钮后到达主界面")
                return True
            if xml2 and not is_onboarding_page(xml2, w, h):
                log("坐标点击底部按钮后离开 onboarding 页")
                return True

        # 3) 仍未离开，向右滑动翻下一页
        log("尝试右滑翻下一页引导")
        swipe_right(driver, duration=350)
        time.sleep(1)

    log("处理 onboarding 页达到最大次数")
    return False


def _swipe_left(driver, duration=350):
    """屏幕中央从左向右滑动（翻引导页，进入下一页）。"""
    size = driver.get_window_size()
    x, y = size["width"], size["height"]
    driver.swipe(int(x * 0.15), int(y * 0.5), int(x * 0.85), int(y * 0.5), duration)


def handle_launch_interferences(driver, max_rounds=14):
    """处理首次启动的引导页、开屏广告、隐私协议与权限弹窗。

    性能要点：Compose 应用下每次 find_elements 都会触发完整控件树 dump，极慢。
    这里改为**每轮只 page_source 一次**，本地解析节点后点坐标，把「每轮 4~6 次 dump」
    降到「每轮 1 次」。

    健壮性要点（针对纯 Compose、无 text/desc 的引导页）：
      - 几何识别「大图 + 底部指示点」的 onboarding 页，按坐标点底部中央按钮；
      - 纯图形（0 文字）引导页很可能是「点一下翻一页」而非滑动翻页，因此：
        连续点击多个候选按钮位置走引导，页面一旦变化就继续点下一处，
        仅当连续多次点击都无变化时才退而尝试滑动翻页；
      - 卡住时保存一次真实布局（ui_launch_stuck）便于排查。
    """
    log("检查并处理启动引导页/广告/弹窗")

    # 先保存一份启动后的真实布局，便于后续排查（一次性，不在热循环内）
    try:
        save_ui_dump(driver, "ui_launch_before")
        log_ui_summary(driver)
    except Exception:
        pass

    finish_texts = ["跳过", "跳过广告", "立即体验", "进入", "开始体验", "开始", "马上体验",
                    "开启", "立即开启", "知道了", "我知道了", "同意并继续", "同意", "确定", "下一步",
                    "完成", "进入奈飞", "立即进入", "关闭", "暂不", "以后再说"]
    finish_kw = ["跳过", "体验", "进入", "开启", "同意", "完成", "开始", "下一步", "知道了", "关闭"]
    perm_texts = ["允许", "仅使用期间允许", "ALLOW", "ALWAYS", "始终允许"]
    perm_kw = ["允许", "同意"]
    tab_keywords = ["首页", "推荐", "我的", "任务", "福利", "分类", "视频"]

    # 纯图形引导页（无文字）时尝试点击的候选位置（相对坐标），覆盖常见按钮区
    graphic_taps = [
        (0.50, 0.85), (0.50, 0.90), (0.50, 0.80),
        (0.82, 0.86), (0.82, 0.90), (0.50, 0.72),
        (0.50, 0.45), (0.50, 0.62),
    ]

    last_xml = ""
    no_change = 0
    tap_idx = 0
    for i in range(max_rounds + 1):
        # 每轮仅 dump 一次，本地解析（避免多次控件树查找拖慢）
        try:
            xml = driver.page_source
        except Exception:
            xml = ""
        nodes = _parse_nodes(xml)

        # 1) 是否已到达主界面
        if any(any(k in lbl for k in tab_keywords) for lbl, *_ in nodes) or \
           any(k in xml for k in tab_keywords):
            log("已到达 APP 主界面")
            return
        # 2) 结束/同意按钮（精确）
        if _tap_label(driver, finish_texts, nodes):
            log("点击了启动页结束/同意按钮（精确）")
            time.sleep(0.8)
            continue
        # 3) 模糊匹配
        if _tap_label(driver, finish_kw, nodes):
            log("点击了启动页结束按钮（模糊匹配）")
            time.sleep(0.8)
            continue
        # 4) 权限弹窗
        if _tap_label(driver, perm_texts, nodes):
            log("处理了系统权限弹窗（精确）")
            time.sleep(0.5)
            continue
        if _tap_label(driver, perm_kw, nodes):
            log("处理了权限弹窗（模糊）")
            time.sleep(0.5)
            continue

        # 5) Compose onboarding 页几何识别（文字未暴露时，如「个性推荐」页）
        try:
            size = driver.get_window_size()
            if is_onboarding_page(xml, size["width"], size["height"]):
                log("几何特征识别到 onboarding 页，进入专门处理流程")
                if handle_onboarding_pages(driver):
                    return
                continue
        except Exception as e:
            log(f"onboarding 几何识别异常: {e}")

        # 6) 纯图形屏幕（0 文字）：优先连续点击候选位置走引导，页面变化即视为翻页成功
        has_text = any(lbl for lbl, *_ in nodes)
        if not has_text:
            pos = graphic_taps[tap_idx % len(graphic_taps)]
            tap_idx += 1
            log(f"纯图形屏幕，尝试点击 ({pos[0]},{pos[1]}) 第{tap_idx}次")
            try:
                tap_relative(driver, pos[0], pos[1])
                time.sleep(1.2)
                xml3 = driver.page_source
            except Exception:
                xml3 = xml
            if any(k in xml3 for k in tab_keywords):
                log("点击后已到达 APP 主界面")
                return
            if xml3 and xml3 != last_xml:
                log("页面已变化（可能翻到下一引导页），继续点击")
                last_xml = xml3
                no_change = 0
                continue
            # 无变化
            no_change += 1
            last_xml = xml3
            if no_change >= 4:
                # 连续多次点击无变化 → 试一次滑动翻页（交替方向）
                direction = "右" if no_change % 2 == 0 else "左"
                log(f"连续点击无变化，尝试滑动翻页（{direction}）")
                if direction == "右":
                    swipe_right(driver, duration=350)
                else:
                    _swipe_left(driver, duration=350)
                time.sleep(1)
                no_change = 0
                last_xml = ""
            if i % 6 == 0:
                try:
                    save_ui_dump(driver, "ui_launch_stuck")
                    log_ui_summary(driver)
                except Exception:
                    pass
            continue

        # 7) 有文字但没匹配上 → 兜底滑动翻页（交替方向）
        direction = "右" if i % 2 == 0 else "左"
        log(f"第 {i+1} 次尝试滑动翻页（{direction}）")
        if direction == "右":
            swipe_right(driver, duration=350)
        else:
            _swipe_left(driver, duration=350)
        time.sleep(1)

    # 兜底：最后再精确点一次结束按钮
    try:
        xml = driver.page_source
        nodes = _parse_nodes(xml)
        _tap_label(driver, finish_texts, nodes)
    except Exception:
        pass
    log("启动引导处理结束（已达最大滑动次数）")


def dismiss_common_popups(driver, timeout=3):
    """处理 APP 内常见的弹窗：系统公告、升级提示、活动浮层等。
    优先点击「我知道了/关闭/跳过」，不阻塞主流程。
    """
    # 1) 系统公告（截图：白色弹窗，右下角蓝色「我知道了」按钮）
    if driver.find_elements(By.XPATH, "//*[@text='系统公告']"):
        log("检测到系统公告弹窗")
        # 优先点「我知道了」；若文案不同，尝试同类确认按钮
        for txt in ["我知道了", "知道了", "确认", "关闭"]:
            if find_and_click(driver, [txt], timeout=timeout):
                log(f"已点击 {txt} 关闭系统公告")
                time.sleep(1.5)
                return True
        # fallback：点弹窗右下角蓝色按钮区域（截图中约 x=0.75, y=0.80）
        size = driver.get_window_size()
        x, y = size["width"], size["height"]
        for rx, ry in [(0.75, 0.80), (0.75, 0.75), (0.75, 0.85)]:
            tap_x, tap_y = int(x * rx), int(y * ry)
            log(f"尝试点击系统公告右下角({tap_x},{tap_y})")
            try:
                driver.tap([(tap_x, tap_y)])
                time.sleep(1.5)
                return True
            except Exception:
                pass

    # 2) 通用关闭/跳过/以后再说
    for txt in ["关闭", "我知道了", "知道了", "暂不", "以后再说", "跳过"]:
        try:
            el = driver.find_element(By.XPATH, f"//*[@text='{txt}']")
            if el.is_displayed():
                el.click()
                log(f"关闭通用弹窗按钮：{txt}")
                time.sleep(1)
                return True
        except Exception:
            continue
    return False


def ensure_app_foreground(driver):
    """确保奈飞工厂 APP 处于前台；若被退到桌面/后台则重新拉起。

    这是防止脚本「卡在系统桌面」的关键兜底：一旦检测到当前 package 不是本 APP，
    就通过 activate_app / start_activity 重新拉起，避免后续所有点击都打在桌面上。
    """
    try:
        cur = driver.current_package
    except Exception:
        cur = None
    if cur == PKG:
        return True
    log(f"当前不在 APP 内（package={cur}），尝试重新拉起 {PKG}")
    try:
        driver.activate_app(PKG)
    except Exception:
        try:
            driver.start_activity(PKG, ACTIVITY)
        except Exception as e:
            log(f"重新拉起 APP 失败: {e}")
    time.sleep(5)
    try:
        dismiss_common_popups(driver)
    except Exception:
        pass
    try:
        return driver.current_package == PKG
    except Exception:
        return False


def is_login_page(driver):
    """判断是否已在账号密码登录页。"""
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
