"""
配置管理系统 - 基于环境变量的简化版本
"""
import uuid
import base64
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import AliasChoices, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from models import IMAConfig, IMAStatus


class AppConfig(BaseSettings):
    """应用配置 - 从环境变量读取"""
    # 服务配置
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8081
    mcp_debug: bool = False
    mcp_log_level: str = "INFO"
    mcp_log_file: Optional[str] = None
    mcp_secret_key: str = "default-secret-key-change-in-production"
    mcp_server_name: str = "ima-copilot"
    mcp_server_version: str = "0.2.0"

    # IMA API 配置
    api_endpoint: str = "https://ima.qq.com/cgi-bin/assistant/qa"
    request_timeout: int = 30
    retry_count: int = 3
    ask_concurrency_limit: int = 1
    proxy: Optional[str] = None

    model_config = SettingsConfigDict(
        env_prefix="IMA_",
        env_file=".env",
        extra="ignore"  # 忽略额外的字段
    )

    @property
    def host(self) -> str:
        return self.mcp_host

    @property
    def port(self) -> int:
        return self.mcp_port

    @property
    def debug(self) -> bool:
        return self.mcp_debug

    @property
    def log_level(self) -> str:
        return self.mcp_log_level

    @property
    def log_file(self) -> Optional[str]:
        return self.mcp_log_file

    @property
    def secret_key(self) -> str:
        return self.mcp_secret_key


class IMAEnvironmentConfig(BaseSettings):
    """IMA 认证配置 - 从环境变量读取"""
    # IMA 认证信息
    cookies: str = ""
    x_ima_cookie: str = ""
    x_ima_bkn: str = ""
    
    # 默认配置常量
    DEFAULT_KNOWLEDGE_BASE_ID: str = "7305806844290061"
    DEFAULT_ROBOT_TYPE: int = 5
    DEFAULT_SCENE_TYPE: int = 1
    DEFAULT_MODEL_TYPE: int = 4

    knowledge_base_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices(
            "IMA_KNOWLEDGE_BASE_ID",
            "knowledgeBaseId",
        ),
    )
    knowledge_base_ids: Optional[str] = Field(
        None,
        validation_alias=AliasChoices(
            "IMA_KNOWLEDGE_BASE_IDS",
            "knowledgeBaseIds",
        ),
    )
    uskey: Optional[str] = None
    client_id: Optional[str] = None
    robot_type: int = DEFAULT_ROBOT_TYPE
    scene_type: int = DEFAULT_SCENE_TYPE
    model_type: int = DEFAULT_MODEL_TYPE

    model_config = SettingsConfigDict(
        env_prefix="IMA_",
        env_file=".env",
        extra="ignore"  # 忽略额外的字段
    )


class ConfigManager:
    """简化的配置管理器 - 基于环境变量"""

    def __init__(self):
        self.app_config = AppConfig()
        self.env_config = IMAEnvironmentConfig()
        self._ima_config: Optional[IMAConfig] = None

    def update_auth(
        self,
        x_ima_cookie: str,
        x_ima_bkn: str,
        cookies: str = "",
    ) -> bool:
        """运行时更新认证信息并持久化到 .env

        Args:
            x_ima_cookie: 捕获的 x-ima-cookie 值
            x_ima_bkn: 捕获的 x-ima-bkn 值
            cookies: 浏览器 cookies 字符串（可选）

        Returns:
            更新是否成功
        """
        try:
            # 1. 更新环境配置
            self.env_config.x_ima_cookie = x_ima_cookie
            self.env_config.x_ima_bkn = x_ima_bkn
            if cookies:
                self.env_config.cookies = cookies

            # 2. 重新加载 IMAConfig
            self._ima_config = None
            config = self.get_config()
            if not config:
                logger.error("update_auth: 重新加载配置失败")
                return False

            # 3. 强制覆盖核心字段（确保新值生效）
            config.x_ima_cookie = x_ima_cookie
            config.x_ima_bkn = x_ima_bkn
            if cookies:
                config.cookies = cookies
            # 重置 token 状态，让后续请求自动刷新
            config.current_token = None
            config.token_updated_at = None
            config.token_valid_time = None
            config.updated_at = datetime.now()

            # 4. 写入 .env 文件持久化
            self._write_env_file(x_ima_cookie, x_ima_bkn, cookies)

            logger.info("✅ 认证信息已更新并持久化")
            return True

        except Exception as e:
            logger.error(f"更新认证配置失败: {e}")
            return False

    def update_knowledge_base(
        self,
        knowledge_base_id: Optional[str] = None,
        knowledge_base_ids: Optional[list[str]] = None,
    ) -> bool:
        """更新知识库配置并持久化到 .env

        Args:
            knowledge_base_id: 默认知识库 ID（单知识库模式）
            knowledge_base_ids: 多知识库 ID 列表

        Returns:
            更新是否成功
        """
        try:
            # 更新环境配置
            if knowledge_base_id:
                self.env_config.knowledge_base_id = knowledge_base_id
            if knowledge_base_ids is not None:
                self.env_config.knowledge_base_ids = ",".join(knowledge_base_ids)

            # 重置 IMAConfig 以便下次 get_config 重新加载
            self._ima_config = None

            # 写入 .env 文件
            self._write_env_kb(knowledge_base_id, knowledge_base_ids)

            logger.info("✅ 知识库配置已更新并持久化")
            return True

        except Exception as e:
            logger.error(f"更新知识库配置失败: {e}")
            return False

    def _write_env_file(
        self,
        x_ima_cookie: str,
        x_ima_bkn: str,
        cookies: str = "",
    ) -> None:
        """将认证信息写入 .env 文件"""
        from pathlib import Path

        env_path = Path(__file__).parent.parent / ".env"
        lines: list[str] = []

        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        updates = {
            "IMA_X_IMA_COOKIE": x_ima_cookie,
            "IMA_X_IMA_BKN": x_ima_bkn,
        }
        if cookies:
            updates["IMA_COOKIES"] = cookies

        updated_keys: set[str] = set()
        new_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            matched = False
            for key, value in updates.items():
                if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                    new_lines.append(f'{key}="{value}"')
                    updated_keys.add(key)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        # 追加尚未存在的 key
        for key, value in updates.items():
            if key not in updated_keys:
                new_lines.append(f'{key}="{value}"')

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info(f"✅ .env 已更新: {env_path}")

    def _write_env_kb(
        self,
        knowledge_base_id: Optional[str] = None,
        knowledge_base_ids: Optional[list[str]] = None,
    ) -> None:
        """将知识库配置写入 .env 文件"""
        from pathlib import Path

        env_path = Path(__file__).parent.parent / ".env"
        lines: list[str] = []

        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        updates: Dict[str, str] = {}
        if knowledge_base_id:
            updates["IMA_KNOWLEDGE_BASE_ID"] = knowledge_base_id
        if knowledge_base_ids is not None:
            updates["IMA_KNOWLEDGE_BASE_IDS"] = ",".join(knowledge_base_ids)

        if not updates:
            return

        updated_keys: set[str] = set()
        new_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            matched = False
            for key, value in updates.items():
                if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                    new_lines.append(f'{key}="{value}"')
                    updated_keys.add(key)
                    matched = True
                    break
                # 也处理被注释的行
                if stripped.startswith(f"# {key}=") or stripped.startswith(f"#{key}="):
                    new_lines.append(f'{key}="{value}"')
                    updated_keys.add(key)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        # 追加尚未存在的 key
        for key, value in updates.items():
            if key not in updated_keys:
                new_lines.append(f'{key}="{value}"')

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info(f"✅ .env 知识库配置已更新: {env_path}")

    def _generate_missing_params(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """自动生成缺失的参数"""
        # 生成client_id（如果缺失）
        if not config_data.get('client_id'):
            config_data['client_id'] = str(uuid.uuid4())
            logger.info(f"Generated client_id: {config_data['client_id']}")

        # 生成uskey（如果缺失）
        if not config_data.get('uskey'):
            random_bytes = secrets.token_bytes(32)
            config_data['uskey'] = base64.b64encode(random_bytes).decode('utf-8')
            logger.info("Generated uskey: 32-byte random string")

        # 确保created_at存在
        if not config_data.get('created_at'):
            config_data['created_at'] = datetime.now()
            logger.info("Set created_at to current time")

        return config_data

    @staticmethod
    def _parse_knowledge_base_ids(raw_value: Optional[str]) -> List[str]:
        if not raw_value:
            return []

        parsed_ids: List[str] = []
        for item in raw_value.split(","):
            candidate = item.strip()
            if candidate and candidate not in parsed_ids:
                parsed_ids.append(candidate)

        return parsed_ids

    def load_config(self, auto_generate: bool = True) -> Optional[IMAConfig]:
        """从环境变量加载配置"""
        try:
            configured_single_kb_id = (self.env_config.knowledge_base_id or "").strip()
            configured_single_kb_ids = self._parse_knowledge_base_ids(configured_single_kb_id)
            configured_multi_kb_ids = self._parse_knowledge_base_ids(self.env_config.knowledge_base_ids)

            if configured_single_kb_id and len(configured_single_kb_ids) == 1:
                resolved_kb_id = configured_single_kb_id
                resolved_kb_ids = [configured_single_kb_id]
            elif len(configured_single_kb_ids) > 1 and not configured_multi_kb_ids:
                logger.warning(
                    "检测到 IMA_KNOWLEDGE_BASE_ID 包含多个值，将按多知识库模式处理；"
                    "建议改用 IMA_KNOWLEDGE_BASE_IDS"
                )
                resolved_kb_id = configured_single_kb_ids[0]
                resolved_kb_ids = configured_single_kb_ids
            elif configured_multi_kb_ids:
                resolved_kb_id = configured_multi_kb_ids[0]
                resolved_kb_ids = configured_multi_kb_ids
            else:
                resolved_kb_id = self.env_config.DEFAULT_KNOWLEDGE_BASE_ID
                resolved_kb_ids = [resolved_kb_id]

            # 从环境变量获取配置数据
            config_data = {
                'cookies': self.env_config.cookies,
                'x_ima_cookie': self.env_config.x_ima_cookie,
                'x_ima_bkn': self.env_config.x_ima_bkn,
                'knowledge_base_id': resolved_kb_id,
                'knowledge_base_ids': resolved_kb_ids,
                'uskey': self.env_config.uskey,
                'client_id': self.env_config.client_id,
                'robot_type': self.env_config.robot_type or self.env_config.DEFAULT_ROBOT_TYPE,
                'scene_type': self.env_config.scene_type or self.env_config.DEFAULT_SCENE_TYPE,
                'model_type': self.env_config.model_type or self.env_config.DEFAULT_MODEL_TYPE,
                'timeout': self.app_config.request_timeout,
                'retry_count': self.app_config.retry_count,
                'ask_concurrency_limit': max(1, self.app_config.ask_concurrency_limit),
                'proxy': self.app_config.proxy,
                'created_at': datetime.now()
            }

            # 自动生成缺失的参数
            if auto_generate:
                config_data = self._generate_missing_params(config_data)

            # 验证并创建配置对象
            self._ima_config = IMAConfig(**config_data)
            logger.info("Configuration loaded from environment variables successfully")
            return self._ima_config

        except ValidationError as e:
            logger.error(f"Configuration validation failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error loading config: {e}")
            return None

    def get_config(self) -> Optional[IMAConfig]:
        """获取当前配置"""
        if self._ima_config is None:
            self._ima_config = self.load_config()
        return self._ima_config

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """验证环境变量配置"""
        # 必需认证信息：X-Ima-Cookie 和 X-Ima-Bkn
        required_fields = [
            (self.env_config.x_ima_cookie, "IMA_X_IMA_COOKIE"),
            (self.env_config.x_ima_bkn, "IMA_X_IMA_BKN")
        ]

        for value, name in required_fields:
            if not value or value.strip() == "":
                return False, f"Missing required environment variable: {name}"

        single_kb_ids = self._parse_knowledge_base_ids((self.env_config.knowledge_base_id or "").strip())
        multi_kb_ids = self._parse_knowledge_base_ids(self.env_config.knowledge_base_ids)

        if not single_kb_ids and not multi_kb_ids:
            return False, "Missing required environment variable: IMA_KNOWLEDGE_BASE_ID or IMA_KNOWLEDGE_BASE_IDS"

        return True, None

    def get_config_status(self) -> IMAStatus:
        """获取配置状态"""
        status = IMAStatus()

        # 验证环境变量配置
        is_valid, error = self.validate_config()
        if is_valid:
            config = self.get_config()
            if config:
                status.is_configured = True
                status.session_info = {
                    'client_id': config.client_id,
                    'knowledge_base_id': config.knowledge_base_id,
                    'knowledge_base_ids': config.knowledge_base_ids,
                    'created_at': config.created_at.isoformat(),
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None,
                }
        else:
            status.error_message = error or "环境变量配置不完整"

        return status


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> Optional[IMAConfig]:
    """获取全局配置"""
    return config_manager.get_config()


def get_app_config() -> AppConfig:
    """获取应用配置"""
    return config_manager.app_config
