@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ###############################################################################
REM FastAPI Backend — 一键管理脚本 (Windows 版)
REM
REM 用法：
REM   交互模式：  scripts\manage.bat
REM   命令模式：  scripts\manage.bat <command> [args]
REM
REM 示例：
REM   scripts\manage.bat init           初始化环境 + 安装依赖
REM   scripts\manage.bat module users   创建新模块
REM   scripts\manage.bat migrate        数据库迁移
REM   scripts\manage.bat tunnel         MySQL SSH 隧道
REM   scripts\manage.bat help           查看所有命令
REM ###############################################################################

REM 统一 Conda 环境名称
set "DEFAULT_CONDA_ENV=fastapi_env"

REM 切换到项目根目录
cd /d "%~dp0\.."
set "PROJECT_DIR=%cd%"

REM 解析命令行参数
set "ACTION=%~1"
set "ARG2=%~2"

if "%ACTION%"=="" goto :main_menu
if /I "%ACTION%"=="help"      goto :show_help
if /I "%ACTION%"=="-h"        goto :show_help
if /I "%ACTION%"=="init"      goto :do_init
if /I "%ACTION%"=="init-env"  goto :do_init_env
if /I "%ACTION%"=="init-proj" goto :do_init_proj
if /I "%ACTION%"=="module"    goto :do_module
if /I "%ACTION%"=="migrate"   goto :do_migrate
if /I "%ACTION%"=="tunnel"    goto :do_tunnel
if /I "%ACTION%"=="port"      goto :do_port_check
if /I "%ACTION%"=="sysinfo"   goto :do_sysinfo
if /I "%ACTION%"=="backup"    goto :do_backup
if /I "%ACTION%"=="clean"     goto :do_clean_logs

echo [ERROR] 未知命令: %ACTION%
echo 运行 scripts\manage.bat help 查看帮助
exit /b 1


REM ############################################################################
REM                           主菜单
REM ############################################################################

:main_menu
cls
echo.
echo   ╔═══════════════════════════════════════════════════╗
echo   ║       FastAPI Backend 管理中心 (Windows)          ║
echo   ╚═══════════════════════════════════════════════════╝
echo.
echo   项目: %PROJECT_DIR%

REM 检测当前环境
set "ENV_INFO=未检测到"
if defined CONDA_DEFAULT_ENV (
    if not "%CONDA_DEFAULT_ENV%"=="base" (
        set "ENV_INFO=Conda (%CONDA_DEFAULT_ENV%)"
    )
)
if defined VIRTUAL_ENV (
    for %%I in ("%VIRTUAL_ENV%") do set "ENV_INFO=venv (%%~nxI)"
)
echo   环境: !ENV_INFO!
echo.

echo   ──────────────────────────────────────────────────
echo   环境初始化
echo   ──────────────────────────────────────────────────
echo    1)  初始化 Conda 环境 + 安装依赖
echo    2)  初始化项目（目录 + 数据库迁移）
echo    3)  创建新业务模块（模型/Schema/CRUD/API）
echo.
echo   ──────────────────────────────────────────────────
echo   开发工具
echo   ──────────────────────────────────────────────────
echo    4)  数据库迁移管理
echo    5)  MySQL SSH 隧道
echo    6)  查看端口占用
echo.
echo   ──────────────────────────────────────────────────
echo   运维工具
echo   ──────────────────────────────────────────────────
echo    7)  系统信息
echo    8)  清理日志文件
echo    9)  备份项目配置
echo.
echo    0)  退出
echo.

set /p "MENU_CHOICE=  请选择 [0-9]: "

if "%MENU_CHOICE%"=="1" goto :do_init_env
if "%MENU_CHOICE%"=="2" goto :do_init_proj
if "%MENU_CHOICE%"=="3" goto :do_module
if "%MENU_CHOICE%"=="4" goto :do_migrate
if "%MENU_CHOICE%"=="5" goto :do_tunnel
if "%MENU_CHOICE%"=="6" goto :do_port_check
if "%MENU_CHOICE%"=="7" goto :do_sysinfo
if "%MENU_CHOICE%"=="8" goto :do_clean_logs
if "%MENU_CHOICE%"=="9" goto :do_backup
if "%MENU_CHOICE%"=="0" goto :exit_script
if /I "%MENU_CHOICE%"=="q" goto :exit_script

echo [!] 无效选择
timeout /t 1 /nobreak >nul
goto :main_menu


REM ############################################################################
REM                       1. 初始化 Conda 环境
REM ############################################################################

:do_init_env
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   🐍 初始化 Conda 环境
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

where conda >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未检测到 conda！请先安装 Miniconda/Anaconda
    echo.
    echo 下载地址: https://docs.conda.io/en/latest/miniconda.html
    goto :return_menu
)

set /p "ENV_NAME=Conda 环境名称 [%DEFAULT_CONDA_ENV%]: "
if "%ENV_NAME%"=="" set "ENV_NAME=%DEFAULT_CONDA_ENV%"

set /p "PY_VER=Python 版本 [3.10]: "
if "%PY_VER%"=="" set "PY_VER=3.10"

REM 检查环境是否已存在
conda env list 2>nul | findstr /B "%ENV_NAME% " >nul 2>&1
if %errorlevel%==0 (
    echo [!] Conda 环境 '%ENV_NAME%' 已存在
    set /p "OVERWRITE=是否删除并重新创建？(y/N): "
    if /I "!OVERWRITE!"=="y" (
        echo [INFO] 删除现有环境...
        call conda env remove -n %ENV_NAME% -y
    ) else (
        echo [INFO] 使用现有环境
        goto :install_deps
    )
)

echo [INFO] 创建 Conda 环境: %ENV_NAME% (Python %PY_VER%)...
call conda create -n %ENV_NAME% python=%PY_VER% -y
if %errorlevel% neq 0 (
    echo [ERROR] 环境创建失败！
    goto :return_menu
)
echo [√] Conda 环境创建成功

:install_deps
echo [INFO] 激活环境...
call conda activate %ENV_NAME%

echo [INFO] 安装项目依赖...
pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
if %errorlevel% neq 0 pip install --upgrade pip >nul 2>&1

pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo [!] 清华镜像不可用，使用官方源...
    pip install -r requirements.txt
)

echo.
echo [√] 环境初始化完成！
echo [INFO] 激活命令: conda activate %ENV_NAME%
goto :return_menu


REM ############################################################################
REM                       2. 初始化项目
REM ############################################################################

:do_init_proj
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   📦 项目初始化
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

echo [INFO] 创建项目目录...
if not exist "logs" mkdir logs
if not exist "uploads" mkdir uploads
if not exist "alembic\versions" mkdir alembic\versions
echo [√] 目录创建完成

if not exist "config\settings.toml" (
    echo [ERROR] 配置文件 config\settings.toml 不存在！
    goto :return_menu
)
echo [√] 配置文件检查通过

echo [INFO] 测试数据库连接...
set "PYTHONPATH=%PROJECT_DIR%;%PYTHONPATH%"
python -c "from app.core.database import init_db; init_db()" >nul 2>&1
if %errorlevel%==0 (
    echo [√] 数据库连接成功
    echo [INFO] 应用数据库迁移...
    alembic upgrade head >nul 2>&1
    echo [√] 数据库迁移完成
) else (
    echo [!] 数据库连接失败，请检查 config\settings.toml 中的数据库配置
)

echo.
echo [√] 项目初始化完成！
goto :return_menu


REM ############################################################################
REM                       完整初始化
REM ############################################################################

:do_init
call :do_init_env
call :do_init_proj
goto :return_menu


REM ############################################################################
REM                       3. 创建新模块
REM ############################################################################

:do_module
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   🧩 创建新业务模块
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set "MODULE_NAME=%ARG2%"
if "%MODULE_NAME%"=="" (
    set /p "MODULE_NAME=请输入模块名称（英文小写，如 products）: "
)
if "%MODULE_NAME%"=="" (
    echo [ERROR] 模块名称不能为空
    goto :return_menu
)

REM 首字母大写
set "FIRST_CHAR=%MODULE_NAME:~0,1%"
set "REST_CHARS=%MODULE_NAME:~1%"
for %%A in (A B C D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    set "FIRST_CHAR=!FIRST_CHAR:%%A=%%A!"
)
REM 简化处理：用 Python 生成首字母大写
for /f %%C in ('python -c "print('%MODULE_NAME%'.capitalize())"') do set "CLASS_NAME=%%C"

echo [INFO] 创建模块: %MODULE_NAME% (类名: %CLASS_NAME%)

REM 创建 Model
echo [INFO] 创建 Model...
(
echo """%MODULE_NAME% 模型"""
echo from sqlalchemy import String
echo from sqlalchemy.orm import Mapped, mapped_column
echo.
echo from app.models.base import BaseModel
echo.
echo.
echo class %CLASS_NAME%^(BaseModel^):
echo     """%MODULE_NAME% 模型"""
echo     __tablename__ = "%MODULE_NAME%"
echo     __table_args__ = {"comment": "%MODULE_NAME% 表"}
echo.
echo     name: Mapped[str] = mapped_column^(String^(100^), nullable=False, comment="名称"^)
echo     description: Mapped[str ^| None] = mapped_column^(String^(500^), nullable=True, comment="描述"^)
) > "app\models\%MODULE_NAME%.py"

REM 创建 Schema
echo [INFO] 创建 Schema...
(
echo """%MODULE_NAME% Pydantic schemas"""
echo from datetime import datetime
echo from typing import Optional
echo from pydantic import BaseModel, Field, ConfigDict
echo.
echo.
echo class %CLASS_NAME%Base^(BaseModel^):
echo     """%MODULE_NAME% 基础信息"""
echo     name: str = Field^(..., max_length=100, description="名称"^)
echo     description: Optional[str] = Field^(None, max_length=500, description="描述"^)
echo.
echo.
echo class %CLASS_NAME%Create^(%CLASS_NAME%Base^):
echo     """创建 %MODULE_NAME%"""
echo     pass
echo.
echo.
echo class %CLASS_NAME%Update^(BaseModel^):
echo     """更新 %MODULE_NAME%"""
echo     name: Optional[str] = Field^(None, max_length=100, description="名称"^)
echo     description: Optional[str] = Field^(None, max_length=500, description="描述"^)
echo.
echo.
echo class %CLASS_NAME%Response^(%CLASS_NAME%Base^):
echo     """%MODULE_NAME% 响应"""
echo     model_config = ConfigDict^(from_attributes=True^)
echo     id: int
echo     created_at: datetime
echo     updated_at: datetime
) > "app\schemas\%MODULE_NAME%.py"

REM 创建 CRUD
echo [INFO] 创建 CRUD...
(
echo """%MODULE_NAME% CRUD 操作"""
echo from app.crud.base import CRUDBase
echo from app.models.%MODULE_NAME% import %CLASS_NAME%
echo from app.schemas.%MODULE_NAME% import %CLASS_NAME%Create, %CLASS_NAME%Update
echo.
echo.
echo class CRUD%CLASS_NAME%^(CRUDBase[%CLASS_NAME%, %CLASS_NAME%Create, %CLASS_NAME%Update]^):
echo     """%MODULE_NAME% CRUD"""
echo     pass
echo.
echo.
echo %MODULE_NAME% = CRUD%CLASS_NAME%^(%CLASS_NAME%^)
) > "app\crud\%MODULE_NAME%.py"

REM 创建 API
echo [INFO] 创建 API Endpoint...
(
echo """%MODULE_NAME% API"""
echo from typing import Any
echo from fastapi import APIRouter, Depends, Query
echo from sqlalchemy.ext.asyncio import AsyncSession
echo.
echo from app.core.database import get_async_db
echo from app.api.deps import get_current_user
echo from app.crud import %MODULE_NAME% as %MODULE_NAME%_crud
echo from app.schemas.%MODULE_NAME% import %CLASS_NAME%Create, %CLASS_NAME%Update, %CLASS_NAME%Response
echo from app.schemas.response import Response, PaginatedData, PaginatedResponse
echo.
echo router = APIRouter^(^)
echo.
echo.
echo @router.get^("/", response_model=PaginatedResponse[%CLASS_NAME%Response], summary="获取%MODULE_NAME%列表"^)
echo async def list_%MODULE_NAME%s^(
echo     page: int = Query^(1, ge=1^),
echo     page_size: int = Query^(20, ge=1, le=100^),
echo     db: AsyncSession = Depends^(get_async_db^),
echo     current_user=Depends^(get_current_user^),
echo ^) -^> Any:
echo     items, total = await %MODULE_NAME%_crud.get_multi_paginated^(db, page=page, page_size=page_size^)
echo     return Response^(data=PaginatedData.create^(items=items, total=total, page=page, page_size=page_size^)^)
) > "app\api\v1\endpoints\%MODULE_NAME%.py"

echo.
echo [√] 模块 %MODULE_NAME% 创建完成！
echo.
echo [!] 下一步：
echo     1. 在 app\models\__init__.py 中导入新模型
echo     2. 在 app\schemas\__init__.py 中导入新 schema
echo     3. 在 app\crud\__init__.py 中导入新 CRUD
echo     4. 在 app\api\v1\router.py 中注册路由
echo     5. 运行迁移: alembic revision --autogenerate -m "添加 %MODULE_NAME%"
echo                   alembic upgrade head
goto :return_menu


REM ############################################################################
REM                       4. 数据库迁移
REM ############################################################################

:do_migrate
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   🗄️ 数据库迁移管理
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo    1)  升级到最新版本 (upgrade head)
echo    2)  回滚一个版本 (downgrade -1)
echo    3)  生成新迁移
echo    4)  查看迁移历史
echo    5)  查看当前版本
echo.

set "PYTHONPATH=%PROJECT_DIR%;%PYTHONPATH%"
set /p "DB_CHOICE=请选择 [1-5]: "

if "%DB_CHOICE%"=="1" (
    alembic upgrade head
    echo [√] 迁移完成
)
if "%DB_CHOICE%"=="2" (
    alembic downgrade -1
    echo [√] 回滚完成
)
if "%DB_CHOICE%"=="3" (
    set /p "MIGRATE_MSG=迁移描述: "
    if "!MIGRATE_MSG!"=="" set "MIGRATE_MSG=update"
    alembic revision --autogenerate -m "!MIGRATE_MSG!"
    echo [√] 迁移脚本已生成
)
if "%DB_CHOICE%"=="4" alembic history --verbose
if "%DB_CHOICE%"=="5" alembic current
goto :return_menu


REM ############################################################################
REM                       5. MySQL SSH 隧道
REM ############################################################################

:do_tunnel
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   🔗 MySQL SSH 隧道
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set "SSH_ALIAS=ali99"
set "LOCAL_PORT=3307"
set "REMOTE_HOST=127.0.0.1"
set "REMOTE_PORT=3306"

set /p "SSH_ALIAS=SSH 别名 [%SSH_ALIAS%]: "
set /p "LOCAL_PORT=本地端口 [%LOCAL_PORT%]: "
set /p "REMOTE_HOST=远程 MySQL 地址 [%REMOTE_HOST%]: "
set /p "REMOTE_PORT=远程 MySQL 端口 [%REMOTE_PORT%]: "

echo.
echo [INFO] 映射: 本地 127.0.0.1:%LOCAL_PORT% → 远程 %REMOTE_HOST%:%REMOTE_PORT%
echo [INFO] SSH 别名: %SSH_ALIAS%
echo [INFO] 按 Ctrl+C 断开隧道
echo.

ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -N -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% %SSH_ALIAS%
goto :return_menu


REM ############################################################################
REM                       6. 端口检查
REM ############################################################################

:do_port_check
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   📡 端口占用检查
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set "CHECK_PORT=%ARG2%"
if "%CHECK_PORT%"=="" (
    set /p "CHECK_PORT=请输入端口号（留空查看全部监听端口）: "
)

if "%CHECK_PORT%"=="" (
    echo.
    echo [INFO] 所有监听端口：
    netstat -ano | findstr "LISTENING"
) else (
    echo.
    echo [INFO] 端口 %CHECK_PORT% 状态：
    netstat -ano | findstr ":%CHECK_PORT% " | findstr "LISTENING"
    if !errorlevel! neq 0 (
        echo   端口 %CHECK_PORT% 无监听进程
    )
)
goto :return_menu


REM ############################################################################
REM                       7. 系统信息
REM ############################################################################

:do_sysinfo
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   📊 系统信息
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

echo.
echo --- 操作系统 ---
systeminfo | findstr /C:"OS" | findstr /V "BIOS"

echo.
echo --- CPU ---
wmic cpu get Name,NumberOfCores,NumberOfLogicalProcessors /format:list 2>nul | findstr /V "^$"

echo.
echo --- 内存 ---
for /f "skip=1 tokens=*" %%M in ('wmic os get TotalVisibleMemorySize /value 2^>nul') do (
    for /f "tokens=2 delims==" %%V in ("%%M") do (
        set /a "MEM_GB=%%V/1024/1024"
        echo   总内存: !MEM_GB! GB
    )
)
for /f "skip=1 tokens=*" %%M in ('wmic os get FreePhysicalMemory /value 2^>nul') do (
    for /f "tokens=2 delims==" %%V in ("%%M") do (
        set /a "FREE_GB=%%V/1024/1024"
        echo   可用内存: !FREE_GB! GB
    )
)

echo.
echo --- 磁盘 ---
wmic logicaldisk where DriveType=3 get DeviceID,Size,FreeSpace /format:list 2>nul | findstr /V "^$"

echo.
echo --- Python 环境 ---
python --version 2>nul || echo   Python 未找到
pip --version 2>nul || echo   pip 未找到
if defined CONDA_DEFAULT_ENV echo   Conda 环境: %CONDA_DEFAULT_ENV%
goto :return_menu


REM ############################################################################
REM                       8. 清理日志
REM ############################################################################

:do_clean_logs
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   🧹 清理日志文件
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if exist "logs" (
    echo [INFO] 当前日志文件：
    dir /B /S logs\*.log* 2>nul
    echo.

    set /p "KEEP_DAYS=保留最近几天的日志？[7]: "
    if "!KEEP_DAYS!"=="" set "KEEP_DAYS=7"

    echo [INFO] 删除 !KEEP_DAYS! 天前的日志...
    forfiles /p "logs" /s /m *.log* /d -!KEEP_DAYS! /c "cmd /c del @path" 2>nul
    echo [√] 日志清理完成
) else (
    echo [INFO] 日志目录不存在
)
goto :return_menu


REM ############################################################################
REM                       9. 备份配置
REM ############################################################################

:do_backup
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   💾 备份项目配置
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if not exist "backups" mkdir backups

for /f "tokens=2 delims==" %%A in ('wmic os get LocalDateTime /value 2^>nul ^| find "="') do (
    set "DT=%%A"
)
set "TIMESTAMP=%DT:~0,8%_%DT:~8,6%"
set "BACKUP_DIR=backups\config_backup_%TIMESTAMP%"

mkdir "%BACKUP_DIR%" 2>nul
xcopy /E /I /Q "config" "%BACKUP_DIR%\config" >nul 2>&1
if exist ".env" copy ".env" "%BACKUP_DIR%\" >nul 2>&1
if exist ".env.prod" copy ".env.prod" "%BACKUP_DIR%\" >nul 2>&1
if exist "alembic.ini" copy "alembic.ini" "%BACKUP_DIR%\" >nul 2>&1

echo [√] 备份完成: %BACKUP_DIR%
dir /S /B "%BACKUP_DIR%"
goto :return_menu


REM ############################################################################
REM                       帮助信息
REM ############################################################################

:show_help
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   FastAPI Backend 管理中心 (Windows)
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo 用法: scripts\manage.bat [command] [args]
echo.
echo 环境初始化:
echo   init          完整初始化（Conda + 项目）
echo   init-env      仅初始化 Conda 环境
echo   init-proj     仅初始化项目（目录+数据库）
echo   module ^<name^> 创建新业务模块
echo.
echo 开发工具:
echo   migrate       数据库迁移管理
echo   tunnel        MySQL SSH 隧道
echo   port [N]      查看端口占用
echo.
echo 运维工具:
echo   sysinfo       系统信息
echo   clean         清理日志文件
echo   backup        备份配置文件
echo.
echo 不带参数运行进入交互式菜单
goto :eof


REM ############################################################################
REM                       公共函数
REM ############################################################################

:return_menu
echo.
if "%ACTION%"=="" (
    pause
    goto :main_menu
)
goto :eof

:exit_script
echo.
echo [√] 再见！
endlocal
exit /b 0
