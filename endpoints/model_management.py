import uuid
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Mapping

from sqlalchemy import func
import logging
from dify_plugin.config.logger_format import plugin_logger_handler

from .db_engine import db
from .account_management import Tenant, TenantNotFoundError

# 使用自定义处理器设置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)

class ProviderModel(db.Model):
    __tablename__ = 'provider_models'

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.String(36), nullable=False)
    provider_name = db.Column(db.String(255), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    model_type = db.Column(db.String(40), nullable=False)
    credential_id = db.Column(db.String(36), nullable=True)  # 添加credential_id字段
    is_valid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ProviderModel(provider_name={self.provider_name}, model_name={self.model_name}, model_type={self.model_type})>'

class ProviderModelCredential(db.Model):
    __tablename__ = 'provider_model_credentials'

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.String(36), nullable=False)
    provider_name = db.Column(db.String(255), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    model_type = db.Column(db.String(40), nullable=False)
    credential_name = db.Column(db.String(255), nullable=False)
    encrypted_config = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ProviderModelCredential(model_name={self.model_name})>'

# 服务类实现
class ModelManagementService:
    @staticmethod
    def sync_models(models_data, settings: Mapping):
        """
        同步模型数据
        """
        results = []
        api_key = settings.get("api_key")
        try:
            db.session.begin()
            first_tenant = Tenant.query.first()
            if not first_tenant:
                raise TenantNotFoundError("dify还没初始化workspace")
            tenant_id = first_tenant.id
            provider_name = f"{tenant_id}/taimodel/taimodel"
            
            # 查询数据库中该提供商的所有模型
            existing_models = ProviderModel.query.filter_by(
                tenant_id=tenant_id,
                provider_name=provider_name
            ).all()
            existing_model_dict = {model.model_name: model for model in existing_models}
            
            # 处理入参数据中的模型
            for model_data in models_data:
                # 检查ProviderModel是否存在
                model_id = str(model_data.get("id"))
                code = model_data.get("code")
                provider_model_name = f"{model_id}/{code}"
                existing_provider_model = existing_model_dict.get(provider_model_name)
                
                if existing_provider_model:
                    # 如果模型已存在，从字典中删除
                    del existing_model_dict[provider_model_name]
                    results.append({"model_id": provider_model_name, "status": "existed"})
                else:
                    # 如果模型不存在，创建新记录
                    name = model_data.get("name")
                    vision = bool(model_data.get("vision", 0))
                    search = bool(model_data.get("search", 0))
                    rerank = bool(model_data.get("rerank", 0))
                    functioncall = bool(model_data.get("functioncall", 0))
                    reasoning = bool(model_data.get("reasoning", 0))
                    embedding = bool(model_data.get("embedding", 0))
                    
                    model_type = "text-generation"  # 默认值
                    if embedding:
                        model_type = "text-embedding"
                    elif rerank:
                        model_type = "rerank"
                    
                    encrypted_config = json.dumps({
                        "display_name": name,
                        "endpoint_model_name": provider_model_name,
                        "api_key": api_key,
                        "endpoint_url": "https://www.taidesk.com/compatible-mode/v1",
                        "mode": "chat",
                        "vision_support": str(vision).lower(),
                        "function_call_support": str(functioncall).lower()
                    })
                    
                    # 创建ProviderModelCredential
                    new_credential = ProviderModelCredential(
                        id=str(uuid.uuid4()),  # 生成新的UUID
                        tenant_id=tenant_id,
                        provider_name=provider_name,
                        model_name=provider_model_name,
                        model_type=model_type,
                        credential_name="taidesk_credential",
                        encrypted_config=encrypted_config
                    )
                    db.session.add(new_credential)
                    db.session.flush()  # 确保new_credential获得ID
                    
                    # 创建ProviderModel
                    new_provider_model = ProviderModel(
                        id=str(uuid.uuid4()),  # 生成新的UUID作为主键
                        tenant_id=tenant_id,
                        provider_name=provider_name,
                        model_name=provider_model_name,
                        model_type=model_type,
                        credential_id=new_credential.id,  # 关联credential_id
                        is_valid=True
                    )
                    db.session.add(new_provider_model)
                    results.append({"model_id": provider_model_name, "status": "created"})
            
            # 收集需要删除的模型
            models_to_delete = []
            credentials_to_delete = []
            
            if existing_model_dict:
                models_to_delete = list(existing_model_dict.values())
                credential_ids_to_delete = [model.credential_id for model in models_to_delete if model.credential_id]
                if credential_ids_to_delete:
                    credentials_to_delete = ProviderModelCredential.query.filter(
                        ProviderModelCredential.id.in_(credential_ids_to_delete)
                    ).all()
                
                # 批量删除收集到的模型和凭证
                for credential in credentials_to_delete:
                    db.session.delete(credential)
                for model in models_to_delete:
                    db.session.delete(model)
                
                # 添加删除结果到返回列表
                for provider_model_name in existing_model_dict.keys():
                    results.append({"model_id": provider_model_name, "status": "deleted"})
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"同步模型时出错: {str(e)}")
            raise e
        finally:
            if db.session.is_active:
                db.session.close()
        return results
