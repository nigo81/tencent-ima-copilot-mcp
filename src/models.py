"""
数据模型定义
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl, field_serializer, ConfigDict
from enum import Enum


class MessageType(str, Enum):
    """IMA 响应消息类型"""
    SYSTEM = "system"
    RAW = "raw"
    TEXT = "text"
    KNOWLEDGE_BASE = "knowledgeBase"


class DeviceInfo(BaseModel):
    """设备信息模型"""
    uskey: str
    uskey_bus_infos_input: str


class IMAMessage(BaseModel):
    """IMA 响应消息模型"""
    type: MessageType
    content: str
    raw: Optional[str] = None


class KnowledgeBaseInfo(BaseModel):
    """知识库信息"""
    id: str
    name: str
    logo: Optional[HttpUrl] = None
    introduction: Optional[str] = None
    description: Optional[str] = None
    creator_name: Optional[str] = None
    permission_type: Optional[int] = None


class MediaInfo(BaseModel):
    """媒体信息模型"""
    id: str
    type: int
    title: str
    subtitle: Optional[str] = None
    introduction: Optional[str] = None
    logo: Optional[HttpUrl] = None
    cover: Optional[HttpUrl] = None
    jump_url: Optional[str] = None
    jump_url_info: Optional[Dict[str, Any]] = None
    timestamp: Optional[int] = None
    index: Optional[int] = None
    publisher: Optional[str] = None
    tips: Optional[str] = None
    role_type: Optional[int] = None
    permission_info: Optional[Dict[str, Any]] = None
    source_type: Optional[int] = None
    knowledge_base_info: Optional[KnowledgeBaseInfo] = None


class KnowledgeBaseMessage(IMAMessage):
    """知识库消息模型"""
    content: str = ""  # 知识库搜索状态描述
    processing: Optional[str] = None
    stage: Optional[int] = None
    medias: Optional[List[MediaInfo]] = None


class TextMessage(IMAMessage):
    """文本消息模型"""
    text: str


class IMAResponse(BaseModel):
    """IMA API 完整响应模型"""
    code: int = 0
    msg: str = ""
    msg_seq_id: str
    support_mind_map: bool = False
    intent_report_id: Optional[Dict[str, int]] = None
    debug_profile: Optional[Dict[str, Any]] = None
    qa_permission: Optional[Dict[str, Any]] = None


class TokenRefreshRequest(BaseModel):
    """Token刷新请求模型"""
    user_id: str
    refresh_token: str
    token_type: int = 14


class TokenRefreshResponse(BaseModel):
    """Token刷新响应模型"""
    code: int
    msg: str
    token: Optional[str] = None
    token_valid_time: Optional[str] = None
    user_id: Optional[str] = None


# --- init_session Models ---

class KnowledgeBaseInfoWithFolder(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    knowledge_base_id: str = Field(..., alias="knowledgeBaseId")
    folder_ids: List[str] = Field(default_factory=list, alias="folderIds")


class EnvInfo(BaseModel):
    robotType: int
    interactType: int = 0


class InitSessionRequest(BaseModel):
    envInfo: EnvInfo
    byKeyword: Optional[str] = None
    relatedUrl: str
    sceneType: int
    msgsLimit: int = 10
    forbidAutoAddToHistoryList: bool = True
    knowledgeBaseInfoWithFolder: KnowledgeBaseInfoWithFolder


class SessionInfo(BaseModel):
    id: str
    by_knowledge_base_id: Optional[str] = None
    cover_url: Optional[str] = None
    create_ts: Optional[str] = None
    get_msgs_last_ts: Optional[str] = None
    interact_type: Optional[int] = None
    is_msgs_end: Optional[bool] = None
    knowledge_base_info_with_folder: Optional[KnowledgeBaseInfoWithFolder] = None
    medias: Optional[List[Any]] = None
    mission_task_id: Optional[str] = None
    msgs: Optional[List[Any]] = None
    name: Optional[str] = None
    related_content: Optional[str] = None
    related_url: Optional[str] = None
    robot_type: Optional[int] = None
    scene_type: Optional[int] = None
    session_type: Optional[int] = None
    update_ts: Optional[str] = None


class InitSessionResponse(BaseModel):
    code: int
    msg: str
    session_id: Optional[str] = None
    session_info: Optional[SessionInfo] = None
    attach_task_infos: Optional[List[Any]] = None
    by_keyword: Optional[str] = None
    child_sessions: Optional[List[Any]] = None
    cos_credential: Optional[Any] = None
    knowledge_base_info: Optional[Any] = None
    preview_url: Optional[str] = None


class IMAConfig(BaseModel):
    """IMA 配置模型"""
    model_config = ConfigDict(validate_default=True)

    # 基础认证信息
    cookies: Optional[str] = Field(None, description="完整的 Cookie 字符串（可选）")
    x_ima_cookie: str = Field(..., description="X-Ima-Cookie Header 值")
    x_ima_bkn: str = Field(..., description="X-Ima-Bkn Header 值")

    # 核心参数
    knowledge_base_id: str = Field(..., description="知识库ID")
    knowledge_base_ids: List[str] = Field(default_factory=list, description="可用知识库ID列表")

    # 设备信息
    uskey: Optional[str] = Field(None, description="设备 uskey（动态生成，暂时可选）")
    client_id: str = Field(..., description="客户端 ID")

    # Token刷新相关
    user_id: Optional[str] = Field(None, description="用户ID，用于token刷新")
    refresh_token: Optional[str] = Field(None, description="刷新令牌")
    current_token: Optional[str] = Field(None, description="当前访问令牌")
    token_valid_time: Optional[int] = Field(None, description="令牌有效时间（秒）")
    token_updated_at: Optional[datetime] = Field(None, description="令牌更新时间")

    # 可选行为参数
    robot_type: int = Field(5, description="机器人类型")
    scene_type: int = Field(1, description="场景类型")
    model_type: int = Field(4, description="模型类型")

    # 可选配置
    proxy: Optional[str] = Field(None, description="代理设置")
    timeout: int = Field(30, description="请求超时时间（秒）")
    retry_count: int = Field(3, description="重试次数")
    ask_concurrency_limit: int = Field(1, description="问答并发上限")
    enable_raw_logging: bool = Field(False, description="Enable writing raw SSE responses to disk")
    raw_log_dir: Optional[str] = Field(None, description="Directory for raw SSE logs")
    raw_log_max_bytes: int = Field(1048576, description="Maximum bytes saved per raw response")
    raw_log_on_success: bool = Field(False, description="Save raw response even when successful")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value: Optional[datetime]) -> Optional[str]:
        """序列化 datetime 为 ISO 格式字符串"""
        return value.isoformat() if value else None

    def is_complete(self) -> bool:
        """检查配置是否完整（包含所有必需字段）"""
        return bool(
            self.x_ima_cookie and
            self.x_ima_bkn and
            self.client_id
        )


class IMAStatus(BaseModel):
    """IMA 状态模型"""
    is_configured: bool = False
    is_authenticated: bool = False
    last_test_time: Optional[datetime] = None
    error_message: Optional[str] = None
    session_info: Optional[Dict[str, Any]] = None


class KnowledgeQaInfo(BaseModel):
    tags: List[str] = Field(default_factory=list)
    knowledge_ids: List[str] = Field(default_factory=list)
    media_id_infos: List[Dict[str, Any]] = Field(default_factory=list)


class CommandInfo(BaseModel):
    type: int
    knowledge_qa_info: KnowledgeQaInfo


class ModelInfo(BaseModel):
    model_type: int
    enable_enhancement: bool


class HistoryInfo(BaseModel):
    # This seems to be an empty object, define it as such for now
    pass


class AskQuestionRequest(BaseModel):
    session_id: str
    robot_type: int
    question: str
    question_type: int
    client_id: str
    command_info: CommandInfo
    model_info: ModelInfo
    history_info: HistoryInfo
    device_info: DeviceInfo
    client_tools: List[Any] = Field(default_factory=list)
