"""
朋友圈（Moment）工具

AI 可以使用此工具安排发布朋友圈、评论朋友圈、点赞朋友圈等
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import random
import uuid
import logging

from ..base import BaseTool, ToolMetadata, ToolContext
from ...config import settings

logger = logging.getLogger(__name__)


class ScheduleMomentTool(BaseTool):
    """安排发布朋友圈工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """
        获取工具元数据
        
        Args:
            context: 工具上下文（不需要）
        """
        return ToolMetadata(
            name="schedule_moment",
            description="""使用该工具可以让你所扮演的角色或者作为大模型本质的你发布自己的朋友圈内容（注意：这是你自己的朋友圈，不是用户的朋友圈）。""".strip(),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "朋友圈文字内容（必填）"
                    },
                    "delay_minutes": {
                        "type": "integer",
                        "description": "延迟发布时间（分钟）。0=立即发布，30=30分钟后，60=1小时后。不设置则随机 15-120 分钟"
                    },
                    "need_image": {
                        "type": "boolean",
                        "description": "是否需要配图（需要 ComfyUI 服务支持）"
                    },
                    "image_prompt": {
                        "type": "string",
                        "description": "配图描述（会调用 AI 绘图服务生成，如果服务可用）"
                    },
                    "mood": {
                        "type": "string",
                        "description": "当前心情标签（开心/难过/平静/兴奋/思考/其他）"
                    }
                },
                "required": ["content"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行朋友圈安排
        
        Args:
            arguments: {
                "content": "朋友圈内容",
                "delay_minutes": 0,  # 可选
                "need_image": false,  # 可选
                "image_prompt": "图片描述",  # 可选
                "mood": "开心"  # 可选
            }
            context: 执行上下文（需要 db 和 session_id）
        
        Returns:
            str: JSON 格式的执行结果
        """
        import json
        
        # 验证必要参数
        if not arguments.get("content"):
            return json.dumps({
                "success": False,
                "error": "朋友圈内容不能为空"
            }, ensure_ascii=False)
        
        # 从上下文获取必要信息
        db_name = context.extra.get("db_name", settings.mongodb_db_name)
        db = context.db[db_name]
        session_id = context.session_id
        
        if not session_id:
            logger.error("❌ 缺少 session_id，无法创建朋友圈")
            return json.dumps({
                "success": False,
                "error": "系统错误：缺少会话信息"
            }, ensure_ascii=False)
        
        try:
            # 1. 解析延迟时间
            delay_minutes = arguments.get("delay_minutes")
            
            if delay_minutes is None:
                # AI 没指定时间 → 随机 15-120 分钟（模拟真人的随机性）
                delay_minutes = random.randint(15, 120)
                logger.info(f"📅 未指定延迟时间，随机设置为 {delay_minutes} 分钟")
            
            publish_at = datetime.now() + timedelta(minutes=delay_minutes)
            
            # 2. 创建队列记录
            queue_item = {
                "_id": str(uuid.uuid4()),
                "session_id": session_id,
                "content": arguments["content"],
                "created_at": datetime.now().isoformat(),
                "publish_at": publish_at.isoformat(),
                "status": "pending",
                "need_image": arguments.get("need_image", False),
                "image_prompt": arguments.get("image_prompt"),
                "generated_images": [],
                "mood": arguments.get("mood"),
                "triggered_by": "ai_self"
            }
            
            # 3. 如果需要图片，尝试生成（异步，不阻塞）
            if queue_item["need_image"] and queue_item["image_prompt"]:
                try:
                    from ...services.resource_manager import get_resource_manager
                    
                    resource_mgr = await get_resource_manager()
                    
                    # 检查是否有可用的图片生成器
                    available_generators = resource_mgr.get_available_generators(
                        resource_type="image"
                    )
                    
                    if available_generators:
                        logger.info(f"🎨 检测到可用的图片生成器，开始生成图片...")
                        image_urls = await resource_mgr.generate_image(
                            prompt=queue_item["image_prompt"],
                            generator_name=available_generators[0]
                        )
                        
                        if image_urls:
                            queue_item["generated_images"] = image_urls
                            logger.info(f"✅ 成功生成 {len(image_urls)} 张图片")
                        else:
                            logger.warning("⚠️ 图片生成失败，将发布纯文字朋友圈")
                    else:
                        logger.info("ℹ️ 暂无可用的图片生成服务，保存图片描述，等服务可用时再生成")
                        
                except Exception as e:
                    logger.error(f"❌ 生成图片时出错: {e}")
                    logger.info("将继续发布纯文字朋友圈")
            
            # 4. 保存到会话文档的 moment_queue 字段
            await db.chat_sessions.update_one(
                {"_id": session_id},
                {"$push": {"moment_queue": queue_item}}
            )
            logger.info(f"✅ 朋友圈已加入队列: {queue_item['_id']}")
            
            # 5. 返回结果给 AI
            delay_text = f"{delay_minutes}分钟后" if delay_minutes > 0 else "立即"
            has_image_text = "（配图）" if queue_item["generated_images"] else ""
            
            result = {
                "success": True,
                "queue_id": queue_item["_id"],
                "message": f"朋友圈已安排，将在{delay_text}发布{has_image_text}",
                "publish_at": publish_at.isoformat(),
                "has_images": len(queue_item["generated_images"]) > 0,
                "image_count": len(queue_item["generated_images"])
            }
            
            logger.info(f"📝 朋友圈工具执行成功: {result}")
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 朋友圈工具执行失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"发布失败: {str(e)}"
            }, ensure_ascii=False)


class CancelMomentTool(BaseTool):
    """取消朋友圈发布工具（可选功能）"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """获取工具元数据"""
        return ToolMetadata(
            name="cancel_moment",
            description="使用该工具可以取消一条你自己尚未发布（状态为 pending）的朋友圈。",
            input_schema={
                "type": "object",
                "properties": {
                    "queue_id": {
                        "type": "string",
                        "description": "队列 ID（调用 schedule_moment 时返回的 queue_id）"
                    }
                },
                "required": ["queue_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """执行取消操作"""
        import json
        
        queue_id = arguments.get("queue_id")
        if not queue_id:
            return json.dumps({
                "success": False,
                "error": "缺少 queue_id 参数"
            }, ensure_ascii=False)
        
        try:
            db_name = context.extra.get("db_name", settings.mongodb_db_name)
            db = context.db[db_name]
            session_id = context.session_id
            
            # 从会话文档的 moment_queue 中查找
            session = await db.chat_sessions.find_one({"_id": session_id})
            
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "会话不存在"
                }, ensure_ascii=False)
            
            # 找到对应的队列项
            queue_item = next((item for item in session.get("moment_queue", []) if item["_id"] == queue_id), None)
            
            if not queue_item:
                return json.dumps({
                    "success": False,
                    "error": "未找到该朋友圈"
                }, ensure_ascii=False)
            
            if queue_item["status"] != "pending":
                return json.dumps({
                    "success": False,
                    "error": f"该朋友圈状态为 {queue_item['status']}，无法取消"
                }, ensure_ascii=False)
            
            # 更新数组中的状态
            await db.chat_sessions.update_one(
                {"_id": session_id, "moment_queue._id": queue_id},
                {"$set": {
                    "moment_queue.$.status": "cancelled",
                    "moment_queue.$.cancelled_at": datetime.now().isoformat()
                }}
            )
            
            logger.info(f"✅ 朋友圈已取消: {queue_id}")
            
            return json.dumps({
                "success": True,
                "message": "朋友圈已取消"
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 取消朋友圈失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"取消失败: {str(e)}"
            }, ensure_ascii=False)


class CommentMomentTool(BaseTool):
    """评论朋友圈工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """获取工具元数据"""
        return ToolMetadata(
            name="comment_moment",
            description="""使用该工具可以对你自己发布的朋友圈添加评论。用户会在前端看到你的朋友圈，并可能对其进行评论，这个工具用于查看和回复用户的评论。""".strip(),
            input_schema={
                "type": "object",
                "properties": {
                    "moment_id": {
                        "type": "string",
                        "description": "朋友圈 ID（从 get_my_moments 或 get_moment_detail 工具获取）"
                    },
                    "content": {
                        "type": "string",
                        "description": "评论内容（必填，建议 10-200 字）"
                    }
                },
                "required": ["moment_id", "content"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行评论操作
        
        Args:
            arguments: {
                "moment_id": "朋友圈ID",
                "content": "评论内容"
            }
            context: 执行上下文（需要 db 和 session_id）
        
        Returns:
            str: JSON 格式的执行结果
        """
        import json
        
        moment_id = arguments.get("moment_id")
        content = arguments.get("content")
        
        if not moment_id or not content:
            return json.dumps({
                "success": False,
                "error": "moment_id 和 content 是必填参数"
            }, ensure_ascii=False)
        
        if len(content.strip()) == 0:
            return json.dumps({
                "success": False,
                "error": "评论内容不能为空"
            }, ensure_ascii=False)
        
        try:
            db_name = context.extra.get("db_name", settings.mongodb_db_name)
            db = context.db[db_name]
            session_id = context.session_id
            
            if not session_id:
                return json.dumps({
                    "success": False,
                    "error": "系统错误：缺少会话信息"
                }, ensure_ascii=False)
            
            # 获取会话信息（获取 AI 角色名称）
            session = await db.chat_sessions.find_one({"_id": session_id})
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "会话不存在"
                }, ensure_ascii=False)
            
            # 获取 AI 的名字（从 assistant_name 或使用默认）
            ai_name = session.get("assistant_name", "AI助手")
            
            # 创建评论
            current_time = datetime.now().isoformat()
            comment = {
                "_id": str(uuid.uuid4()),
                "user_id": "ai",  # 标记为 AI 评论
                "user_name": ai_name,
                "content": content.strip(),
                "created_at": current_time,
                "is_ai": True  # 额外标记，方便前端区分
            }
            
            # 添加评论到朋友圈
            result = await db.chat_sessions.update_one(
                {"_id": session_id, "moments._id": moment_id},
                {"$push": {"moments.$.comments": comment}}
            )
            
            if result.matched_count == 0:
                return json.dumps({
                    "success": False,
                    "error": "朋友圈不存在或已删除"
                }, ensure_ascii=False)
            
            logger.info(f"✅ AI 评论成功: {moment_id} - {content[:20]}...")
            
            return json.dumps({
                "success": True,
                "message": "评论发布成功",
                "comment": {
                    "id": comment["_id"],
                    "content": content,
                    "created_at": comment["created_at"]
                }
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 评论失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"评论失败: {str(e)}"
            }, ensure_ascii=False)


class LikeMomentTool(BaseTool):
    """点赞朋友圈工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """获取工具元数据"""
        return ToolMetadata(
            name="like_moment",
            description="""使用该工具可以给你自己的朋友圈进行点赞或取消点赞。""".strip(),
            input_schema={
                "type": "object",
                "properties": {
                    "moment_id": {
                        "type": "string",
                        "description": "朋友圈 ID"
                    }
                },
                "required": ["moment_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行点赞/取消点赞操作
        
        Args:
            arguments: {"moment_id": "朋友圈ID"}
            context: 执行上下文
        
        Returns:
            str: JSON 格式的执行结果
        """
        import json
        
        moment_id = arguments.get("moment_id")
        
        if not moment_id:
            return json.dumps({
                "success": False,
                "error": "moment_id 是必填参数"
            }, ensure_ascii=False)
        
        try:
            db_name = context.extra.get("db_name", settings.mongodb_db_name)
            db = context.db[db_name]
            session_id = context.session_id
            
            if not session_id:
                return json.dumps({
                    "success": False,
                    "error": "系统错误：缺少会话信息"
                }, ensure_ascii=False)
            
            # 查找朋友圈
            session = await db.chat_sessions.find_one({
                "_id": session_id,
                "moments._id": moment_id
            })
            
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "朋友圈不存在"
                }, ensure_ascii=False)
            
            # 找到对应的朋友圈
            moment = next((m for m in session.get("moments", []) if m["_id"] == moment_id), None)
            
            if not moment:
                return json.dumps({
                    "success": False,
                    "error": "朋友圈不存在"
                }, ensure_ascii=False)
            
            # 检查是否已点赞（使用 "ai" 标识）
            ai_user_id = "ai"
            likes = moment.get("likes", [])
            
            # 统一转换 likes 为字符串进行比较
            likes_str = [str(like) for like in likes]
            
            if ai_user_id in likes_str:
                # 取消点赞
                await db.chat_sessions.update_one(
                    {"_id": session_id, "moments._id": moment_id},
                    {"$pull": {"moments.$.likes": ai_user_id}}
                )
                
                logger.info(f"✅ AI 取消点赞: {moment_id}")
                
                return json.dumps({
                    "success": True,
                    "action": "unliked",
                    "message": "已取消点赞"
                }, ensure_ascii=False)
            else:
                # 添加点赞
                await db.chat_sessions.update_one(
                    {"_id": session_id, "moments._id": moment_id},
                    {"$addToSet": {"moments.$.likes": ai_user_id}}
                )
                
                logger.info(f"✅ AI 点赞: {moment_id}")
                
                return json.dumps({
                    "success": True,
                    "action": "liked",
                    "message": "点赞成功"
                }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 点赞操作失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"操作失败: {str(e)}"
            }, ensure_ascii=False)

