"""
资源管理器抽象层

提供统一的外部资源管理接口，支持多种资源类型：
- 图片（ComfyUI、Stable Diffusion 等）
- 视频（未来扩展）
- 音频（未来扩展）

设计原则：
1. 接口统一：所有资源生成器实现相同的接口
2. 可扩展：轻松添加新的资源类型和生成器
3. 异步优先：所有操作都是异步的
4. 错误容忍：生成失败不应影响主流程
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """资源类型枚举"""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class ResourceGeneratorStatus(str, Enum):
    """资源生成器状态"""
    AVAILABLE = "available"      # 可用
    UNAVAILABLE = "unavailable"  # 不可用
    ERROR = "error"              # 错误状态


class BaseResourceGenerator(ABC):
    """
    资源生成器抽象基类
    
    所有外部资源生成器都应继承此类
    """
    
    def __init__(self, generator_name: str, resource_type: ResourceType):
        """
        初始化生成器
        
        Args:
            generator_name: 生成器名称（如 "comfyui", "stable_diffusion"）
            resource_type: 资源类型
        """
        self.generator_name = generator_name
        self.resource_type = resource_type
        self.status = ResourceGeneratorStatus.UNAVAILABLE
    
    @abstractmethod
    async def initialize(self) -> bool:
        """
        初始化生成器（如检查 MCP 服务器连接）
        
        Returns:
            bool: 初始化成功返回 True
        """
        pass
    
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> Optional[List[str]]:
        """
        生成资源
        
        Args:
            prompt: 生成提示词
            **kwargs: 额外参数（不同生成器可能需要不同参数）
        
        Returns:
            List[str] | None: 生成的资源 URL 列表，失败返回 None
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            dict: {
                "status": "available" | "unavailable" | "error",
                "message": "状态描述",
                "details": {...}  # 额外信息
            }
        """
        pass
    
    def is_available(self) -> bool:
        """检查生成器是否可用"""
        return self.status == ResourceGeneratorStatus.AVAILABLE


class ComfyUIImageGenerator(BaseResourceGenerator):
    """
    ComfyUI 图片生成器
    
    通过 MCP 工具调用 ComfyUI 生成图片
    """
    
    def __init__(self):
        super().__init__("comfyui", ResourceType.IMAGE)
        self.mcp_server_name = "comfyui"  # MCP 服务器名称
        self.mcp_tool_name = "generate_image_comfyui"  # MCP 工具名称
    
    async def initialize(self) -> bool:
        """
        初始化 ComfyUI 生成器
        
        检查 MCP 服务器是否可用
        """
        try:
            from ..mcp.manager import mcp_manager
            
            # 检查 MCP 服务器是否已注册
            health = await mcp_manager.health_check()
            servers = health.get("servers", {})
            
            if self.mcp_server_name in servers:
                server_status = servers[self.mcp_server_name].get("status")
                if server_status == "running":
                    self.status = ResourceGeneratorStatus.AVAILABLE
                    logger.info(f"✅ {self.generator_name} 生成器初始化成功")
                    return True
            
            logger.warning(f"⚠️ {self.mcp_server_name} MCP 服务器未找到或未运行")
            self.status = ResourceGeneratorStatus.UNAVAILABLE
            return False
            
        except Exception as e:
            logger.error(f"❌ {self.generator_name} 生成器初始化失败: {e}")
            self.status = ResourceGeneratorStatus.ERROR
            return False
    
    async def generate(self, prompt: str, **kwargs) -> Optional[List[str]]:
        """
        生成图片
        
        Args:
            prompt: 图片描述提示词
            **kwargs: 额外参数
                - workflow: 工作流名称（默认 "text2img"）
                - width: 图片宽度
                - height: 图片高度
                - ...其他 ComfyUI 参数
        
        Returns:
            List[str] | None: 图片 URL 列表
        """
        if not self.is_available():
            logger.warning(f"⚠️ {self.generator_name} 生成器不可用，跳过图片生成")
            return None
        
        try:
            from ..mcp.manager import mcp_manager
            
            # 构建参数
            arguments = {
                "prompt": prompt,
                "workflow": kwargs.get("workflow", "text2img"),
                **kwargs
            }
            
            # 调用 MCP 工具
            logger.info(f"🎨 调用 {self.generator_name} 生成图片: {prompt[:50]}...")
            result = await mcp_manager.call_tool(
                server_name=self.mcp_server_name,
                tool_name=self.mcp_tool_name,
                arguments=arguments
            )
            
            # 提取图片 URL
            image_urls = []
            for item in result.get("content", []):
                if item.get("type") == "resource":
                    url = item.get("resource", {}).get("uri")
                    if url:
                        image_urls.append(url)
            
            if image_urls:
                logger.info(f"✅ 成功生成 {len(image_urls)} 张图片")
                return image_urls
            else:
                logger.warning(f"⚠️ {self.generator_name} 未返回图片")
                return None
                
        except Exception as e:
            logger.error(f"❌ {self.generator_name} 生成图片失败: {e}")
            return None
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            from ..mcp.manager import mcp_manager
            health = await mcp_manager.health_check()
            servers = health.get("servers", {})
            
            if self.mcp_server_name in servers:
                server_info = servers[self.mcp_server_name]
                return {
                    "status": "available" if server_info.get("status") == "running" else "unavailable",
                    "message": f"{self.generator_name} 服务运行正常",
                    "details": server_info
                }
            
            return {
                "status": "unavailable",
                "message": f"{self.mcp_server_name} MCP 服务器未找到",
                "details": {}
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"健康检查失败: {str(e)}",
                "details": {}
            }


class ResourceManager:
    """
    资源管理器
    
    统一管理所有资源生成器，提供统一的资源生成接口
    """
    
    def __init__(self):
        self._generators: Dict[str, BaseResourceGenerator] = {}
        self._initialized = False
    
    async def initialize(self):
        """
        初始化所有资源生成器
        
        会尝试初始化所有已注册的生成器，失败的生成器会被标记为不可用
        """
        if self._initialized:
            logger.info("⚠️ 资源管理器已初始化，跳过")
            return
        
        logger.info("🎨 正在初始化资源管理器...")
        
        # 注册 ComfyUI 图片生成器
        comfyui = ComfyUIImageGenerator()
        self._generators["comfyui_image"] = comfyui
        
        # 初始化所有生成器
        for name, generator in self._generators.items():
            try:
                await generator.initialize()
                logger.info(f"  - {name}: {generator.status.value}")
            except Exception as e:
                logger.error(f"  - {name}: 初始化失败 ({e})")
        
        self._initialized = True
        logger.info("✅ 资源管理器初始化完成")
    
    def register_generator(self, name: str, generator: BaseResourceGenerator):
        """
        注册自定义资源生成器
        
        Args:
            name: 生成器唯一标识
            generator: 生成器实例
        """
        self._generators[name] = generator
        logger.info(f"✅ 注册资源生成器: {name}")
    
    async def generate_image(
        self, 
        prompt: str, 
        generator_name: str = "comfyui_image",
        **kwargs
    ) -> Optional[List[str]]:
        """
        生成图片（统一接口）
        
        Args:
            prompt: 图片描述
            generator_name: 使用的生成器（默认 comfyui）
            **kwargs: 额外参数
        
        Returns:
            List[str] | None: 图片 URL 列表
        """
        generator = self._generators.get(generator_name)
        
        if not generator:
            logger.warning(f"⚠️ 生成器 {generator_name} 不存在")
            return None
        
        if not generator.is_available():
            logger.warning(f"⚠️ 生成器 {generator_name} 不可用")
            return None
        
        return await generator.generate(prompt, **kwargs)
    
    async def health_check(self) -> Dict[str, Any]:
        """
        获取所有生成器的健康状态
        
        Returns:
            dict: {
                "initialized": bool,
                "generators": {
                    "generator_name": {
                        "status": "available" | "unavailable" | "error",
                        "message": "...",
                        "details": {...}
                    }
                }
            }
        """
        generators_health = {}
        
        for name, generator in self._generators.items():
            generators_health[name] = await generator.health_check()
        
        return {
            "initialized": self._initialized,
            "generators": generators_health
        }
    
    def get_available_generators(self, resource_type: Optional[ResourceType] = None) -> List[str]:
        """
        获取可用的生成器列表
        
        Args:
            resource_type: 过滤资源类型（可选）
        
        Returns:
            List[str]: 可用生成器名称列表
        """
        available = []
        for name, generator in self._generators.items():
            if resource_type and generator.resource_type != resource_type:
                continue
            if generator.is_available():
                available.append(name)
        return available


# 全局单例
_resource_manager: Optional[ResourceManager] = None


async def get_resource_manager() -> ResourceManager:
    """获取资源管理器单例"""
    global _resource_manager
    
    if _resource_manager is None:
        _resource_manager = ResourceManager()
        await _resource_manager.initialize()
    
    return _resource_manager

