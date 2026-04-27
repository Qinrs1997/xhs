# Makefile for Base FastAPI AI Project

.PHONY: help start dev prod migrate setup clean test lint

# 默认目标
help:
	@echo "Base FastAPI AI 项目管理命令"
	@echo ""
	@echo "使用方法: make [command]"
	@echo ""
	@echo "开发命令:"
	@echo "  setup    - 初始化环境（安装依赖、配置数据库）"
	@echo "  dev      - 启动开发服务器 (热重载 enabled)"
	@echo "  start    - 启动生产服务器"
	@echo "  test     - 运行测试套件"
	@echo "  lint     - 代码风格检查"
	@echo ""
	@echo "数据库命令:"
	@echo "  migrate  - 生成并应用数据库迁移"
	@echo "  db-up    - 仅应用迁移"
	@echo "  db-reset - 重置数据库（慎用！）"
	@echo ""
	@echo "项目管理:"
	@echo "  clean    - 清理缓存文件"
	@echo "  module   - 创建新模块 (用法: make module NAME=xxx)"

# 初始化
setup:
	@echo "📦 安装依赖..."
	pip install -r requirements.txt
	@echo "🔧 初始化环境脚本..."
	chmod +x scripts/*.sh

# 启动服务
dev:
	bash scripts/start.sh

start:
	APP_ENV=prod bash scripts/start.sh

# 数据库操作
migrate:
	bash scripts/migrate.sh

db-up:
	alembic upgrade head

# 创建新模块
module:
	@if [ -z "$(NAME)" ]; then echo "Error: 请指定模块名称，例如 make module NAME=blog"; exit 1; fi
	bash scripts/new_module.sh $(NAME)

# 运行测试
test:
	pytest

# 清理
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .coverage
