#!/usr/bin/env python3
"""入口兼容脚本：原 checkin.py 已重构为多模块，本文件仅作为入口转发到 main.main。

可直接 `python checkin.py`，它与 `python main.py` 等价。
查看各模块请见：config.py / ui.py / apk.py / launch.py / video.py / tasks.py / notify.py / main.py
"""
from main import main

if __name__ == "__main__":
    main()
