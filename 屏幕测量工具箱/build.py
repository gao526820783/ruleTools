#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
屏幕测量工具箱 · PyInstaller 打包脚本（跨平台）

用法：
    python build.py            # 打包单文件可执行程序
    python build.py --clean    # 先清理 build/ dist/ 再打包

产物：dist/屏幕测量工具箱(.exe)
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "screen_measure.py")
APP_NAME = "屏幕测量工具箱"


def ensure(pkg, install_name=None):
    """确保依赖已安装，缺失则通过 pip 安装。"""
    try:
        __import__(pkg)
    except ImportError:
        print(f"[提示] 未检测到 {pkg}，正在安装...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", install_name or pkg]
        )


def clean():
    """清理构建残留。"""
    for d in ("build", "dist", f"{APP_NAME}.spec"):
        p = os.path.join(HERE, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            print(f"[清理] 已删除 {d}/")
        elif os.path.isfile(p):
            os.remove(p)
            print(f"[清理] 已删除 {d}")


def build():
    ensure("PyInstaller")
    ensure("PySide6")

    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        # 显式引入 SVG 支持（部分图标/渲染需要）
        "--hidden-import", "PySide6.QtSvg",
        # 排除体积巨大的 WebEngine（本程序用不到）
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebChannel",
        ENTRY,
    ]
    print("[打包]", " ".join(args))
    subprocess.check_call(args, cwd=HERE)

    ext = ".exe" if os.name == "nt" else ""
    out = os.path.join(HERE, "dist", APP_NAME + ext)
    if not os.path.exists(out):
        print("[错误] 产物未生成")
        return 1

    size_mb = os.path.getsize(out) / 1024 / 1024
    print()
    print("=" * 48)
    print(f" 打包成功：{out}")
    print(f" 大小：{size_mb:.1f} MB")
    print("=" * 48)
    print(" 双击即可运行（无需 Python 环境）。")
    print(" 校准配置 screen_measure_config.json 生成于 exe 同目录。")
    return 0


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
    sys.exit(build())