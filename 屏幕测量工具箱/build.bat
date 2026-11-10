@echo off
chcp 65001 > nul
echo ================================================
echo  屏幕测量工具箱 · PyInstaller 打包脚本
echo ================================================

:: 1. 检查 PyInstaller
python -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo [提示] 未检测到 PyInstaller，正在安装...
    python -m pip install pyinstaller
)

:: 2. 检查 PySide6
python -c "import PySide6" 2>nul
if %errorlevel% neq 0 (
    echo [提示] 未检测到 PySide6，正在安装...
    python -m pip install PySide6
)

:: 3. 打包
echo.
echo [打包] 开始构建单文件可执行程序...
python -m PyInstaller ^
    --name "屏幕测量工具箱" ^
    --onefile ^
    --windowed ^
    --clean ^
    --noconfirm ^
    --hidden-import "PySide6.QtSvg" ^
    --exclude-module "PySide6.QtWebEngineWidgets" ^
    --exclude-module "PySide6.QtWebEngineCore" ^
    --exclude-module "PySide6.QtWebChannel" ^
    screen_measure.py

if %errorlevel% neq 0 (
    echo [错误] 打包失败！
    pause
    exit /b 1
)

:: 4. 检查产物
if not exist "dist\屏幕测量工具箱.exe" (
    echo [错误] 产物未生成，检查 dist\ 目录
    pause
    exit /b 1
)

echo.
echo ================================================
echo  打包成功！
echo  输出文件：dist\屏幕测量工具箱.exe
echo ================================================
echo.
echo  使用方法：
echo    1. 把 dist\屏幕测量工具箱.exe 复制到任意目录
echo    2. 双击运行即可（无需 Python 环境）
echo    3. 校准配置 screen_measure_config.json 会生成在 exe 同目录
echo.

pause