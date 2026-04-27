#!/bin/bash
###############################################################################
# FastAPI Backend — 一键运维管理脚本
#
# 整合了项目初始化、部署、运维等全部功能，通过交互式菜单或命令行参数使用
#
# 用法：
#   交互模式：  ./scripts/manage.sh
#   命令模式：  ./scripts/manage.sh <command> [args]
#
# 示例：
#   ./scripts/manage.sh deploy          # 部署 systemd 服务
#   ./scripts/manage.sh init            # 初始化项目环境
#   ./scripts/manage.sh module users    # 创建新模块
#   ./scripts/manage.sh status          # 查看服务状态
###############################################################################

set -euo pipefail

# 强制使用 bash
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

# ==================== 全局变量 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="fastapi-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TIMER_FILE="/etc/systemd/system/${SERVICE_NAME}.timer"

# 加载公共环境配置
if [ -f "${SCRIPT_DIR}/_env.sh" ]; then
    source "${SCRIPT_DIR}/_env.sh"
fi
DEFAULT_CONDA_ENV="${DEFAULT_CONDA_ENV:-fastapi_env}"

# ==================== 颜色定义 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ==================== 打印函数 ====================
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN} [✓]${NC} $1"; }
warn()    { echo -e "${YELLOW} [!]${NC} $1"; }
error()   { echo -e "${RED} [✗]${NC} $1"; }

header() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

divider() {
    echo -e "${DIM}──────────────────────────────────────────────────────────${NC}"
}

# 检查命令是否存在
cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

# 检查是否 root
require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        error "此操作需要 root 权限！请使用: sudo $0 $1"
        exit 1
    fi
}

# 切换到项目根目录
cd "${PROJECT_DIR}"


###############################################################################
#                         1. 环境初始化
###############################################################################

# 检测 Python 环境
detect_python_env() {
    if [ -n "${CONDA_PREFIX:-}" ] && [ "${CONDA_DEFAULT_ENV:-base}" != "base" ]; then
        PYTHON_BIN="${CONDA_PREFIX}/bin"
        ENV_TYPE="conda"
        ENV_NAME="${CONDA_DEFAULT_ENV}"
    elif [ -d "${PROJECT_DIR}/venv" ]; then
        PYTHON_BIN="${PROJECT_DIR}/venv/bin"
        ENV_TYPE="venv"
        ENV_NAME="venv"
    else
        # 尝试从 _env.sh 推断 Conda 路径
        local conda_prefix="/opt/miniconda3/envs/${DEFAULT_CONDA_ENV}"
        if [ -d "${conda_prefix}" ]; then
            PYTHON_BIN="${conda_prefix}/bin"
            ENV_TYPE="conda"
            ENV_NAME="${DEFAULT_CONDA_ENV}"
            CONDA_PREFIX="${conda_prefix}"
        else
            PYTHON_BIN="/usr/bin"
            ENV_TYPE="system"
            ENV_NAME="系统 Python"
        fi
    fi
}

# 初始化 Conda 环境
init_conda_env() {
    header "🐍 初始化 Conda 环境"

    if ! cmd_exists conda; then
        error "未检测到 conda！请先安装 Miniconda/Anaconda"
        echo ""
        info "快速安装 Miniconda："
        echo -e "  ${GREEN}wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh${NC}"
        echo -e "  ${GREEN}bash Miniconda3-latest-Linux-x86_64.sh${NC}"
        return 1
    fi

    local env_name="${DEFAULT_CONDA_ENV}"
    local python_version="3.10"

    read -rp "Conda 环境名称 [${env_name}]: " input_name
    env_name="${input_name:-$env_name}"

    read -rp "Python 版本 [${python_version}]: " input_ver
    python_version="${input_ver:-$python_version}"

    # 检查是否已存在
    if conda env list 2>/dev/null | grep -q "^${env_name} "; then
        warn "Conda 环境 '${env_name}' 已存在"
        read -rp "是否删除并重新创建？(y/N): " -n 1
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            info "删除现有环境..."
            conda env remove -n "${env_name}" -y
        else
            info "使用现有环境"
            return 0
        fi
    fi

    # 尝试自动接受 conda ToS
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main >/dev/null 2>&1 || true

    info "创建 Conda 环境: ${env_name} (Python ${python_version})..."
    conda create -n "${env_name}" python="${python_version}" -y

    success "Conda 环境创建成功"

    # 激活并安装依赖
    info "激活环境并安装依赖..."
    eval "$(conda shell.bash hook)"
    conda activate "${env_name}"

    info "安装项目依赖（清华镜像）..."
    pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || pip install --upgrade pip
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || pip install -r requirements.txt

    success "环境初始化完成"
    echo ""
    info "激活命令: conda activate ${env_name}"
}

# 创建目录和初始化数据库
init_project() {
    header "📦 项目初始化"

    # 创建目录
    info "创建项目目录..."
    mkdir -p logs uploads alembic/versions
    success "目录创建完成"

    # 检查配置
    if [ ! -f "config/settings.toml" ]; then
        error "配置文件 config/settings.toml 不存在！"
        return 1
    fi
    success "配置文件检查通过"

    # 数据库初始化
    info "测试数据库连接..."
    export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}"

    if python3 -c "from app.core.database import init_db; init_db()" 2>/dev/null; then
        success "数据库连接成功"

        if [ -d "alembic/versions" ] && [ -z "$(ls -A alembic/versions 2>/dev/null | grep -v __pycache__)" ]; then
            info "创建初始数据库迁移..."
            alembic revision --autogenerate -m "Initial migration"
            alembic upgrade head
            success "数据库迁移完成"
        else
            info "应用数据库迁移..."
            alembic upgrade head
            success "数据库迁移完成"
        fi
    else
        warn "数据库连接失败，请检查 config/settings.toml 中的数据库配置"
    fi

    success "项目初始化完成！"
}


###############################################################################
#                         2. 模块生成器
###############################################################################

create_module() {
    local module_name="${1:-}"

    if [ -z "${module_name}" ]; then
        read -rp "请输入模块名称（英文小写，如 products）: " module_name
    fi

    if [ -z "${module_name}" ]; then
        error "模块名称不能为空"
        return 1
    fi

    header "🧩 创建模块: ${module_name}"

    # 检查是否已存在
    if [ -f "app/models/${module_name}.py" ]; then
        warn "模块 ${module_name} 已存在！"
        read -rp "是否覆盖？(y/N): " -n 1
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            return 0
        fi
    fi

    # 创建模型
    info "创建 Model..."
    cat > "app/models/${module_name}.py" << PYEOF
"""${module_name} 模型"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ${module_name^}(BaseModel):
    """${module_name} 模型"""
    __tablename__ = "${module_name}"
    __table_args__ = {"comment": "${module_name} 表"}

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="名称")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="描述")
PYEOF

    # 创建 Schema
    info "创建 Schema..."
    cat > "app/schemas/${module_name}.py" << PYEOF
"""${module_name} Pydantic schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class ${module_name^}Base(BaseModel):
    """${module_name} 基础信息"""
    name: str = Field(..., max_length=100, description="名称")
    description: Optional[str] = Field(None, max_length=500, description="描述")


class ${module_name^}Create(${module_name^}Base):
    """创建 ${module_name}"""
    pass


class ${module_name^}Update(BaseModel):
    """更新 ${module_name}"""
    name: Optional[str] = Field(None, max_length=100, description="名称")
    description: Optional[str] = Field(None, max_length=500, description="描述")


class ${module_name^}Response(${module_name^}Base):
    """${module_name} 响应"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
PYEOF

    # 创建 CRUD
    info "创建 CRUD..."
    cat > "app/crud/${module_name}.py" << PYEOF
"""${module_name} CRUD 操作"""
from app.crud.base import CRUDBase
from app.models.${module_name} import ${module_name^}
from app.schemas.${module_name} import ${module_name^}Create, ${module_name^}Update


class CRUD${module_name^}(CRUDBase[${module_name^}, ${module_name^}Create, ${module_name^}Update]):
    """${module_name} CRUD"""
    pass


${module_name} = CRUD${module_name^}(${module_name^})
PYEOF

    # 创建 API 端点
    info "创建 API Endpoint..."
    cat > "app/api/v1/endpoints/${module_name}.py" << PYEOF
"""${module_name} API"""
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.api.deps import get_current_user
from app.crud import ${module_name} as ${module_name}_crud
from app.schemas.${module_name} import ${module_name^}Create, ${module_name^}Update, ${module_name^}Response
from app.schemas.response import Response, PaginatedData, PaginatedResponse

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[${module_name^}Response], summary="获取${module_name}列表")
async def list_${module_name}s(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Any:
    items, total = await ${module_name}_crud.get_multi_paginated(
        db, page=page, page_size=page_size
    )
    return Response(data=PaginatedData.create(items=items, total=total, page=page, page_size=page_size))


@router.post("/", response_model=Response[${module_name^}Response], summary="创建${module_name}")
async def create_${module_name}(
    obj_in: ${module_name^}Create,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Any:
    obj = await ${module_name}_crud.create(db, obj_in=obj_in)
    return Response(code=201, message="创建成功", data=obj)


@router.get("/{item_id}", response_model=Response[${module_name^}Response], summary="获取${module_name}详情")
async def get_${module_name}(
    item_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Any:
    from app.core.exceptions import NotFoundError
    obj = await ${module_name}_crud.get(db, id=item_id)
    if not obj:
        raise NotFoundError("${module_name} 不存在")
    return Response(data=obj)


@router.put("/{item_id}", response_model=Response[${module_name^}Response], summary="更新${module_name}")
async def update_${module_name}(
    item_id: int,
    obj_in: ${module_name^}Update,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Any:
    from app.core.exceptions import NotFoundError
    obj = await ${module_name}_crud.get(db, id=item_id)
    if not obj:
        raise NotFoundError("${module_name} 不存在")
    obj = await ${module_name}_crud.update(db, db_obj=obj, obj_in=obj_in)
    return Response(message="更新成功", data=obj)


@router.delete("/{item_id}", response_model=Response, summary="删除${module_name}")
async def delete_${module_name}(
    item_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Any:
    from app.core.exceptions import NotFoundError
    obj = await ${module_name}_crud.get(db, id=item_id)
    if not obj:
        raise NotFoundError("${module_name} 不存在")
    await ${module_name}_crud.delete(db, id=item_id)
    return Response(message="删除成功")
PYEOF

    success "模块 ${module_name} 创建完成！"
    echo ""
    warn "下一步："
    echo "  1. 在 app/models/__init__.py 中导入新模型"
    echo "  2. 在 app/schemas/__init__.py 中导入新 schema"
    echo "  3. 在 app/crud/__init__.py 中导入新 CRUD"
    echo "  4. 在 app/api/v1/router.py 中注册路由"
    echo "  5. 运行迁移: alembic revision --autogenerate -m '添加 ${module_name}'"
    echo "               alembic upgrade head"
}


###############################################################################
#                         3. systemd 部署
###############################################################################

deploy_service() {
    header "🚀 部署 systemd 服务"
    require_root "deploy"

    detect_python_env
    info "项目目录: ${PROJECT_DIR}"
    info "部署用户: $(logname 2>/dev/null || echo $SUDO_USER)"
    info "Python:   ${ENV_TYPE} (${ENV_NAME}) → ${PYTHON_BIN}"

    local deploy_user
    deploy_user="$(logname 2>/dev/null || echo ${SUDO_USER:-root})"
    local deploy_group
    deploy_group="$(id -gn "${deploy_user}" 2>/dev/null || echo "${deploy_user}")"

    # 从 settings.toml 读取端口
    local port=8999
    if [ -f "${PROJECT_DIR}/config/settings.toml" ]; then
        local tp
        tp=$(grep -E '^port\s*=' "${PROJECT_DIR}/config/settings.toml" | head -1 | sed 's/.*=\s*//' | tr -d ' ')
        [ -n "${tp}" ] && port="${tp}"
    fi
    info "服务端口: ${port}"

    # 检查 uvicorn
    if [ ! -f "${PYTHON_BIN}/uvicorn" ]; then
        error "未找到 uvicorn (${PYTHON_BIN}/uvicorn)"
        error "请先安装: pip install -r requirements.txt"
        return 1
    fi

    # 创建必要目录
    mkdir -p "${PROJECT_DIR}/logs" "${PROJECT_DIR}/uploads"
    chown -R "${deploy_user}:${deploy_group}" "${PROJECT_DIR}/logs" "${PROJECT_DIR}/uploads"

    # 生成 service 文件
    info "生成 ${SERVICE_FILE}..."
    cat > "${SERVICE_FILE}" << EOF
# 由 manage.sh 自动生成 — $(date '+%Y-%m-%d %H:%M:%S')
[Unit]
Description=FastAPI Backend Service
After=network-online.target mysql.service redis.service
Wants=network-online.target

[Service]
User=${deploy_user}
Group=${deploy_group}
WorkingDirectory=${PROJECT_DIR}

Environment="PATH=${PYTHON_BIN}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
Environment="APP_ENV=prod"
EOF

    # Conda 变量
    if [ "${ENV_TYPE}" = "conda" ]; then
        cat >> "${SERVICE_FILE}" << EOF
Environment="CONDA_PREFIX=${CONDA_PREFIX:-}"
Environment="CONDA_DEFAULT_ENV=${ENV_NAME}"
EOF
    fi

    # EnvironmentFile
    if [ -f "${PROJECT_DIR}/.env.prod" ]; then
        echo "EnvironmentFile=${PROJECT_DIR}/.env.prod" >> "${SERVICE_FILE}"
        info "已配置 .env.prod 为环境变量源"
    elif [ -f "${PROJECT_DIR}/.env" ]; then
        echo "EnvironmentFile=${PROJECT_DIR}/.env" >> "${SERVICE_FILE}"
        info "已配置 .env 为环境变量源"
    else
        warn "未检测到 .env 文件，请确保已设置 SECRET_KEY 和 MYSQL_PASSWORD"
    fi

    cat >> "${SERVICE_FILE}" << EOF

ExecStartPre=/bin/mkdir -p ${PROJECT_DIR}/logs
ExecStartPre=/bin/mkdir -p ${PROJECT_DIR}/uploads

ExecStart=${PYTHON_BIN}/uvicorn app.main:app \\
    --host 0.0.0.0 \\
    --port ${port} \\
    --workers 2 \\
    --proxy-headers \\
    --forwarded-allow-ips="*" \\
    --access-log \\
    --log-level warning

KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5

LimitNOFILE=65535
LimitNPROC=4096

StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    success "service 文件已生成"

    # 重新加载并启用
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl start "${SERVICE_NAME}"
    sleep 2

    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        success "服务已启动并启用开机自启"
    else
        warn "服务可能未正常启动，请运行: sudo journalctl -u ${SERVICE_NAME} -n 50"
    fi
}

# 创建延时启动 Timer
setup_timer() {
    header "⏰ 配置延时启动 (systemd Timer)"
    require_root "timer"

    if [ ! -f "${SERVICE_FILE}" ]; then
        error "请先部署 service（选择菜单 3 或运行 sudo $0 deploy）"
        return 1
    fi

    echo ""
    info "设置开机后延迟多长时间启动 ${SERVICE_NAME}"
    echo ""
    echo -e "  ${DIM}示例: 30   → 开机后 30 秒启动${NC}"
    echo -e "  ${DIM}示例: 120  → 开机后  2 分钟启动${NC}"
    echo -e "  ${DIM}示例: 300  → 开机后  5 分钟启动${NC}"
    echo ""

    read -rp "请输入延迟秒数 [60]: " delay_sec
    delay_sec="${delay_sec:-60}"

    # 验证输入
    if ! [[ "${delay_sec}" =~ ^[0-9]+$ ]]; then
        error "请输入有效的数字"
        return 1
    fi

    # 先禁用 service 的直接自启（由 timer 接管）
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true

    # 生成 timer 文件
    info "生成 ${TIMER_FILE}..."
    cat > "${TIMER_FILE}" << EOF
# 由 manage.sh 自动生成 — $(date '+%Y-%m-%d %H:%M:%S')
# 开机后延迟 ${delay_sec} 秒启动 ${SERVICE_NAME}
[Unit]
Description=Delayed startup timer for FastAPI Backend
Documentation=file://${PROJECT_DIR}/README.md

[Timer]
# 开机后延迟指定时间启动
OnBootSec=${delay_sec}s
# 如果错过了触发时间（如系统休眠），立即执行
Persistent=true
# 关联的 service 单元
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

    # 启用 timer
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.timer"
    systemctl start "${SERVICE_NAME}.timer"

    success "延时启动 Timer 已配置"
    echo ""
    info "开机后将延迟 ${BOLD}${delay_sec} 秒${NC} 启动 ${SERVICE_NAME}"
    echo ""
    echo -e "  ${CYAN}查看 Timer 状态:${NC}  systemctl list-timers | grep ${SERVICE_NAME}"
    echo -e "  ${CYAN}取消延时启动:${NC}    sudo systemctl disable ${SERVICE_NAME}.timer"
    echo -e "  ${CYAN}改回直接自启:${NC}    sudo systemctl enable ${SERVICE_NAME}"
}

# 卸载服务
uninstall_service() {
    header "🗑️  卸载 systemd 服务"
    require_root "uninstall"

    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl stop "${SERVICE_NAME}.timer" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}.timer" 2>/dev/null || true
    rm -f "${SERVICE_FILE}" "${TIMER_FILE}"
    systemctl daemon-reload

    success "服务已完全卸载"
}


###############################################################################
#                         4. MySQL SSH 隧道
###############################################################################

mysql_tunnel() {
    header "🔗 MySQL SSH 隧道"

    local ssh_alias="ali99"
    local local_port="3307"
    local remote_host="127.0.0.1"
    local remote_port="3306"

    read -rp "SSH 别名 [${ssh_alias}]: " input
    ssh_alias="${input:-$ssh_alias}"

    read -rp "本地端口 [${local_port}]: " input
    local_port="${input:-$local_port}"

    read -rp "远程 MySQL 地址 [${remote_host}]: " input
    remote_host="${input:-$remote_host}"

    read -rp "远程 MySQL 端口 [${remote_port}]: " input
    remote_port="${input:-$remote_port}"

    echo ""
    info "映射: 本地 127.0.0.1:${local_port} → 远程 ${remote_host}:${remote_port}"
    info "SSH 别名: ${ssh_alias}"
    info "按 Ctrl+C 断开隧道"
    echo ""

    ssh -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -N -L "${local_port}:${remote_host}:${remote_port}" "${ssh_alias}"
}


###############################################################################
#                         5. 服务器运维工具
###############################################################################

ops_menu() {
    while true; do
        header "🔧 服务器运维工具箱"
        echo ""
        echo -e "  ${GREEN}1)${NC}  查看系统资源（CPU / 内存 / 磁盘）"
        echo -e "  ${GREEN}2)${NC}  查看端口占用"
        echo -e "  ${GREEN}3)${NC}  查看系统日志（最近错误）"
        echo -e "  ${GREEN}4)${NC}  清理日志文件"
        echo -e "  ${GREEN}5)${NC}  查看网络连接统计"
        echo -e "  ${GREEN}6)${NC}  查看进程 Top 10（内存占用）"
        echo -e "  ${GREEN}7)${NC}  测试端口连通性"
        echo -e "  ${GREEN}8)${NC}  数据库迁移管理"
        echo -e "  ${GREEN}9)${NC}  备份项目配置"
        echo -e "  ${GREEN}10)${NC} Nginx 配置检查 / 重载"
        echo ""
        echo -e "  ${DIM}0)  返回主菜单${NC}"
        echo ""
        read -rp "请选择 [0-10]: " ops_choice

        case "${ops_choice}" in
            1) ops_system_info ;;
            2) ops_port_check ;;
            3) ops_system_logs ;;
            4) ops_clean_logs ;;
            5) ops_network_stats ;;
            6) ops_top_processes ;;
            7) ops_connectivity_test ;;
            8) ops_db_migrate ;;
            9) ops_backup_config ;;
            10) ops_nginx ;;
            0|q|Q) return ;;
            *) warn "无效选择" ;;
        esac

        echo ""
        read -rp "按回车继续..." -s
    done
}

ops_system_info() {
    header "📊 系统资源概览"

    echo -e "\n${BOLD}CPU:${NC}"
    if cmd_exists nproc; then
        echo "  核心数: $(nproc)"
    fi
    if [ -f /proc/loadavg ]; then
        echo "  负载: $(cat /proc/loadavg | awk '{print $1, $2, $3}')"
    fi

    echo -e "\n${BOLD}内存:${NC}"
    free -h 2>/dev/null || echo "  free 命令不可用"

    echo -e "\n${BOLD}磁盘:${NC}"
    df -h / /home 2>/dev/null | head -5

    echo -e "\n${BOLD}运行时间:${NC}"
    uptime 2>/dev/null
}

ops_port_check() {
    local port="${1:-}"
    if [ -z "${port}" ]; then
        read -rp "请输入要检查的端口（留空查看全部监听端口）: " port
    fi

    if [ -z "${port}" ]; then
        header "📡 所有监听端口"
        ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null || warn "ss/netstat 均不可用"
    else
        header "📡 端口 ${port} 状态"
        ss -tlnp "sport = :${port}" 2>/dev/null || netstat -tlnp 2>/dev/null | grep ":${port}" || echo "  端口 ${port} 无监听进程"
    fi
}

ops_system_logs() {
    header "📋 最近系统错误日志"
    journalctl --priority=err --since="24 hours ago" --no-pager | tail -30 2>/dev/null || warn "journalctl 不可用"
}

ops_clean_logs() {
    header "🧹 清理日志文件"

    # 应用日志
    if [ -d "${PROJECT_DIR}/logs" ]; then
        local log_size
        log_size=$(du -sh "${PROJECT_DIR}/logs" 2>/dev/null | awk '{print $1}')
        info "当前应用日志大小: ${log_size}"

        read -rp "保留最近几天的日志？[7]: " keep_days
        keep_days="${keep_days:-7}"

        local deleted
        deleted=$(find "${PROJECT_DIR}/logs" -name "*.log*" -mtime "+${keep_days}" -type f -print -delete 2>/dev/null | wc -l)
        success "已清理 ${deleted} 个旧日志文件"
    fi

    # journald 日志
    if cmd_exists journalctl; then
        read -rp "是否也清理 journald 日志（保留最近 7 天）？(y/N): " -n 1
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo journalctl --vacuum-time=7d 2>/dev/null
            success "journald 日志已清理"
        fi
    fi
}

ops_network_stats() {
    header "🌐 网络连接统计"
    if cmd_exists ss; then
        echo -e "\n${BOLD}连接状态统计:${NC}"
        ss -s 2>/dev/null
        echo -e "\n${BOLD}TCP 连接状态分布:${NC}"
        ss -tan 2>/dev/null | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn
    else
        warn "ss 命令不可用"
    fi
}

ops_top_processes() {
    header "📈 内存占用 Top 10"
    ps aux --sort=-%mem 2>/dev/null | head -11 || warn "ps 命令不可用"
}

ops_connectivity_test() {
    read -rp "请输入要测试的地址 (host:port): " target
    if [ -z "${target}" ]; then
        warn "地址不能为空"
        return
    fi

    local host="${target%%:*}"
    local port="${target##*:}"

    if [ "${host}" = "${port}" ]; then
        read -rp "请输入端口号: " port
    fi

    header "🔍 测试 ${host}:${port}"

    # TCP 连通性
    if cmd_exists nc; then
        if nc -z -w 3 "${host}" "${port}" 2>/dev/null; then
            success "TCP 连接成功: ${host}:${port}"
        else
            error "TCP 连接失败: ${host}:${port}"
        fi
    elif cmd_exists timeout; then
        if timeout 3 bash -c "echo > /dev/tcp/${host}/${port}" 2>/dev/null; then
            success "TCP 连接成功: ${host}:${port}"
        else
            error "TCP 连接失败: ${host}:${port}"
        fi
    else
        warn "nc 和 timeout 均不可用，无法测试"
    fi

    # Ping
    info "Ping 延迟:"
    ping -c 3 -W 2 "${host}" 2>/dev/null || echo "  Ping 不可达或被防火墙拦截"
}

ops_db_migrate() {
    header "🗄️ 数据库迁移管理"

    echo ""
    echo -e "  ${GREEN}1)${NC}  升级到最新版本 (upgrade head)"
    echo -e "  ${GREEN}2)${NC}  回滚一个版本 (downgrade -1)"
    echo -e "  ${GREEN}3)${NC}  生成新迁移"
    echo -e "  ${GREEN}4)${NC}  查看迁移历史"
    echo -e "  ${GREEN}5)${NC}  查看当前版本"
    echo ""
    read -rp "请选择 [1-5]: " db_choice

    export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}"

    case "${db_choice}" in
        1) alembic upgrade head && success "迁移完成" ;;
        2) alembic downgrade -1 && success "回滚完成" ;;
        3)
            read -rp "迁移描述: " msg
            alembic revision --autogenerate -m "${msg:-update}" && success "迁移脚本已生成"
            ;;
        4) alembic history --verbose | head -30 ;;
        5) alembic current ;;
        *) warn "无效选择" ;;
    esac
}

ops_backup_config() {
    header "💾 备份项目配置"

    local backup_dir="${PROJECT_DIR}/backups"
    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="${backup_dir}/config_backup_${timestamp}.tar.gz"

    mkdir -p "${backup_dir}"

    tar -czf "${backup_file}" \
        -C "${PROJECT_DIR}" \
        config/ \
        .env 2>/dev/null \
        .env.prod 2>/dev/null \
        alembic.ini 2>/dev/null \
        || true

    if [ -f "${backup_file}" ]; then
        local size
        size=$(du -h "${backup_file}" | awk '{print $1}')
        success "备份完成: ${backup_file} (${size})"
    else
        error "备份失败"
    fi
}

ops_nginx() {
    header "🌐 Nginx 管理"

    if ! cmd_exists nginx; then
        warn "未安装 Nginx"
        return
    fi

    echo ""
    echo -e "  ${GREEN}1)${NC}  检查配置语法"
    echo -e "  ${GREEN}2)${NC}  重载配置"
    echo -e "  ${GREEN}3)${NC}  查看状态"
    echo -e "  ${GREEN}4)${NC}  查看错误日志（最近 30 行）"
    echo ""
    read -rp "请选择 [1-4]: " ng_choice

    case "${ng_choice}" in
        1) sudo nginx -t ;;
        2) sudo nginx -t && sudo systemctl reload nginx && success "Nginx 已重载" ;;
        3) systemctl status nginx --no-pager ;;
        4) sudo tail -30 /var/log/nginx/error.log 2>/dev/null || warn "日志文件不存在" ;;
        *) warn "无效选择" ;;
    esac
}


###############################################################################
#                         6. 服务快捷命令
###############################################################################

svc_status()  { systemctl status "${SERVICE_NAME}" --no-pager 2>/dev/null || warn "服务未安装"; }
svc_start()   { sudo systemctl start "${SERVICE_NAME}" && success "服务已启动"; }
svc_stop()    { sudo systemctl stop "${SERVICE_NAME}" && success "服务已停止"; }
svc_restart() { sudo systemctl restart "${SERVICE_NAME}" && success "服务已重启"; }
svc_logs()    { journalctl -u "${SERVICE_NAME}" -f; }


###############################################################################
#                         7. 主菜单
###############################################################################

show_main_menu() {
    while true; do
        clear 2>/dev/null || true
        echo ""
        echo -e "${BOLD}${CYAN}"
        echo "   ╔═══════════════════════════════════════════════════╗"
        echo "   ║         FastAPI Backend 管理中心                  ║"
        echo "   ╚═══════════════════════════════════════════════════╝"
        echo -e "${NC}"
        echo -e "   ${DIM}项目: ${PROJECT_DIR}${NC}"
        detect_python_env
        echo -e "   ${DIM}环境: ${ENV_TYPE} (${ENV_NAME})${NC}"
        echo ""

        divider
        echo -e "  ${MAGENTA}环境初始化${NC}"
        divider
        echo -e "  ${GREEN}1)${NC}  初始化 Conda 环境 + 安装依赖"
        echo -e "  ${GREEN}2)${NC}  初始化项目（目录 + 数据库迁移）"
        echo -e "  ${GREEN}3)${NC}  创建新业务模块（模型/Schema/CRUD/API）"

        divider
        echo -e "  ${MAGENTA}部署管理${NC}"
        divider
        echo -e "  ${GREEN}4)${NC}  部署 systemd 服务（自动生成 + 注册自启）"
        echo -e "  ${GREEN}5)${NC}  配置延时启动 Timer（开机后延迟 N 秒启动）"
        echo -e "  ${GREEN}6)${NC}  卸载 systemd 服务 + Timer"

        divider
        echo -e "  ${MAGENTA}服务控制${NC}"
        divider
        echo -e "  ${GREEN}7)${NC}  查看服务状态"
        echo -e "  ${GREEN}8)${NC}  启动 / 停止 / 重启服务"
        echo -e "  ${GREEN}9)${NC}  查看服务实时日志"

        divider
        echo -e "  ${MAGENTA}开发工具${NC}"
        divider
        echo -e "  ${GREEN}10)${NC} MySQL SSH 隧道"
        echo -e "  ${GREEN}11)${NC} 服务器运维工具箱"

        divider
        echo ""
        echo -e "  ${DIM}0 / q)  退出${NC}"
        echo ""
        read -rp "  请选择 [0-11]: " choice

        case "${choice}" in
            1)  init_conda_env ;;
            2)  init_project ;;
            3)  create_module ;;
            4)  deploy_service ;;
            5)  setup_timer ;;
            6)  uninstall_service ;;
            7)  svc_status ;;
            8)
                echo ""
                echo -e "  ${GREEN}a)${NC} 启动  ${GREEN}b)${NC} 停止  ${GREEN}c)${NC} 重启"
                read -rp "  请选择: " sub
                case "${sub}" in
                    a|A|start)   svc_start ;;
                    b|B|stop)    svc_stop ;;
                    c|C|restart) svc_restart ;;
                    *) warn "无效选择" ;;
                esac
                ;;
            9)  svc_logs ;;
            10) mysql_tunnel ;;
            11) ops_menu ;;
            0|q|Q|exit) echo ""; success "再见！"; exit 0 ;;
            *) warn "无效选择，请重新输入" ;;
        esac

        echo ""
        read -rp "按回车返回主菜单..." -s
    done
}


###############################################################################
#                         8. 命令行直调
###############################################################################

case "${1:-}" in
    # 环境初始化
    init)       shift; init_conda_env; init_project ;;
    init-env)   init_conda_env ;;
    init-proj)  init_project ;;
    module)     shift; create_module "$@" ;;

    # 部署
    deploy)     deploy_service ;;
    timer)      setup_timer ;;
    uninstall)  uninstall_service ;;

    # 服务控制
    status)     svc_status ;;
    start)      svc_start ;;
    stop)       svc_stop ;;
    restart)    svc_restart ;;
    logs|log)   svc_logs ;;

    # 运维
    tunnel)     mysql_tunnel ;;
    ops)        ops_menu ;;
    port)       shift; ops_port_check "$@" ;;
    sysinfo)    ops_system_info ;;
    migrate)    ops_db_migrate ;;
    backup)     ops_backup_config ;;

    # 帮助
    help|-h|--help)
        header "FastAPI Backend 管理中心"
        echo ""
        echo "用法: $0 [command] [args]"
        echo ""
        echo -e "${BOLD}环境初始化:${NC}"
        echo "  init          完整初始化（Conda + 项目）"
        echo "  init-env      仅初始化 Conda 环境"
        echo "  init-proj     仅初始化项目（目录+数据库）"
        echo "  module <name> 创建新业务模块"
        echo ""
        echo -e "${BOLD}部署管理:${NC}"
        echo "  deploy        部署 systemd 服务 (需要 sudo)"
        echo "  timer         配置延时启动 Timer (需要 sudo)"
        echo "  uninstall     卸载服务 (需要 sudo)"
        echo ""
        echo -e "${BOLD}服务控制:${NC}"
        echo "  status        查看服务状态"
        echo "  start         启动服务"
        echo "  stop          停止服务"
        echo "  restart       重启服务"
        echo "  logs          查看实时日志"
        echo ""
        echo -e "${BOLD}运维工具:${NC}"
        echo "  tunnel        MySQL SSH 隧道"
        echo "  ops           运维工具箱（交互式）"
        echo "  port [N]      查看端口占用"
        echo "  sysinfo       系统资源概览"
        echo "  migrate       数据库迁移管理"
        echo "  backup        备份配置文件"
        echo ""
        echo -e "${DIM}不带参数运行进入交互式菜单${NC}"
        ;;

    # 无参数 → 交互式菜单
    "")
        show_main_menu
        ;;

    *)
        error "未知命令: $1"
        echo "运行 $0 help 查看帮助"
        exit 1
        ;;
esac
