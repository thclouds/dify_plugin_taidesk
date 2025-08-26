import uuid
import secrets
import base64
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Mapping

from sqlalchemy import func
import logging
from dify_plugin.config.logger_format import plugin_logger_handler

from .db_engine import db
from .database_config import DatabaseConfig
from .account_management import Tenant, TenantNotFoundError

# 使用自定义处理器设置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)

# 从Dify复制的ProviderModel模型
class ProviderModel(db.Model):
    __tablename__ = 'provider_models'

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.String(36), nullable=False)
    provider_name = db.Column(db.String(255), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    model_type = db.Column(db.String(40), nullable=False)
    encrypted_config = db.Column(db.Text, nullable=True)
    is_valid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ProviderModel(provider_name={self.provider_name}, model_name={self.model_name}, model_type={self.model_type})>'

# 从Dify复制的ProviderModelSetting模型
class ProviderModelSetting(db.Model):
    __tablename__ = 'provider_model_settings'

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.String(36), nullable=False)
    provider_name = db.Column(db.String(255), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    model_type = db.Column(db.String(40), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    load_balancing_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ProviderModelSetting(provider_name={self.provider_name}, model_name={self.model_name}, model_type={self.model_type}, enabled={self.enabled})>'

# 服务类实现
class ModelManagementService:
    @staticmethod
    def sync_models(models_data, settings: Mapping):
        """
        同步模型数据
        :param models_data: 模型数据列表
        :return: 同步结果
        """
        results = []
        api_key = settings.get("api_key")
        try:
            # 开始事务
            db.session.begin()
            
            for model_data in models_data:
                model_id = str(model_data.get("id"))
                name = model_data.get("name")
                code = model_data.get("code")
                vision = bool(model_data.get("vision", 0))
                search = bool(model_data.get("search", 0))
                rerank = bool(model_data.get("rerank", 0))
                functioncall = bool(model_data.get("functioncall", 0))
                reasoning = bool(model_data.get("reasoning", 0))
                embedding = bool(model_data.get("embedding", 0))
                
                try:
                    
                    # 写入ProviderModel表
                    # 生成model_name (id+'/'+code)
                    provider_model_name = f"{model_id}/{code}"
                    # 从数据库查询第一个租户id
                    first_tenant = Tenant.query.first()
                    if not first_tenant:
                        raise TenantNotFoundError("数据库中未找到租户信息")
                    tenant_id = first_tenant.id
                    # provider_name (租户id+/taimodel/taimodel)
                    provider_name = f"{tenant_id}/taimodel/taimodel"
                    
                    # 根据模型功能确定model_type
                    model_type = "llm"  # 默认值
                    if embedding:
                        model_type = "text-embedding"
                    elif rerank:
                        model_type = "rerank"
                    
                    # 创建encrypted_config JSON字符串
                    encrypted_config = json.dumps({
                        "display_name": name,
                        "endpoint_model_name": provider_model_name,
                        "api_key": api_key,
                        "endpoint_url": "https://www.taidesk.com/compatible-mode/v1",
                        "mode": "chat",
                        "vision_support": str(vision).lower(),
                        "function_call_support": str(functioncall).lower()
                    })
                    
                    # 检查ProviderModel是否存在
                    existing_provider_model = ProviderModel.query.filter_by(
                        provider_name=provider_name,
                        model_name=provider_model_name
                    ).first()
                    
                    if existing_provider_model:
                        # 更新ProviderModel
                        existing_provider_model.tenant_id = tenant_id
                        existing_provider_model.provider_name = provider_name
                        existing_provider_model.model_name = provider_model_name
                        existing_provider_model.model_type = model_type
                        existing_provider_model.encrypted_config = encrypted_config
                        existing_provider_model.is_valid = True
                    else:
                        # 创建ProviderModel
                        new_provider_model = ProviderModel(
                            id=str(uuid.uuid4()),  # 生成新的UUID作为主键
                            tenant_id=tenant_id,
                            provider_name=provider_name,
                            model_name=provider_model_name,
                            model_type=model_type,
                            encrypted_config=encrypted_config,
                            is_valid=True
                        )
                        db.session.add(new_provider_model)
                    
                    # 写入ProviderModelSetting表
                    # 检查ProviderModelSetting是否存在
                    existing_setting = ProviderModelSetting.query.filter_by(
                        tenant_id=tenant_id,
                        provider_name=provider_name,
                        model_name=provider_model_name,
                        model_type=model_type
                    ).first()
                    
                    if existing_setting:
                        # 更新ProviderModelSetting
                        existing_setting.enabled = True
                        existing_setting.load_balancing_enabled = False
                    else:
                        # 创建ProviderModelSetting
                        new_setting = ProviderModelSetting(
                            id=str(uuid.uuid4()),  # 生成新的UUID
                            tenant_id=tenant_id,
                            provider_name=provider_name,
                            model_name=provider_model_name,
                            model_type=model_type,
                            enabled=True,
                            load_balancing_enabled=False
                        )
                        db.session.add(new_setting)
                    

                    
                    db.session.commit()
                    results.append({
                        "model_id": model_id,
                        "status": "updated" if existing_provider_model else "created"
                    })
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"处理模型 {model_id} 时出错: {str(e)}")
                    results.append({
                        "model_id": model_id,
                        "status": "error",
                        "error": str(e)
                    })
            
            return results
        except Exception as e:
            db.session.rollback()
            logger.error(f"同步模型时出错: {str(e)}")
            raise
        finally:
            if db.session.is_active:
                db.session.close()
