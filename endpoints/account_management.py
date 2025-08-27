import uuid
import secrets
import base64
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import func
import logging
from dify_plugin.config.logger_format import plugin_logger_handler

from .db_engine import db
from .database_config import DatabaseConfig
from .password import hash_password
# 使用自定义处理器设置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)
# 初始化数据库的函数
def init_account_management_db(app=None):
    if db.app is None and app is not None:
        db.init_app(app)
    return db

# 定义数据模型
class Account(db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    password = db.Column(db.String(255))
    password_salt = db.Column(db.String(255))
    interface_language = db.Column(db.String(10), default='en-US')
    interface_theme = db.Column(db.String(10), default='light')
    timezone = db.Column(db.String(50), default='UTC')
    status = db.Column(db.String(20), default='active')
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Account {self.email}>'

class Tenant(db.Model):
    __tablename__ = 'tenants'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='normal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Tenant {self.name}>'

class TenantAccountJoin(db.Model):
    __tablename__ = 'tenant_account_joins'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False)
    account_id = db.Column(db.String(36), db.ForeignKey('accounts.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    current = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 定义外键关系
    tenant = db.relationship('Tenant', backref=db.backref('tenant_account_joins', lazy=True))
    account = db.relationship('Account', backref=db.backref('tenant_account_joins', lazy=True))

    def __repr__(self):
        return f'<TenantAccountJoin tenant={self.tenant_id}, account={self.account_id}, role={self.role}>'

# 定义角色常量
class TenantAccountRole:
    OWNER = 'owner'
    ADMIN = 'admin'
    DATASET_OPERATOR = 'dataset_operator'
    NORMAL = 'normal'
    EDITOR = 'editor'

# 异常类定义
class AccountNotFoundError(Exception):
    pass

class TenantNotFoundError(Exception):
    pass

class MemberNotInTenantError(Exception):
    pass

class AccountAlreadyInTenantError(Exception):
    pass

class CannotOperateSelfError(Exception):
    pass

class NoPermissionError(Exception):
    pass

class RoleAlreadyAssignedError(Exception):
    pass

# 服务类实现
class AccountManagementService:
    # 语言与时区映射
    language_timezone_mapping = {
        "en-US": "America/New_York",
        "zh-Hans": "Asia/Shanghai",
        "zh-Hant": "Asia/Taipei",
        "pt-BR": "America/Sao_Paulo",
        "es-ES": "Europe/Madrid",
        "fr-FR": "Europe/Paris",
        "de-DE": "Europe/Berlin",
        "ja-JP": "Asia/Tokyo",
        "ko-KR": "Asia/Seoul",
        "ru-RU": "Europe/Moscow",
        "it-IT": "Europe/Rome",
        "uk-UA": "Europe/Kyiv",
        "vi-VN": "Asia/Ho_Chi_Minh",
        "ro-RO": "Europe/Bucharest",
        "pl-PL": "Europe/Warsaw",
        "hi-IN": "Asia/Kolkata",
        "tr-TR": "Europe/Istanbul",
        "fa-IR": "Asia/Tehran",
        "sl-SI": "Europe/Ljubljana",
        "th-TH": "Asia/Bangkok",
    }
    @staticmethod
    def sync_accounts(sync_data, app_context=None):
        """
        同步账户数据
        :param sync_data: 同步数据列表
        :param app_context: Flask应用上下文
        :return: 同步结果
        """
        results = []
        try:
            # 开始事务
            db.session.begin()
            
            for user_data in sync_data:
                # 使用id作为唯一标识
                user_id = str(user_data.get("id"))
                real_name = user_data.get("realName")
                phone = user_data.get("phone")
                # 从数据库查询第一个租户id
                first_tenant = Tenant.query.first()
                if not first_tenant:
                    raise TenantNotFoundError("数据库中未找到租户信息")
                tenant_id = first_tenant.id
                is_admin = user_data.get("admin", False)
                role_name = user_data.get("roleName")
                
                # 这里我们假设使用phone或id生成email
                email = f"{phone}@taidesk.com" if phone else f"u_{user_id}@taidesk.com"
                
                try:
                    # 检查用户是否存在
                    existing_account = AccountManagementService.get_account_by_email(email)
                    
                    if existing_account:
                        # 更新用户
                        result = AccountManagementService.update_account(
                            email=email,
                            name=real_name,
                            tenant_id=tenant_id,
                            role="admin" if is_admin else role_name if role_name else "normal"
                        )
                        results.append({
                            "user_id": user_id,
                            "status": "updated",
                            "data": result
                        })
                    else:
                        # 创建用户
                        result = AccountManagementService.create_account(
                            email=email,
                            name=real_name,
                            password=str(email),
                            tenant_id=tenant_id,
                            role="admin" if is_admin else role_name if role_name else "normal"
                        )
                        results.append({
                            "user_id": user_id,
                            "status": "created",
                            "data": result
                        })
                except AccountNotFoundError:
                    # 用户不存在，创建新用户
                    result = AccountManagementService.create_account(
                        email=email,
                        name=real_name,
                        password=str(email),
                        tenant_id=tenant_id,
                        role="admin" if is_admin else role_name if role_name else "normal"
                    )
                    results.append({
                        "user_id": user_id,
                        "status": "created",
                        "data": result
                    })
                except Exception as e:
                    print(f"同步用户数据异常 (user_id: {user_id}): {str(e)}")
                    results.append({
                        "user_id": user_id,
                        "status": "error",
                        "error": str(e)
                    })
            
            # 提交事务
            db.session.commit()
            return results
        except Exception as e:
            # 回滚事务
            db.session.rollback()
            print(f"同步账户事务失败: {str(e)}")
            raise

    @staticmethod
    def get_account_by_email(email: str) -> Account:
        """通过邮箱查找账户"""
        account = Account.query.filter_by(email=email).first()
        if not account:
            raise AccountNotFoundError(f"Account with email {email} not found")
        return account

    @staticmethod
    def get_all_accounts() -> List[Dict[str, Any]]:
        """获取所有账户信息"""
        accounts = Account.query.all()
        result = []
        for account in accounts:
            account_dict = {
                'id': str(account.id),  # 确保id是字符串类型
                'email': account.email,
                'name': account.name,
                'interface_language': account.interface_language,
                'interface_theme': account.interface_theme,
                'timezone': account.timezone,
                'status': account.status,
                'created_at': account.created_at.isoformat(),
                'updated_at': account.updated_at.isoformat()
            }
            result.append(account_dict)
        return result

    @staticmethod
    def create_account(
        email: str,
        name: str,
        interface_language: str = 'en-US',
        password: Optional[str] = None,
        interface_theme: str = 'light',
        role: str = 'normal',
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # 检查账户是否已存在
        existing_account = Account.query.filter_by(email=email).first()
        if existing_account:
            raise ValueError(f"Account with email {email} already exists")

        # 创建新账户
        new_account = Account(
            email=email,
            name=name,
            interface_language=interface_language,
            interface_theme=interface_theme
        )

        # 处理密码
        if password:
            # 生成密码盐
            salt = secrets.token_bytes(16)
            base64_salt = base64.b64encode(salt).decode()

            # 加密密码
            password_hashed = hash_password(password, salt)
            base64_password_hashed = base64.b64encode(password_hashed).decode()

            new_account.password = base64_password_hashed
            new_account.password_salt = base64_salt

        # 设置时区
        new_account.timezone = AccountManagementService.language_timezone_mapping.get(interface_language, 'UTC')

        logger.info(f"Creating new account: {email}")

        # 保存到数据库
        db.session.add(new_account)
        db.session.commit()

        # 如果提供了租户ID，创建租户成员关系
        if tenant_id:
            # 检查租户是否存在
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                raise TenantNotFoundError(f"Tenant with id {tenant_id} not found")

            # 确定角色
            if role.lower() == 'admin':
                final_role = TenantAccountRole.ADMIN
            else:
                final_role = TenantAccountRole.NORMAL

            # 创建租户成员关系
            new_join = TenantAccountJoin(
                tenant_id=tenant_id,
                account_id=new_account.id,
                role=final_role
            )
            db.session.add(new_join)
            db.session.commit()

        # 返回创建的账户信息
        result = {
            'id': new_account.id,
            'email': new_account.email,
            'name': new_account.name,
            'interface_language': new_account.interface_language,
            'interface_theme': new_account.interface_theme,
            'created_at': new_account.created_at.isoformat()
        }

        if tenant_id:
            result['tenant_id'] = tenant_id
            result['role'] = final_role

        return result

    @staticmethod
    def update_account(
        email: str,
        name: Optional[str] = None,
        new_email: Optional[str] = None,
        interface_language: Optional[str] = None,
        interface_theme: Optional[str] = None,
        role: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # 查找账户
        account = Account.query.filter_by(email=email).first()
        if not account:
            raise AccountNotFoundError(f"Account with email {email} not found")

        # 更新账户信息
        if name is not None:
            account.name = name
        if new_email is not None:
            # 检查新邮箱是否已被使用
            existing_account = Account.query.filter_by(email=new_email).first()
            if existing_account and existing_account.id != account.id:
                raise ValueError(f"Email {new_email} is already used by another account")
            account.email = new_email
        if interface_language is not None:
            account.interface_language = interface_language
        if interface_theme is not None:
            account.interface_theme = interface_theme

        # 更新时间戳
        account.updated_at = datetime.utcnow()

        # 如果提供了角色和租户ID，更新租户成员关系
        if role is not None and tenant_id is not None:
            # 检查租户是否存在
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                raise TenantNotFoundError(f"Tenant with id {tenant_id} not found")

            # 查找租户成员关系
            join = TenantAccountJoin.query.filter_by(
                tenant_id=tenant_id,
                account_id=account.id
            ).first()

            if join:
                # 确定角色
                if role.lower() == 'admin':
                    final_role = TenantAccountRole.ADMIN
                else:
                    final_role = TenantAccountRole.NORMAL

                # 更新角色
                join.role = final_role
                join.updated_at = datetime.utcnow()
            else:
                # 创建新的租户成员关系
                # 确定角色
                if role.lower() == 'admin':
                    final_role = TenantAccountRole.ADMIN
                else:
                    final_role = TenantAccountRole.NORMAL

                new_join = TenantAccountJoin(
                    tenant_id=tenant_id,
                    account_id=account.id,
                    role=final_role
                )
                db.session.add(new_join)

        # 保存更改
        db.session.commit()

        # 返回更新后的账户信息
        result = {
            'id': account.id,
            'email': account.email,
            'name': account.name,
            'interface_language': account.interface_language,
            'interface_theme': account.interface_theme,
            'updated_at': account.updated_at.isoformat()
        }

        if role is not None and tenant_id is not None:
            result['tenant_id'] = tenant_id
            result['role'] = final_role

        return result

    @staticmethod
    def delete_account(email: str) -> Dict[str, Any]:
        # 查找账户
        account = Account.query.filter_by(email=email).first()
        if not account:
            raise AccountNotFoundError(f"Account with email {email} not found")

        account_id = account.id

        # 查找并删除关联的租户关系
        tenant_joins = TenantAccountJoin.query.filter_by(account_id=account_id).all()
        for join in tenant_joins:
            db.session.delete(join)

        # 删除账户
        db.session.delete(account)
        db.session.commit()

        return {
            'email': email,
            'message': 'Account deleted successfully'
        }

    @staticmethod
    def create_tenant(name: str) -> Dict[str, Any]:
        # 创建新租户
        new_tenant = Tenant(name=name)

        # 保存到数据库
        db.session.add(new_tenant)
        db.session.commit()

        return {
            'id': new_tenant.id,
            'name': new_tenant.name,
            'created_at': new_tenant.created_at.isoformat()
        }

    @staticmethod
    def add_tenant_member(tenant_id: str, account_id: str, role: str = 'normal') -> Dict[str, Any]:
        # 检查租户是否存在
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"Tenant with id {tenant_id} not found")

        # 检查账户是否存在
        account = Account.query.get(account_id)
        if not account:
            raise AccountNotFoundError(f"Account with id {account_id} not found")

        # 检查账户是否已在租户中
        existing_join = TenantAccountJoin.query.filter_by(
            tenant_id=tenant_id,
            account_id=account_id
        ).first()
        if existing_join:
            raise AccountAlreadyInTenantError(f"Account {account_id} is already in tenant {tenant_id}")

        # 检查角色是否有效
        valid_roles = [TenantAccountRole.OWNER, TenantAccountRole.ADMIN, TenantAccountRole.DATASET_OPERATOR, TenantAccountRole.NORMAL]
        if role not in valid_roles:
            raise ValueError(f"Invalid role {role}. Valid roles are {valid_roles}")

        # 创建租户成员关系
        new_join = TenantAccountJoin(
            tenant_id=tenant_id,
            account_id=account_id,
            role=role
        )

        # 保存到数据库
        db.session.add(new_join)
        db.session.commit()

        return {
            'id': new_join.id,
            'tenant_id': new_join.tenant_id,
            'account_id': new_join.account_id,
            'role': new_join.role,
            'created_at': new_join.created_at.isoformat()
        }

    @staticmethod
    def remove_tenant_member(tenant_id: str, account_id: str, operator_id: str) -> Dict[str, Any]:
        # 检查租户是否存在
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"Tenant with id {tenant_id} not found")

        # 检查账户是否存在
        account = Account.query.get(account_id)
        if not account:
            raise AccountNotFoundError(f"Account with id {account_id} not found")

        # 检查操作符是否存在
        operator = Account.query.get(operator_id)
        if not operator:
            raise AccountNotFoundError(f"Operator account with id {operator_id} not found")

        # 检查操作符是否是租户成员
        operator_join = TenantAccountJoin.query.filter_by(
            tenant_id=tenant_id,
            account_id=operator_id
        ).first()
        if not operator_join:
            raise MemberNotInTenantError(f"Operator {operator_id} is not a member of tenant {tenant_id}")

        # 检查操作符是否有权限移除成员
        if operator_join.role not in [TenantAccountRole.OWNER, TenantAccountRole.ADMIN]:
            raise NoPermissionError(f"Operator {operator_id} has no permission to remove members from tenant {tenant_id}")

        # 查找租户成员关系
        join = TenantAccountJoin.query.filter_by(
            tenant_id=tenant_id,
            account_id=account_id
        ).first()
        if not join:
            raise MemberNotInTenantError(f"Account {account_id} is not a member of tenant {tenant_id}")

        # 不能移除自己
        if account_id == operator_id:
            raise CannotOperateSelfError("Cannot remove yourself from the tenant")

        # 删除租户成员关系
        db.session.delete(join)
        db.session.commit()

        return {
            'tenant_id': tenant_id,
            'account_id': account_id,
            'message': 'Member removed from tenant successfully'
        }

    @staticmethod
    def update_member_role(tenant_id: str, account_id: str, new_role: str, operator_id: str) -> Dict[str, Any]:
        # 检查租户是否存在
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"Tenant with id {tenant_id} not found")

        # 检查账户是否存在
        account = Account.query.get(account_id)
        if not account:
            raise AccountNotFoundError(f"Account with id {account_id} not found")

        # 检查操作符是否存在
        operator = Account.query.get(operator_id)
        if not operator:
            raise AccountNotFoundError(f"Operator account with id {operator_id} not found")

        # 检查操作符是否是租户成员
        operator_join = TenantAccountJoin.query.filter_by(
            tenant_id=tenant_id,
            account_id=operator_id
        ).first()
        if not operator_join:
            raise MemberNotInTenantError(f"Operator {operator_id} is not a member of tenant {tenant_id}")

        # 检查操作符是否有权限更新角色
        if operator_join.role not in [TenantAccountRole.OWNER, TenantAccountRole.ADMIN]:
            raise NoPermissionError(f"Operator {operator_id} has no permission to update member roles in tenant {tenant_id}")

        # 查找租户成员关系
        join = TenantAccountJoin.query.filter_by(
            tenant_id=tenant_id,
            account_id=account_id
        ).first()
        if not join:
            raise MemberNotInTenantError(f"Account {account_id} is not a member of tenant {tenant_id}")

        # 检查角色是否有效
        valid_roles = [TenantAccountRole.OWNER, TenantAccountRole.ADMIN, TenantAccountRole.DATASET_OPERATOR, TenantAccountRole.NORMAL]
        if new_role not in valid_roles:
            raise ValueError(f"Invalid role {new_role}. Valid roles are {valid_roles}")

        # 检查是否已是相同角色
        if join.role == new_role:
            raise RoleAlreadyAssignedError(f"Account {account_id} already has role {new_role} in tenant {tenant_id}")

        # 更新角色
        join.role = new_role
        join.updated_at = datetime.utcnow()

        # 保存更改
        db.session.commit()

        return {
            'id': join.id,
            'tenant_id': join.tenant_id,
            'account_id': join.account_id,
            'new_role': join.role,
            'updated_at': join.updated_at.isoformat()
        }

    @staticmethod
    def get_tenant_members(tenant_id: str) -> List[Dict[str, Any]]:
        # 检查租户是否存在
        tenant = Tenant.query.get(tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"Tenant with id {tenant_id} not found")

        # 查找租户成员关系
        joins = TenantAccountJoin.query.filter_by(tenant_id=tenant_id).all()

        # 构建成员列表
        members = []
        for join in joins:
            account = Account.query.get(join.account_id)
            if account:
                members.append({
                    'id': join.id,
                    'account_id': join.account_id,
                    'account_name': account.name,
                    'account_email': account.email,
                    'role': join.role,
                    'created_at': join.created_at.isoformat()
                })

        return members