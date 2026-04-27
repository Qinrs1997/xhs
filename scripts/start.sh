#!/bin/bash

###############################################################################
# FastAPI 开发服务器启动脚本（简化版）
#
# 功能：
# 1. 自动检测并激活虚拟环境（Conda 或 venv）
# 2. 从 config/settings.toml 加载配置
# 3. 启动开发服务器
#
# 注意：所有配置都在 config/settings.toml 中管理
###############################################################################

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 统一的 Conda 环境名称（只改 scripts/_env.sh 这一处即可）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_env.sh"

# 打印函数
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# 切换到项目根目录
cd "$(dirname "$0")/.."

print_header "🚀 FastAPI 开发服务器"

# ============================================================================
# 1. 检测并激活虚拟环境
# ============================================================================

ensure_env() {
    print_info "检测/激活虚拟环境..."

    # 已在 conda 非 base 环境
    if [ -n "$CONDA_DEFAULT_ENV" ] && [ "$CONDA_DEFAULT_ENV" != "base" ]; then
        print_success "已在 Conda 环境：$CONDA_DEFAULT_ENV"
        return
    fi

    # 已在 venv 环境
    if [ -n "$VIRTUAL_ENV" ]; then
        print_success "已在 venv 环境：$(basename "$VIRTUAL_ENV")"
        return
    fi

    # 尝试激活 conda 环境
    if command -v conda >/dev/null 2>&1; then
        eval "$(conda shell.bash hook)"
        if conda env list | grep -q "^${DEFAULT_CONDA_ENV} "; then
            print_info "自动激活 Conda 环境：${DEFAULT_CONDA_ENV}"
            conda activate "${DEFAULT_CONDA_ENV}"
            print_success "环境激活成功"
            return
        fi
    fi

    # 尝试激活 venv
    if [ -d "venv" ]; then
        print_info "自动激活 venv 环境"
        # shellcheck source=/dev/null
        source venv/bin/activate
        print_success "环境激活成功"
        return
    fi

    print_error "未检测到可用虚拟环境！"
    echo ""
    print_info "请先运行初始化脚本创建环境："
    echo -e "  ${GREEN}./scripts/init.sh${NC}"
    exit 1
}

ensure_env

# ============================================================================
# 2. 检查依赖
# ============================================================================

print_info "检查依赖..."
if ! command -v uvicorn >/dev/null 2>&1; then
    print_error "uvicorn 未安装！"
    echo ""
    print_error "请先运行初始化脚本："
    echo -e "  ${GREEN}./scripts/init.sh${NC}"
    exit 1
fi

# 检查关键 Python 包
if ! python3 -c "import pydantic, sqlalchemy, alembic" >/dev/null 2>&1; then
    print_error "检测到缺失关键 Python 依赖包 (pydantic/sqlalchemy/alembic)！"
    echo ""
    print_info "请运行以下命令安装依赖："
    echo -e "  ${GREEN}pip install -r requirements.txt${NC}"
    echo "  或者运行初始化脚本: ${GREEN}./scripts/init.sh${NC}"
    exit 1
fi

print_success "依赖检查通过"

# ============================================================================
# 3. 检查配置文件
# ============================================================================

print_info "检查配置文件..."
if [ ! -f "config/settings.toml" ]; then
    print_error "配置文件 config/settings.toml 不存在！"
    exit 1
fi
print_success "配置文件检查通过"

# ============================================================================
# 4. 加载配置
# ============================================================================

print_info "加载配置..."

# 确保项目根目录在 Python 路径中
export PYTHONPATH="$(pwd):$PYTHONPATH"

# 从配置文件读取配置（通过 Python）
# 使用 heredoc 避免 bash 对引号和反引号的误解
if ! CONFIG_OUTPUT=$(python3 - <<'PY' 2>&1
import sys
import shlex
from pathlib import Path

# 确保可以导入 app 模块
project_root = Path.cwd()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from app.core.config import settings

    def emit(key, value):
        # 使用 shlex.quote 确保带空格或特殊字符的值安全传递给 shell
        print(f'{key}={shlex.quote(str(value))}')

    emit('APP_HOST', settings.APP_HOST)
    emit('APP_PORT', settings.APP_PORT)
    emit('APP_WORKERS', settings.APP_WORKERS)
    emit('DEBUG', settings.DEBUG)
    emit('DOCS_URL', settings.DOCS_URL)
    emit('PROJECT_NAME', settings.PROJECT_NAME)
    emit('APP_ENV', settings.APP_ENV)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
PY
); then
    print_error "配置加载失败！"
    echo "----------------------------------------"
    echo "$CONFIG_OUTPUT"
    echo "----------------------------------------"
    print_info "请检查 app/core/config.py 或 config/settings.toml 是否配置正确"
    exit 1
fi

# 解析配置
eval "$CONFIG_OUTPUT"

print_success "配置加载完成"

# ============================================================================
# 5. 应用就绪检查 (可选，重型初始化已移至 app lifespan)
# ============================================================================

print_info "正在准备启动环境..."
# 此处不再运行耗时的 alembic 迁移，由 app/main.py 的 lifespan 负责基础自检
# 生产环境建议依然手动运行迁移脚本：./scripts/migrate.sh upgrade head


# ============================================================================
# 6. 检查端口占用并自动处理
# ============================================================================

print_info "正在检查端口 $APP_PORT ..."
if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -t -i :$APP_PORT)
    if [ -n "$PIDS" ]; then
        print_warning "检测到端口 $APP_PORT 已被占用 (PID: $PIDS)，正在尝试关闭..."
        for PID in $PIDS; do
            kill -9 "$PID" 2>/dev/null || true
        done
        sleep 1
        print_success "已关闭占用进程"
    fi
elif command -v fuser >/dev/null 2>&1; then
    if fuser $APP_PORT/tcp >/dev/null 2>&1; then
        print_warning "检测到端口 $APP_PORT 已被占用，正在尝试关闭..."
        fuser -k $APP_PORT/tcp >/dev/null 2>&1 || true
        sleep 1
        print_success "已关闭占用进程"
    fi
fi
print_success "端口 $APP_PORT 已就绪"


# ============================================================================
# 7. 显示启动信息
# ============================================================================

print_header "📊 服务配置"
echo ""
echo -e "  ${CYAN}项目名称:${NC} $PROJECT_NAME"
echo -e "  ${CYAN}运行环境:${NC} $APP_ENV"
echo -e "  ${CYAN}调试模式:${NC} $DEBUG"
echo -e "  ${CYAN}工作进程:${NC} $APP_WORKERS"
echo ""

# ============================================================================
# 8. 启动服务器
# ============================================================================

print_success "启动开发服务器..."
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  📍 服务地址:${NC} http://${APP_HOST}:${APP_PORT}"
if [ "$DOCS_URL" != "None" ] && [ -n "$DOCS_URL" ]; then
    echo -e "${GREEN}  📖 API 文档:${NC} http://${APP_HOST}:${APP_PORT}${DOCS_URL}"
fi
echo -e "${GREEN}  🛑 按 Ctrl+C 停止服务器${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 根据 DEBUG 模式决定是否使用 --reload
if [ "$DEBUG" = "True" ] || [ "$DEBUG" = "true" ]; then
    RELOAD_FLAG="--reload"
else
    RELOAD_FLAG=""
fi

# 启动服务
uvicorn app.main:app \
    --host ${APP_HOST} \
    --port ${APP_PORT} \
    --workers ${APP_WORKERS} \
    ${RELOAD_FLAG}
