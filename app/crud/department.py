"""部门管理 CRUD 操作

提供部门和用户-部门关联的数据库操作。
"""
from typing import Optional, List, Sequence
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.department import Department, UserDepartment
from app.schemas.department import DepartmentCreate, DepartmentUpdate


class CRUDDepartment(CRUDBase[Department, DepartmentCreate, DepartmentUpdate]):
    """部门 CRUD 操作"""

    async def get_by_code(
        self,
        db: AsyncSession,
        *,
        code: str
    ) -> Optional[Department]:
        """根据编码获取部门"""
        result = await db.execute(
            select(Department).where(Department.code == code)
        )
        return result.scalar_one_or_none()

    async def create_department(
        self,
        db: AsyncSession,
        *,
        obj_in: DepartmentCreate,
        creator_id: int | None = None
    ) -> Department:
        """
        创建部门

        自动计算层级。
        """
        # 计算层级
        level = 1
        if obj_in.parent_id:
            parent = await self.get(db, id=obj_in.parent_id)
            if parent:
                level = parent.level + 1

        dept = Department(
            name=obj_in.name,
            code=obj_in.code,
            parent_id=obj_in.parent_id,
            level=level,
            sort_order=obj_in.sort_order,
            leader_id=obj_in.leader_id,
            description=obj_in.description,
            creator_id=creator_id,
        )

        db.add(dept)
        await db.commit()
        await db.refresh(dept)
        return dept

    async def update_department(
        self,
        db: AsyncSession,
        *,
        dept: Department,
        obj_in: DepartmentUpdate,
        updater_id: int | None = None
    ) -> Department:
        """更新部门"""
        update_data = obj_in.model_dump(exclude_unset=True)

        # 如果更改了父部门，重新计算层级
        if "parent_id" in update_data:
            parent_id = update_data["parent_id"]
            if parent_id:
                parent = await self.get(db, id=parent_id)
                update_data["level"] = parent.level + 1 if parent else 1
            else:
                update_data["level"] = 1

        for field, value in update_data.items():
            setattr(dept, field, value)

        dept.updater_id = updater_id

        db.add(dept)
        await db.commit()
        await db.refresh(dept)
        return dept

    async def get_all_active(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[Sequence[Department], int]:
        """获取所有启用的部门"""
        # 查询总数
        count_stmt = select(func.count(Department.id)).where(
            Department.is_active.is_(True)
        )
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 查询列表
        query_stmt = (
            select(Department)
            .where(Department.is_active.is_(True))
            .order_by(Department.level, Department.sort_order, Department.id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query_stmt)
        items = result.scalars().all()

        return items, total

    async def get_tree(
        self,
        db: AsyncSession,
        *,
        parent_id: int | None = None,
        include_inactive: bool = False
    ) -> List[dict]:
        """
        获取部门树（优化版：一次查询，内存构建）

        Args:
            db: 数据库会话
            parent_id: 父部门ID（None 表示从根开始）
            include_inactive: 是否包含禁用的部门

        Returns:
            树形结构的部门列表
        """
        # 一次性查询所有部门
        conditions = []
        if not include_inactive:
            conditions.append(Department.is_active.is_(True))

        query = select(Department).order_by(Department.level, Department.sort_order, Department.id)
        if conditions:
            query = query.where(and_(*conditions))

        result = await db.execute(query)
        all_departments = result.scalars().all()

        # 构建部门字典和子部门映射
        dept_dict = {}
        children_map = {}  # parent_id -> [children]

        for dept in all_departments:
            dept_data = {
                "id": dept.id,
                "name": dept.name,
                "code": dept.code,
                "parent_id": dept.parent_id,
                "level": dept.level,
                "sort_order": dept.sort_order,
                "is_active": dept.is_active,
                "leader_id": dept.leader_id,
                "description": dept.description,
                "children": []
            }
            dept_dict[dept.id] = dept_data

            # 按父部门分组
            pid = dept.parent_id
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(dept_data)

        # 递归构建树
        def build_tree(pid: int | None = None) -> List[dict]:
            children = children_map.get(pid, [])
            for child in children:
                child["children"] = build_tree(child["id"])
            return children

        return build_tree(parent_id)

    async def get_children(
        self,
        db: AsyncSession,
        *,
        parent_id: int
    ) -> Sequence[Department]:
        """获取直接子部门"""
        result = await db.execute(
            select(Department)
            .where(Department.parent_id == parent_id)
            .order_by(Department.sort_order, Department.id)
        )
        return result.scalars().all()

    async def has_children(
        self,
        db: AsyncSession,
        *,
        department_id: int
    ) -> bool:
        """检查是否有子部门"""
        result = await db.execute(
            select(func.count(Department.id))
            .where(Department.parent_id == department_id)
        )
        return (result.scalar() or 0) > 0

    async def get_sub_department_ids(
        self,
        db: AsyncSession,
        *,
        department_id: int,
        recursive: bool = True
    ) -> List[int]:
        """
        获取所有子部门 ID

        非递归模式：只返回直接子部门，一次 SQL
        递归模式：一次 SQL 拉全部 (id, parent_id) 后在内存里 BFS 收集，
                 避免原先"每层一次 SQL"的 N+1（层级深时可能成百上千次查询）
        """
        if not recursive:
            result = await db.execute(
                select(Department.id)
                .where(Department.parent_id == department_id)
            )
            return list(result.scalars().all())

        # 递归：一次查询 id + parent_id，按 parent_id 建立邻接表，再 BFS
        result = await db.execute(
            select(Department.id, Department.parent_id)
        )
        children_map: dict[int, list[int]] = {}
        for row_id, row_parent in result.all():
            if row_parent is not None:
                children_map.setdefault(row_parent, []).append(row_id)

        collected: List[int] = []
        queue: list[int] = list(children_map.get(department_id, []))
        visited: set[int] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            collected.append(current)
            queue.extend(children_map.get(current, []))

        return collected


class CRUDUserDepartment:
    """用户-部门关联 CRUD 操作"""

    async def assign_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        department_id: int,
        is_primary: bool = False,
        position: str | None = None
    ) -> UserDepartment:
        """
        分配用户到部门

        如果设置为主部门，会自动取消其他主部门标记。
        """
        # 检查是否已存在
        existing = await self.get_user_department(
            db,
            user_id=user_id,
            department_id=department_id
        )

        if existing:
            # 更新现有记录
            existing.is_primary = is_primary
            if position is not None:
                existing.position = position

            if is_primary:
                await self._clear_other_primary(db, user_id=user_id, except_id=existing.id)

            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing

        # 创建新记录
        if is_primary:
            await self._clear_other_primary(db, user_id=user_id)

        link = UserDepartment(
            user_id=user_id,
            department_id=department_id,
            is_primary=is_primary,
            position=position,
        )

        db.add(link)
        await db.commit()
        await db.refresh(link)
        return link

    async def batch_assign_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        department_ids: List[int],
        primary_department_id: int | None = None,
        clear_existing: bool = False
    ) -> List[UserDepartment]:
        """
        批量分配用户到多个部门

        Args:
            user_id: 用户ID
            department_ids: 部门ID列表
            primary_department_id: 主部门ID
            clear_existing: 是否清除现有部门
                - True: 替换模式，清除所有现有部门后重新分配
                - False: 追加模式，保留现有部门，仅添加新部门
        """
        if clear_existing:
            # 替换模式：删除现有关联
            await self.remove_all_user_departments(db, user_id=user_id)

        # 获取用户当前已有的部门ID
        existing_links = await self.get_user_departments(db, user_id=user_id)
        existing_dept_ids = {link.department_id for link in existing_links}

        # 如果设置了新的主部门，清除旧的主部门标记
        if primary_department_id:
            await self._clear_other_primary(db, user_id=user_id)

        # 创建新关联（跳过已存在的）
        links = list(existing_links) if not clear_existing else []
        for dept_id in department_ids:
            if dept_id in existing_dept_ids and not clear_existing:
                # 追加模式下，已存在的部门只更新主部门标记
                if dept_id == primary_department_id:
                    for link in links:
                        if link.department_id == dept_id:
                            link.is_primary = True
                            db.add(link)
                            break
                continue

            is_primary = (dept_id == primary_department_id)
            link = UserDepartment(
                user_id=user_id,
                department_id=dept_id,
                is_primary=is_primary,
            )
            db.add(link)
            links.append(link)

        await db.commit()

        # 刷新获取完整数据
        for link in links:
            try:
                await db.refresh(link)
            except Exception:  # noqa: S110 -- 批量分配过程中对象可能已被清理,refresh 失败可忽略
                pass

        return [link for link in links if link.id is not None]

    async def remove_user_from_department(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        department_id: int
    ) -> bool:
        """从部门移除用户"""
        link = await self.get_user_department(
            db,
            user_id=user_id,
            department_id=department_id
        )

        if not link:
            return False

        await db.delete(link)
        await db.commit()
        return True

    async def remove_all_user_departments(
        self,
        db: AsyncSession,
        *,
        user_id: int
    ) -> int:
        """清除用户所有部门关联"""
        result = await db.execute(
            select(UserDepartment).where(UserDepartment.user_id == user_id)
        )
        links = result.scalars().all()

        count = len(links)
        for link in links:
            await db.delete(link)

        await db.commit()
        return count

    async def get_user_department(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        department_id: int
    ) -> Optional[UserDepartment]:
        """获取用户-部门关联"""
        result = await db.execute(
            select(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id
            )
        )
        return result.scalar_one_or_none()

    async def get_user_departments(
        self,
        db: AsyncSession,
        *,
        user_id: int
    ) -> Sequence[UserDepartment]:
        """获取用户的所有部门"""
        result = await db.execute(
            select(UserDepartment)
            .options(selectinload(UserDepartment.department))
            .where(UserDepartment.user_id == user_id)
        )
        return result.scalars().all()

    async def get_user_primary_department(
        self,
        db: AsyncSession,
        *,
        user_id: int
    ) -> Optional[UserDepartment]:
        """获取用户的主部门"""
        result = await db.execute(
            select(UserDepartment)
            .options(selectinload(UserDepartment.department))
            .where(
                UserDepartment.user_id == user_id,
                UserDepartment.is_primary.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_department_users(
        self,
        db: AsyncSession,
        *,
        department_id: int,
        recursive: bool = False,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[Sequence[UserDepartment], int]:
        """
        获取部门下的用户

        Args:
            db: 数据库会话
            department_id: 部门 ID
            recursive: 是否包含子部门成员
            skip: 跳过记录数
            limit: 返回记录数
        """
        # 确定要查询的部门 ID 列表
        dept_ids = [department_id]
        if recursive:
            sub_ids = await department.get_sub_department_ids(db, department_id=department_id)
            dept_ids.extend(sub_ids)

        # 总数
        count_stmt = select(func.count(UserDepartment.id)).where(
            UserDepartment.department_id.in_(dept_ids)
        )
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 列表
        query_stmt = (
            select(UserDepartment)
            .options(selectinload(UserDepartment.user))
            .where(UserDepartment.department_id.in_(dept_ids))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query_stmt)
        items = result.scalars().all()

        return items, total

    async def _clear_other_primary(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        except_id: int | None = None
    ) -> None:
        """清除用户的其他主部门标记"""
        conditions = [
            UserDepartment.user_id == user_id,
            UserDepartment.is_primary.is_(True),
        ]
        if except_id:
            conditions.append(UserDepartment.id != except_id)

        result = await db.execute(
            select(UserDepartment).where(and_(*conditions))
        )
        links = result.scalars().all()

        for link in links:
            link.is_primary = False
            db.add(link)


# 全局实例
department = CRUDDepartment(Department)
user_department = CRUDUserDepartment()
