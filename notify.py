#!/usr/bin/env python3
"""飞书卡片通知：支持七牛云可点击链接、飞书自建应用内嵌图、纯文字三种降级策略。"""
import os
import time

import requests

from config import (
    log, FEISHU_WEBHOOK, FEISHU_APP_ID, FEISHU_APP_SECRET,
    QINIU_AK, QINIU_SK, QINIU_BUCKET, QINIU_DOMAIN,
    SCREENSHOT_DIR, SHOT_NAMES, SCREENSHOT_BASE_URL, TASK_RESULTS,
)


def get_tenant_access_token():
    """用自建应用的 app_id/app_secret 换取 tenant_access_token。"""
    if not (FEISHU_APP_ID and FEISHU_APP_SECRET):
        return None
    try:
        r = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10,
        )
        data = r.json()
        if data.get("code") != 0:
            log(f"获取 tenant_access_token 失败: {data}")
            return None
        return data.get("tenant_access_token")
    except Exception as e:
        log(f"获取 tenant_access_token 异常: {e}")
        return None


def upload_image_to_feishu(path):
    """上传本地图片到飞书，返回 image_key（失败返回 None）。"""
    token = get_tenant_access_token()
    if not token:
        return None
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    try:
        with open(path, "rb") as f:
            r = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": (os.path.basename(path), f, "image/png")},
                timeout=30,
            )
        data = r.json()
        if data.get("code") != 0:
            log(f"上传图片失败 {os.path.basename(path)}: {data}")
            return None
        return data.get("data", {}).get("image_key")
    except Exception as e:
        log(f"上传图片异常 {os.path.basename(path)}: {e}")
        return None


def upload_to_qiniu(local_path, key):
    """上传截图到七牛云，返回公开访问 URL；未配置或失败返回 None。"""
    if not (QINIU_AK and QINIU_SK and QINIU_BUCKET and QINIU_DOMAIN):
        return None
    try:
        from qiniu import Auth, put_file
    except ImportError:
        log("未安装 qiniu 依赖，跳过七牛云上传（pip install qiniu）")
        return None
    try:
        q = Auth(QINIU_AK, QINIU_SK)
        token = q.upload_token(QINIU_BUCKET, key, 3600)
        ret, info = put_file(token, key, local_path)
        if info.status_code == 200:
            return f"https://{QINIU_DOMAIN}/{key}"
        log(f"七牛云上传失败 {key}: {info}")
        return None
    except Exception as e:
        log(f"七牛云上传异常 {key}: {e}")
        return None


def notify_feishu():
    if not FEISHU_WEBHOOK:
        log("未配置 FEISHU_WEBHOOK，跳过飞书通知")
        return

    fields = []
    for k, v in TASK_RESULTS.items():
        fields.append({
            "is_short": True,
            "text": {"tag": "lark_md", "content": f"**{k}**\n{'✅ 已完成' if v else '⚠️ 未成功'}"},
        })

    elements = [{"tag": "div", "fields": fields}, {"tag": "hr"}]

    # 截图展示优先级：飞书自建应用内嵌图（image_key）> 七牛云公开链接 > SCREENSHOT_BASE_URL 链接
    qiniu_urls = {}
    if QINIU_AK and QINIU_SK and QINIU_BUCKET and QINIU_DOMAIN:
        log("正在上传截图到七牛云...")
        for n in SHOT_NAMES:
            p = os.path.join(SCREENSHOT_DIR, f"{n}.png")
            if not os.path.exists(p) or os.path.getsize(p) == 0:
                continue
            url = upload_to_qiniu(p, f"{n}.png")
            if url:
                qiniu_urls[n] = url
        if qiniu_urls:
            log(f"已上传 {len(qiniu_urls)} 张截图到七牛云")

    if FEISHU_APP_ID and FEISHU_APP_SECRET:
        for n in SHOT_NAMES:
            p = os.path.join(SCREENSHOT_DIR, f"{n}.png")
            if not os.path.exists(p):
                continue
            if os.path.getsize(p) > 9 * 1024 * 1024:
                log(f"截图 {n} 超过 9MB，跳过内嵌")
                continue
            key = upload_image_to_feishu(p)
            if key:
                elements.append({
                    "tag": "img",
                    "img_key": key,
                    "alt": {"tag": "plain_text", "content": n},
                })
    elif qiniu_urls:
        links = "\n".join(f"- [{n}]({u})" for n, u in qiniu_urls.items())
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**截图（七牛云）：**\n{links}"},
        })
    elif SCREENSHOT_BASE_URL:
        base = SCREENSHOT_BASE_URL.rstrip("/")
        links = "\n".join(
            f"- [{n}]({base}/{n}.png)"
            for n in SHOT_NAMES
            if os.path.exists(os.path.join(SCREENSHOT_DIR, f"{n}.png"))
        )
        if links:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**截图：**\n{links}"},
            })

    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        srv = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        rid = os.environ.get("GITHUB_RUN_ID", "")
        run_url = f"{srv}/{repo}/actions/runs/{rid}"

    note = f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
    if run_url:
        note += f" ｜ [查看运行]({run_url})"
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": note}]})

    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "奈飞工厂 每日任务"},
                "template": "blue",
            },
            "elements": elements,
        },
    }
    try:
        r = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        log(f"飞书卡片通知状态: {r.status_code} {r.text[:160]}")
    except Exception as e:
        log(f"飞书通知失败: {e}")
