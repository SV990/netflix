# 奈飞工厂 APP 自动签到

基于 Appium + UiAutomator2 的 Android 自动化脚本，部署在 GitHub Actions 上，每天自动打开 APP 完成「每日签到」「评论领金币」「发弹幕领金币」，并把结果推送到飞书。

## 文件说明

本项目已按职责拆分为多个模块，入口为 `checkin.py`（转发到 `main.py`），GitHub Actions 仍以 `python checkin.py` 运行。

| 文件 | 说明 |
|------|------|
| `checkin.py` | 入口兼容脚本，转发到 `main.main()`（与 `python main.py` 等价） |
| `main.py` | 流程编排：下载/安装 APK → 连接 Appium → 启动干扰处理 → 登录 → 签到/评论/弹幕 → 飞书通知 |
| `config.py` | 环境变量、APP 常量、任务结果字典、统一日志 `log()` |
| `ui.py` | 底层 UI 操作：`find_and_click` / `click_contains` / `save_screenshot` / `swipe_right` / `tap_relative` / `get_input` |
| `apk.py` | APK 下载（直链 + Playwright 绕过反爬）与安装 |
| `launch.py` | 启动干扰处理 `handle_launch_interferences`、弹窗关闭 `dismiss_common_popups`、登录 `try_login`、进任务页 `navigate_to_task` |
| `video.py` | 首页随机进入视频详情页 `enter_first_video`（评论/弹幕任务的前置步骤） |
| `tasks.py` | 三个任务：`do_checkin` / `do_comment` / `do_danmaku`（含 `run_with_retry` 重试） |
| `notify.py` | 飞书卡片通知：七牛云可点击链接 / 飞书自建应用内嵌图 / 纯文字 三种降级 |
| `inspect_ui.py` | （可选）本地 adb 检视工具：dump 当前页控件树并精炼打印 |
| `requirements.txt` | Python 依赖 |
| `.github/workflows/daily-checkin.yml` | GitHub Actions 定时工作流 |
| `NEW-奈飞工厂-V1.0.4.apk` | 本地 APK 样本（不要提交到 GitHub） |

## 前置准备

1. 把本目录推送为一个 **Private** GitHub 仓库。
2. 不要把 `NEW-奈飞工厂-V1.0.4.apk` 提交到仓库（超过 100 MB，且 APK 不应入版本库）。
3. APK 下载地址填入 `APK_DOWNLOAD_URL`，两种形式都支持：
   - **直链**：可直接下载的 `.apk` 文件 URL（如 GitHub Release 附件、对象存储直链）。
   - **反爬分享页**：蓝奏云（`lanzouw.com`）、`dmpdmp.com` 等会在下载前插入一段 JS 反爬挑战页（页面约 4KB、含 `arg1` 混淆脚本）。脚本检测到这类页面时会**自动用 Playwright 无头浏览器绕过挑战并完成下载**，无需你手动提取直链。
   - ⚠️ 推荐优先用 **GitHub Release 附件**做直链：最轻量、最稳定，不会触发反爬，也不需要下载浏览器。

## 配置 GitHub Secrets / Variables

在仓库 **Settings → Secrets and variables → Actions** 中添加：

| 类型 | 名称 | 说明 |
|------|------|------|
| Secret | `APP_USERNAME` | 你的登录账号（邮箱） |
| Secret | `APP_PASSWORD` | 你的登录密码 |
| Secret | `APK_DOWNLOAD_URL` | APK 直链或蓝奏云分享页 |
| Secret | `FEISHU_WEBHOOK` | 飞书机器人 Webhook 地址 |
| Secret | `FEISHU_APP_ID` | 飞书自建应用的 App ID（用于上传截图，见下方说明） |
| Secret | `FEISHU_APP_SECRET` | 飞书自建应用的 App Secret（与上面成对） |
| Secret | `QINIU_AK` | 七牛云 AccessKey（用于上传截图） |
| Secret | `QINIU_SK` | 七牛云 SecretKey（与上面成对） |
| Secret | `QINIU_BUCKET` | 七牛云存储桶名称（例：你的桶名 `tja9zism0`） |
| Secret | `QINIU_DOMAIN` | 七牛云绑定的访问域名（默认 `tja9zism0.hn-bkt.clouddn.com`，即你提供的域名） |
| Secret | `SCREENSHOT_BASE_URL` | （可选）可公开访问的截图目录，仅在你**未配置七牛云**且未配置飞书自建应用时，作为截图可点击链接的退路 |
| Variable | `MAX_RETRIES` | （可选）单任务失败重试次数，默认 `2` |
| Variable | `ANDROID_DEVICE` | （可选）本地/远程 ADB 设备序列号，默认 `emulator-5554`。若你换用雷电、MuMu、真机或多开，需填 `ANDROID_DEVICE=emulator-5556` 等实际序列号 |
| Variable | `APPIUM_HOST` | （可选）Appium Server 地址，默认 `http://127.0.0.1:4723` |

> ⚠️ **关于飞书截图**：飞书自定义机器人（`bot/v2/hook/...`）**不能直接内嵌外链图片**。脚本提供两种看图方式：
> - **七牛云可点击链接（推荐、零自建应用）**：配置 `QINIU_AK`/`QINIU_SK`/`QINIU_BUCKET`（域名默认已是你的 `tja9zism0.hn-bkt.clouddn.com`），脚本跑完会把截图传到七牛云，飞书卡片里挂上每张截图的可点击链接，点开即看大图。
> - **飞书内嵌图片（需自建应用）**：要像聊天图片那样直接内嵌，需飞书自建应用的 `tenant_access_token` 把图传成 `image_key`。即额外创建自建应用并填 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`。
> 两者都未配置时，飞书卡片退化为纯文字状态卡（不报错）。

### 创建飞书自建应用（用于上传截图）

1. 登录 [飞书开放平台 → 开发者后台](https://open.feishu.cn/)，**创建企业自建应用**。
2. 进入应用 → **凭证与基础信息**，复制 **App ID** 和 **App Secret**（填到 GitHub Secrets 的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`）。
3. 进入应用 → **权限管理**，搜索并开通 `im:image`（上传与发送图片）和 `im:message`（发送消息）权限，点 **申请**。
4. 把该自建应用 **发布** 或至少 **申请权限生效**（开发版点击申请即可在测试范围生效）。
5. 在飞书群里把**同一个群机器人（webhook）** 加到群里即可——上传用自建应用身份，发送仍走你的 webhook。

> 若不想走自建应用：保持只配 `FEISHU_WEBHOOK`，并在卡片里用 `SCREENSHOT_BASE_URL` 指向可公网访问的截图目录（需该域名在飞书应用「可信任的图片链接域名」中配置），也能在卡片里看到截图链接。

## 运行方式

- **定时执行**：默认每天北京时间 00:00 自动运行（GitHub Actions cron 为 UTC，已换算为 `0 16 * * *`）。
- **手动触发**：进入仓库 Actions → Daily Check-in → Run workflow。
- **Runner 必须选 `ubuntu-latest`**：工作流固定使用 Linux runner（带 KVM 硬件加速）。**不要**改成 `macos-latest`——macOS（Apple Silicon）没有 KVM，Android 模拟器会卡在启动、`adb` 一直找不到 `emulator-5554` 而失败。

## 增强特性

- **失败自动重试**：每个任务（登录 / 签到 / 评论 / 弹幕）失败会按 `MAX_RETRIES` 重试，提升偶发网络/加载问题的容错。
- **飞书卡片通知**：结果以 interactive 卡片推送，含三项任务状态、执行时间、Actions 运行链接。各阶段截图默认**上传到七牛云并以可点击链接**展示（需配置 `QINIU_AK`/`QINIU_SK`/`QINIU_BUCKET`，域名默认已是你的 `tja9zism0.hn-bkt.clouddn.com`）；若额外配置了飞书自建应用 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`，截图会改为**直接内嵌**为图片；都未配置则退化为纯文字卡。

## 本地调试（可选）

需要本地安装 Android SDK + 模拟器 + Appium Server。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动模拟器并安装 APK
emulator -avd Pixel_4_API_30 &
adb install -r NEW-奈飞工厂-V1.0.4.apk

# 3. 启动 Appium
appium --address 127.0.0.1 --port 4723

# 4. 运行脚本
export APP_USERNAME="你的账号"
export APP_PASSWORD="你的密码"
export APK_PATH="NEW-奈飞工厂-V1.0.4.apk"
export ANDROID_DEVICE="emulator-5556"   # 雷电/MuMu/真机/多开时改成 adb devices 里看到的序列号
export FEISHU_WEBHOOK="你的飞书 webhook"
export FEISHU_APP_ID="你的自建应用 App ID"   # 内嵌截图用，可选
export FEISHU_APP_SECRET="你的自建应用 App Secret"  # 内嵌截图用，可选
python checkin.py
```

## 已知信息

- 包名：`com.nfgcz.app`
- 启动 Activity：`com.yy.myuko.app.MainActivityTinker`

## 常见问题

1. **首次启动卡在引导页/开屏广告**：脚本在启动后会自动处理 onboarding 引导页（向右滑动翻页，并尝试点击「跳过」「立即体验」「进入」「同意并继续」等按钮）和系统权限弹窗。若你的 APK 首次启动页文案或按钮特殊，请根据 `01_after_launch.png` / `01_after_onboarding.png` 调整 `handle_launch_interferences()` 里的文案列表或滑动次数。
2. **登录后弹出「系统公告」「升级提示」等弹窗**：脚本在登录后会自动尝试点击「我知道了」「关闭」「跳过」等关闭按钮。若弹窗按钮文案特殊，请根据 `02_after_login.png` / `03_home_page.png` 调整 `dismiss_common_popups()` 里的文案或 fallback 点击坐标。
2. **找不到签到按钮**：APP 界面可能随版本变化，请根据 Actions 上传的截图调整 `checkin.py` 中的 XPath。
3. **登录失败**：当前脚本已按「底部「我的」tab → 点击「未登录」→ 输入邮箱/密码 → 点击「登录」」的流程实现。若登录页结构变化，请根据截图调整 `try_login()` 里的 XPath。
   > 注意：该 APP 提示「每日最多切换设备 3 次」，频繁手动/自动运行可能触发登录限制，建议只在定时任务跑一次。
3. **APK 下载失败**：直链需公开可访问；若用蓝奏云 / dmpdmp 等反爬链接且脚本报「无头浏览器绕过失败」，请改用 GitHub Release 附件等直链（最稳）。
4. **评论/弹幕未成功**：这两个任务依赖具体播放页/输入框结构，是最容易随版本变化的部分。请对照 Actions 上传的截图调整 `do_comment()` / `do_danmaku()` 中的文本与 XPath，或设置环境变量 `COMMENT_TEXT` / `DANMAKU_TEXT` 自定义发送内容。

## 免责声明

本脚本仅供个人学习和自动化自己账号使用，请遵守相关平台规则。
