import uuid
import json
from datetime import datetime
from typing import List, Dict, Any

from enum import StrEnum
from sqlalchemy import func
import logging
from dify_plugin.config.logger_format import plugin_logger_handler

from ..db_engine import db
from ..account_management import Tenant, TenantNotFoundError

# 使用自定义处理器设置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)


class ExternalKnowledgeManagementService:
    @staticmethod
    def validate_knowledge_data(knowledge_data: List[Dict[str, Any]]) -> List[str]:
        """
        验证知识库数据
        返回错误信息列表
        """
        errors = []
        
        if not isinstance(knowledge_data, list):
            errors.append("知识库数据必须是一个列表")
            return errors
        
        for i, item in enumerate(knowledge_data):
            if not isinstance(item, dict):
                errors.append(f"第{i+1}个知识库数据必须是一个字典")
                continue
                
            # 检查必需字段
            if "id" not in item:
                errors.append(f"第{i+1}个知识库数据缺少'id'字段")
            if "name" not in item:
                errors.append(f"第{i+1}个知识库数据缺少'name'字段")
            
            # 检查字段类型
            if "id" in item and not isinstance(item["id"], (str, int)):
                errors.append(f"第{i+1}个知识库数据'id'字段必须是字符串或数字")
            if "name" in item and not isinstance(item["name"], str):
                errors.append(f"第{i+1}个知识库数据'name'字段必须是字符串")
            if "permissions" in item and not isinstance(item["permissions"], list):
                errors.append(f"第{i+1}个知识库数据'permissions'字段必须是列表")
        
        return errors
    
    @staticmethod
    def sync_external_knowledge(client_id: str, knowledge_data: List[Dict[str, Any]], api_settings: Dict[str, Any], settings: Dict[str, Any]):
        """
        同步外部知识库数据
        输入数据字段: id、name、description、permissions
        """
        # 数据验证
        errors = ExternalKnowledgeManagementService.validate_knowledge_data(knowledge_data)
        if errors:
            raise ValueError(f"数据验证失败: {'; '.join(errors)}")
        
        results = []
        try:
            # 获取租户信息
            first_tenant = Tenant.query.first()
            if not first_tenant:
                raise TenantNotFoundError("dify还没初始化workspace")
            tenant_id = first_tenant.id
            
            # 1. 查询数据库中该租户的taidesk外部知识库API
            existing_api = ExternalKnowledgeApis.query.filter_by(
                tenant_id=tenant_id, name=f"taidesk_api_{client_id}"
            ).first()
            
            if existing_api:
                if existing_api.settings != json.dumps(api_settings):
                    existing_api.settings = json.dumps(api_settings)
                    db.session.flush()
            else:
                # 如果查询不到taidesk类型的外部知识库API，则创建一个默认的
                existing_api = ExternalKnowledgeApis(
                    id=str(uuid.uuid4()),
                    name=f"taidesk_api_{client_id}",
                    tenant_id=tenant_id,
                    settings=json.dumps(api_settings),
                    created_by=tenant_id
                )
                db.session.add(existing_api)
                db.session.flush()
            
            # 获取API ID用于后续查询
            api_id = existing_api.id
            
            # 2. 通过API查询ExternalKnowledgeBindings
            existing_bindings = ExternalKnowledgeBindings.query.filter_by(
                external_knowledge_api_id=api_id
            ).all()
            existing_binding_dict = {binding.external_knowledge_id: binding for binding in existing_bindings}
            
            # 3. 通过ExternalKnowledgeBindings查询Dataset
            # 收集所有绑定关系中的数据集ID
            dataset_ids = [binding.dataset_id for binding in existing_bindings]
            # 查询所有相关的数据集
            existing_datasets = Dataset.query.filter(
                Dataset.id.in_(dataset_ids),
                Dataset.provider == "external"
            ).all()
            # 创建以数据集ID为键的字典，便于查找
            existing_dataset_dict_by_id = {dataset.id: dataset for dataset in existing_datasets}
            
            # 创建一个字典来存储knowledge_id到dataset_id的映射关系
            knowledge_to_dataset_dict = {binding.external_knowledge_id: binding.dataset_id for binding in existing_bindings}
            
            # 处理入参数据中的知识库
            for knowledge_item in knowledge_data:
                knowledge_id = str(knowledge_item.get("id"))
                name = knowledge_item.get("name")
                description = knowledge_item.get("description")
                visible = knowledge_item.get("visible")
                # visible是1all_team_members，否则是partial_members
                permission = "all_team_members" if visible == 1 else "partial_members"
                
                # 根据ExternalKnowledgeBindings中的映射关系查找对应的数据集ID
                dataset_id = knowledge_to_dataset_dict.get(knowledge_id)
                
                if dataset_id:
                    # 如果存在映射关系，获取对应的数据集并更新
                    existing_dataset = existing_dataset_dict_by_id.get(dataset_id)
                    if existing_dataset:
                        # 更新现有数据集
                        existing_dataset.name = name  # 名称也可能会更新
                        existing_dataset.description = description
                        existing_dataset.permission = permission
                        db.session.add(existing_dataset)
                    else:
                        # 如果在数据库中找不到对应的数据集，创建新的
                        new_dataset = Dataset(
                            id=dataset_id,  # 使用已存在的dataset_id
                            tenant_id=tenant_id,
                            name=name,
                            description=description,
                            provider="external",
                            permission=permission,  # 默认权限
                            retrieval_model={"top_k": 2, "score_threshold": 0.6, "score_threshold_enabled": True},
                            created_by=tenant_id
                        )
                        db.session.add(new_dataset)
                        # 添加到字典中，便于后续查找
                        existing_dataset_dict_by_id[dataset_id] = new_dataset
                else:
                    # 如果不存在映射关系，创建新的数据集
                    new_dataset = Dataset(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        name=name,
                        description=description,
                        provider="external",
                        permission=permission,  # 默认权限
                        retrieval_model={"top_k": 2, "score_threshold": 0.6, "score_threshold_enabled": True},
                        created_by=tenant_id
                    )
                    db.session.add(new_dataset)
                    db.session.flush()  # 确保new_dataset获得ID
                    dataset_id = new_dataset.id
                    # 添加到字典中，便于后续查找
                    existing_dataset_dict_by_id[dataset_id] = new_dataset
                
                # 处理外部知识库绑定
                existing_binding = existing_binding_dict.get(knowledge_id)
                
                if existing_binding:
                    # 从字典中移除，剩余的就是需要删除的
                    del existing_binding_dict[knowledge_id]
                    results.append({"knowledge_id": knowledge_id, "status": "exist"})
                else:
                    # 创建绑定关系
                    new_binding = ExternalKnowledgeBindings(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        external_knowledge_api_id=api_id,
                        dataset_id=dataset_id,
                        external_knowledge_id=knowledge_id,
                        created_by=tenant_id
                    )
                    db.session.add(new_binding)
                    results.append({"knowledge_id": knowledge_id, "status": "created"})
            
            # 删除不再需要的绑定
            for knowledge_id, binding in existing_binding_dict.items():
                db.session.delete(binding)
                # 同时删除对应的数据集
                del_dataset = existing_dataset_dict_by_id.get(binding.dataset_id)
                if del_dataset:
                    db.session.delete(del_dataset)
                results.append({"knowledge_id": knowledge_id, "status": "deleted"})
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"同步外部知识库时出错: {str(e)}")
            raise e
        finally:
            if db.session.is_active:
                db.session.close()
        
        return results

class DatasetPermissionEnum(StrEnum):
    ONLY_ME = "only_me"
    ALL_TEAM = "all_team_members"
    PARTIAL_TEAM = "partial_members"

class ExternalKnowledgeApis(db.Model):
    __tablename__ = "external_knowledge_apis"

    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    tenant_id = db.Column(db.String(36), nullable=False)
    settings = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(36), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ExternalKnowledgeBindings(db.Model):
    __tablename__ = "external_knowledge_bindings"

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.String(36), nullable=False)
    external_knowledge_api_id = db.Column(db.String(36), nullable=False)
    dataset_id = db.Column(db.String(36), nullable=False)
    external_knowledge_id = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(36), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DatasetPermission(db.Model):
    __tablename__ = "dataset_permissions"

    id = db.Column(db.String(36), primary_key=True)
    dataset_id = db.Column(db.String(36), nullable=False)
    account_id = db.Column(db.String(36), nullable=False)
    tenant_id = db.Column(db.String(36), nullable=False)
    has_permission = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Dataset(db.Model):
    __tablename__ = "datasets"

    INDEXING_TECHNIQUE_LIST = ["high_quality", "economy", None]
    PROVIDER_LIST = ["vendor", "external", None]

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.String(36), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    provider = db.Column(db.String(255), default="vendor")
    permission = db.Column(db.String(255), default="only_me")
    data_source_type = db.Column(db.String(255), nullable=False)
    indexing_technique = db.Column(db.String(255), nullable=True)
    index_struct = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(36), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    embedding_model = db.Column(db.String(255), nullable=True)
    embedding_model_provider = db.Column(db.String(255), nullable=True)
    collection_binding_id = db.Column(db.String(36), nullable=True)
    retrieval_model = db.Column(db.JSON, nullable=True)
    built_in_field_enabled = db.Column(db.Boolean, default=False)