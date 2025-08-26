import json
import traceback
from typing import Mapping
from werkzeug import Request, Response
from dify_plugin import Endpoint
from .database_config import DatabaseConfig
from .db_engine import db, init_db
from .account_management import AccountManagementService
from .model_management import ModelManagementService
from flask import Flask


class TaideskEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Invokes the endpoint with the given request.
        Supports different operation types via the 'type' field in request body.
        """
        data = r.get_json()
        operation_type = data.get("type")
        # 打印数据库信息
        # config = DatabaseConfig()
        # config_dict = {
        #     "db_host": config.DB_HOST,
        #     "db_port": config.DB_PORT,
        #     "db_username": config.DB_USERNAME,
        #     "db_database": config.DB_DATABASE,
        #     "db_charset": config.DB_CHARSET,
        #     "db_password": config.DB_PASSWORD,
        #     "sqlalchemy_database_uri": config.SQLALCHEMY_DATABASE_URI,
        #     "sqlalchemy_pool_size": config.SQLALCHEMY_POOL_SIZE,
        #     "sqlalchemy_max_overflow": config.SQLALCHEMY_MAX_OVERFLOW
        # }
        # # 控制台输出config_dict
        # print("数据库配置信息:")
        # print(json.dumps(config_dict, indent=2, ensure_ascii=False))
        # # 打印settings
        # print("settings:")
        # print(json.dumps(settings, indent=2, ensure_ascii=False))
        # print("settings['api_key']:")
        # print(settings['api_key'])
        

        try:
            # 确保数据库已初始化
            try:
                # 检查db是否已经与app关联
                if db.app is None:
                    app = Flask(__name__)
                    init_db(app)
            except AttributeError:
                # 如果db.app属性不存在，则创建新app并初始化
                app = Flask(__name__)
                init_db(app)
            if operation_type == "sync":
                """
                {
                    "data": [
                        {
                            "realName": "铁山上",
                            "phone": "18626319712",
                            "tenantId": "000000",
                            "admin": true,
                            "id": 1894205628412559361,
                            "avatar": "https://demo.devlake.thclouds.com:17443/oss-file/000000-cmp/20250317/57f5ef589378b5bae7482ba38b67c92c.jpg"
                        },
                        {
                            "realName": "dany",
                            "phone": "13004594323",
                            "tenantId": "000000",
                            "roleName": null,
                            "id": 1894206292895170561
                        }
                    ],
                    "type": "sync"
                }
                """
                # 全量同步操作，同步用户数据
                try:
                    sync_data = data.get("data", [])
                    
                    with app.app_context():
                        results = AccountManagementService.sync_accounts(sync_data)
                    
                    return Response(
                        response=json.dumps({
                            "status": "success",
                            "sync_count": len(sync_data)
                        }),
                        status=200,
                        content_type="application/json"
                    )
                except Exception as e:
                    print(f"同步账户异常: {str(e)}")
                    print(f"异常堆栈:{traceback.format_exc()}")
                    return Response(
                        response=json.dumps({"error": str(e)}),
                        status=500,
                        content_type="application/json"
                    )
            elif operation_type == "account_create":
                # 创建账户
                try:
                    result = AccountManagementService.create_account(
                        email=data['email'],
                        name=data['name'],
                        interface_language=data.get('interface_language', 'en-US'),
                        password=data.get('password'),
                        interface_theme=data.get('interface_theme', 'light'),
                        role=data.get('role', 'editor'),
                        tenant_id=data.get('tenant_id')
                    )
                    return Response(
                        response=json.dumps({"status": "success", "data": result}),
                        status=201,
                        content_type="application/json"
                    )
                except Exception as e:
                    print(f"创建账户异常: {str(e)}")
                    return Response(
                        response=json.dumps({"error": str(e)}),
                        status=400,
                        content_type="application/json"
                    )
            elif operation_type == "account_update":
                # 更新账户
                try:
                    email = data['email']
                    name = data.get('name')
                    new_email = data.get('new_email')
                    interface_language = data.get('interface_language')
                    interface_theme = data.get('interface_theme')
                    role = data.get('role')
                    tenant_id = data.get('tenant_id')
                    
                    result = AccountManagementService.update_account(
                        email=email,
                        name=name,
                        new_email=new_email,
                        interface_language=interface_language,
                        interface_theme=interface_theme,
                        role=role,
                        tenant_id=tenant_id
                    )
                    return Response(
                        response=json.dumps({"status": "success", "data": result}),
                        status=200,
                        content_type="application/json"
                    )
                except Exception as e:
                    print(f"更新账户异常: {str(e)}")
                    return Response(
                        response=json.dumps({"error": str(e)}),
                        status=400,
                        content_type="application/json"
                    )
            elif operation_type == "account_delete":
                # 删除账户
                try:
                    email = data['email']
                    result = AccountManagementService.delete_account(email)
                    return Response(
                        response=json.dumps({"status": "success", "data": result}),
                        status=200,
                        content_type="application/json"
                    )
                except Exception as e:
                    print(f"删除账户异常: {str(e)}")
                    return Response(
                        response=json.dumps({"error": str(e)}),
                        status=400,
                        content_type="application/json"
                    )
            elif operation_type == "get":
                # 获取所有账户
                try:

                    with app.app_context():
                        result = AccountManagementService.get_all_accounts()
                    return Response(
                        response=json.dumps({"status": "success", "data": result}),
                        status=200,
                        content_type="application/json"
                    )
                except Exception as e:
                    print(f"get异常: {str(e)}")
                    return Response(
                        response=json.dumps({"error": str(e)}),
                        status=500,
                        content_type="application/json"
                    )
            elif operation_type == "models":
                # 同步模型
                try:
                    models_data = data.get("data", [])
                     
                    with app.app_context():
                        results = ModelManagementService.sync_models(models_data, settings)
                     
                    return Response(
                        response=json.dumps({
                            "status": "success",
                            "sync_count": len(models_data),
                            "results": results
                        }),
                        status=200,
                        content_type="application/json"
                    )
                except Exception as e:
                    print(f"同步模型异常: {str(e)}")
                    print(f"异常堆栈:{traceback.format_exc()}")
                    return Response(
                        response=json.dumps({"error": str(e)}),
                        status=500,
                        content_type="application/json"
                    )
            else:
                return Response(
                    response=json.dumps({"error": f"Unsupported operation type: {operation_type}"}),
                    status=400,
                    content_type="application/json"
                )
        except Exception as e:
            print(f"总异常: {str(e)}")
            print(f"异常堆栈:\n{traceback.format_exc()}")
            return Response(
                response=json.dumps({"error": str(e)}),
                status=500,
                content_type="application/json"
            )

