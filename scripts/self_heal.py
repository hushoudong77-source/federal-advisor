#!/usr/bin/env python3
"""
联邦投顾 — 依赖自愈引导脚本 V1.0
根因：会话环境不持久，tickflow 等 pip 包在每次新对话启动后可能丢失。
本模块提供 ensure_dep() 函数，在任何脚本 import tickflow 前调用，
自动检测缺失并 pip install 补装，永久根治「TickFlow 掉了」问题。

用法：
    from self_heal import ensure_tickflow
    ensure_tickflow()
    from tickflow import TickFlow
"""

import importlib
import subprocess
import sys


def _pip_install(pkg: str) -> bool:
    """静默安装包，返回是否成功。"""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def ensure_module(module_name: str, pip_name: str = None) -> bool:
    """
    确保某个模块可用。若 import 失败，自动 pip install 后重试。
    返回最终是否可用。
    """
    pip_name = pip_name or module_name
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        # 尝试安装
        if _pip_install(pip_name):
            try:
                importlib.import_module(module_name)
                return True
            except ImportError:
                return False
        return False


def ensure_tickflow() -> bool:
    """确保 tickflow 可用。TickFlow 是全池25标日线唯一真源。"""
    return ensure_module("tickflow", "tickflow")


def ensure_all() -> dict:
    """一次确保全部关键依赖，返回各依赖状态。"""
    deps = {
        "tickflow": ("tickflow", "tickflow"),
        "httpx": ("httpx", "httpx"),
        "pandas": ("pandas", "pandas"),
        "numpy": ("numpy", "numpy"),
        "requests": ("requests", "requests"),
    }
    status = {}
    for key, (mod, pip) in deps.items():
        status[key] = ensure_module(mod, pip)
    return status


if __name__ == "__main__":
    print("=== 联邦投顾依赖自愈检查 ===")
    status = ensure_all()
    for k, v in status.items():
        print(f"  {'✅' if v else '❌'} {k}: {'OK' if v else '安装失败'}")
    all_ok = all(status.values())
    print(f"\n{'✅ 全部依赖就绪' if all_ok else '❌ 存在失败依赖'}")
