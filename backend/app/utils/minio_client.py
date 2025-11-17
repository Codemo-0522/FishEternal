import io
import base64
import uuid
from typing import List, Optional
from minio import Minio
from minio.error import S3Error
from ..config import settings
import logging

logger = logging.getLogger(__name__)

class MinioClient:
    def __init__(self):
        endpoint_raw = (settings.minio_endpoint or "").strip()
        if not endpoint_raw:
            logger.warning("未检测到 MINIO_ENDPOINT，MinIO 客户端未启用。")
            self.client = None
            self.bucket_name = (settings.minio_bucket_name or "").strip() or "fish-chat"
            return
        secure = endpoint_raw.startswith("https://")
        endpoint_clean = endpoint_raw.replace("http://", "").replace("https://", "")
        self.client = Minio(
            endpoint_clean,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure
        )
        self.bucket_name = settings.minio_bucket_name
        self._ensure_bucket_exists()
    
    def _is_configured(self) -> bool:
        if self.client is None:
            logger.error("MinIO 未配置（缺少 MINIO_ENDPOINT）。请求已跳过。")
            return False
        return True
    
    def _ensure_bucket_exists(self):
        """确保bucket存在，不存在则创建"""
        if self.client is None:
            return
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"创建bucket: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"MinIO bucket操作失败: {e}")
    
    def upload_image(self, image_base64: str, session_id: str, message_id: str, user_id: str) -> str:
        """
        上传图片到MinIO并返回对象路径
        
        路径结构：users/{user_id}/sessions/{session_id}/message_image/{file_id}.jpg
        
        Args:
            image_base64: Base64编码的图片数据
            session_id: 会话ID（可以是路径片段，如 "sessions/xxx" 或 "assistants/xxx/sessions/yyy"）
            message_id: 消息ID（用作目录名，如 "message_image", "role_avatar", "role_background"）
            user_id: 用户ID（必需，用于路径隔离）
        
        Returns:
            MinIO URL (格式: minio://{bucket}/{object_name})
        """
        logger.info(f"=== MinIO上传图片 ===")
        logger.info(f"user_id: {user_id}")
        logger.info(f"session_id: {session_id}")
        logger.info(f"message_id: {message_id}")
        logger.info(f"图片Base64长度: {len(image_base64)}")
        
        if not self._is_configured():
            return None
        
        try:
            # 生成唯一文件名
            file_id = str(uuid.uuid4())
            
            # 统一的路径结构：users/{user_id}/{session_id}/{message_id}/{file_id}.jpg
            # session_id 可以是简单的会话ID，也可以是包含路径的片段（如 "sessions/xxx" 或 "assistants/xxx/sessions/yyy"）
            object_name = f"users/{user_id}/{session_id}/{message_id}/{file_id}.jpg"
            logger.info(f"🏷️ 使用用户隔离路径: {object_name}")
            
            # Base64转二进制
            if image_base64.startswith("data:image"):
                logger.info("检测到data:image格式，提取Base64数据")
                image_data = base64.b64decode(image_base64.split(',')[1])
            else:
                logger.info("直接使用Base64数据")
                image_data = base64.b64decode(image_base64)
            
            logger.info(f"图片二进制数据长度: {len(image_data)}字节")
            
            # 上传到MinIO
            logger.info(f"开始上传到MinIO，bucket: {self.bucket_name}")
            self.client.put_object(
                self.bucket_name,
                object_name,
                io.BytesIO(image_data),
                len(image_data),
                content_type="image/png"
            )
            
            minio_url = f"minio://{self.bucket_name}/{object_name}"
            logger.info(f"✅ 图片上传成功: {minio_url}")
            return minio_url
            
        except Exception as e:
            logger.error(f"❌ 图片上传失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return None
    
    def get_image_base64(self, minio_url: str) -> Optional[str]:
        """从MinIO获取图片并转换为Base64"""
        if not self._is_configured():
            return None
        try:
            # 解析minio://bucket/object路径
            if minio_url.startswith("minio://"):
                path_parts = minio_url.replace("minio://", "").split("/", 1)
                if len(path_parts) == 2:
                    bucket, object_name = path_parts
                else:
                    logger.error(f"无效的MinIO URL格式: {minio_url}")
                    return None
            else:
                logger.error(f"无效的MinIO URL: {minio_url}")
                return None
            
            # 从MinIO下载图片
            response = self.client.get_object(bucket, object_name)
            image_data = response.read()
            
            # 转换为Base64
            base64_data = base64.b64encode(image_data).decode()
            return f"data:image/png;base64,{base64_data}"
            
        except Exception as e:
            logger.error(f"从MinIO获取图片失败: {e}")
            return None
    
    def delete_image(self, minio_url: str) -> bool:
        """删除MinIO中的图片"""
        if not self._is_configured():
            return False
        try:
            if minio_url.startswith("minio://"):
                path_parts = minio_url.replace("minio://", "").split("/", 1)
                if len(path_parts) == 2:
                    bucket, object_name = path_parts
                    self.client.remove_object(bucket, object_name)
                    logger.info(f"图片删除成功: {object_name}")
                    return True
            return False
        except Exception as e:
            logger.error(f"删除图片失败: {e}")
            return False
    
    def delete_session_folder(self, session_id: str) -> bool:
        """删除会话文件夹及其所有内容"""
        if not self._is_configured():
            return False
        try:
            logger.info(f"开始删除会话文件夹: {session_id}")
            
            # 列出会话文件夹下的所有对象
            objects = self.client.list_objects(
                self.bucket_name,
                prefix=f"{session_id}/",
                recursive=True
            )
            
            deleted_count = 0
            for obj in objects:
                try:
                    self.client.remove_object(self.bucket_name, obj.object_name)
                    logger.info(f"删除对象: {obj.object_name}")
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"删除对象失败 {obj.object_name}: {e}")
            
            logger.info(f"✅ 会话文件夹删除完成，共删除 {deleted_count} 个对象")
            return True
            
        except Exception as e:
            logger.error(f"❌ 删除会话文件夹失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return False

    def delete_prefix(self, prefix: str) -> bool:
        """根据前缀删除对象（等价于删除指定“文件夹”）。"""
        if not self._is_configured():
            return False
        try:
            logger.info(f"开始删除前缀: {prefix}")
            normalized_prefix = prefix if prefix.endswith('/') else f"{prefix}/"
            objects = self.client.list_objects(
                self.bucket_name,
                prefix=normalized_prefix,
                recursive=True
            )
            deleted_count = 0
            for obj in objects:
                try:
                    self.client.remove_object(self.bucket_name, obj.object_name)
                    logger.info(f"删除对象: {obj.object_name}")
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"删除对象失败 {obj.object_name}: {e}")
            logger.info(f"✅ 前缀删除完成，共删除 {deleted_count} 个对象")
            return True
        except Exception as e:
            logger.error(f"❌ 删除前缀失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return False

    def delete_assistant_across_owners(self, assistant_id: str) -> int:
        """扫描 users/ 下所有对象，定位包含 /assistants/{assistant_id}/ 的路径，并删除对应 owner 的助手根前缀。
        返回删除的 owner 数量（去重后）。"""
        if not self._is_configured():
            return 0
        try:
            owners_to_clean = set()
            prefix = "users/"
            # 全量扫描 users/，尽量避免遗漏（数量大时可能较慢）
            for obj in self.client.list_objects(self.bucket_name, prefix=prefix, recursive=True):
                name = obj.object_name
                marker = f"/assistants/{assistant_id}/"
                if marker in name:
                    # 期望路径：users/{owner}/assistants/{assistant_id}/...
                    parts = name.split('/')
                    # 简单健壮性判断
                    if len(parts) >= 4 and parts[0] == 'users':
                        owner_id = parts[1]
                        owners_to_clean.add(owner_id)
                        logger.debug(f"匹配到助手对象 owner={owner_id} path={name}")
            # 按 owner 删除
            for owner_id in owners_to_clean:
                owner_prefix = f"users/{owner_id}/assistants/{assistant_id}/"
                logger.info(f"🔍 跨owner清理助手前缀: {owner_prefix}")
                self.delete_prefix(owner_prefix)
            return len(owners_to_clean)
        except Exception as e:
            logger.error(f"跨owner清理助手失败 assistant_id={assistant_id}: {e}")
            return 0
    
    def upload_file(self, file_data: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        """
        通用文件上传方法
        
        Args:
            file_data: 文件二进制数据
            object_name: 对象名称（完整路径，如 "group-chats/{group_id}/avatar.png"）
            content_type: 文件MIME类型
        
        Returns:
            HTTP URL (格式: http://{endpoint}/{bucket}/{object_name})
        """
        if not self._is_configured():
            raise Exception("MinIO未配置")
        
        try:
            logger.info(f"上传文件到MinIO: {object_name}, 大小: {len(file_data)} 字节")
            
            # 上传到MinIO
            self.client.put_object(
                self.bucket_name,
                object_name,
                io.BytesIO(file_data),
                len(file_data),
                content_type=content_type
            )
            
            # 返回HTTP URL
            endpoint = settings.minio_endpoint.replace("http://", "").replace("https://", "")
            protocol = "https" if settings.minio_endpoint.startswith("https://") else "http"
            url = f"{protocol}://{endpoint}/{self.bucket_name}/{object_name}"
            
            logger.info(f"✅ 文件上传成功: {url}")
            return url
            
        except Exception as e:
            logger.error(f"❌ 文件上传失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            raise
    
    def delete_file(self, object_name: str) -> bool:
        """
        删除单个文件
        
        Args:
            object_name: 对象名称（完整路径）
        
        Returns:
            是否删除成功
        """
        if not self._is_configured():
            return False
        
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.info(f"✅ 文件删除成功: {object_name}")
            return True
        except Exception as e:
            logger.error(f"❌ 文件删除失败 {object_name}: {e}")
            return False
    
    def delete_folder(self, folder_prefix: str) -> int:
        """
        删除文件夹及其所有内容
        
        Args:
            folder_prefix: 文件夹前缀（如 "group-chats/{group_id}/"）
        
        Returns:
            删除的文件数量
        """
        if not self._is_configured():
            return 0
        
        try:
            logger.info(f"开始删除文件夹: {folder_prefix}")
            
            # 确保前缀以 / 结尾
            normalized_prefix = folder_prefix if folder_prefix.endswith('/') else f"{folder_prefix}/"
            
            # 列出文件夹下的所有对象
            objects = self.client.list_objects(
                self.bucket_name,
                prefix=normalized_prefix,
                recursive=True
            )
            
            deleted_count = 0
            for obj in objects:
                try:
                    self.client.remove_object(self.bucket_name, obj.object_name)
                    logger.info(f"删除对象: {obj.object_name}")
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"删除对象失败 {obj.object_name}: {e}")
            
            logger.info(f"✅ 文件夹删除完成，共删除 {deleted_count} 个对象")
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ 删除文件夹失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return 0
    
    # ==================== 知识库文档存储方法 ====================
    
    def upload_kb_document(
        self, 
        file_data: bytes, 
        user_id: str, 
        collection_name: str, 
        doc_id: str,
        filename: str,
        content_type: str = "application/octet-stream"
    ) -> str:
        """
        上传知识库文档到 MinIO（带用户隔离）
        
        Args:
            file_data: 文件二进制数据
            user_id: 用户ID（用于隔离）
            collection_name: 知识库collection名称（唯一标识，不可修改）
            doc_id: 文档ID（用作文件名前缀，避免重名）
            filename: 原始文件名
            content_type: 文件MIME类型
        
        Returns:
            MinIO URL (格式: minio://{bucket}/kb-documents/{user_id}/{collection_name}/{doc_id}_{filename})
        """
        if not self._is_configured():
            raise Exception("MinIO未配置")
        
        try:
            # 构建带用户隔离的路径：kb-documents/{user_id}/{collection_name}/{doc_id}_{filename}
            # 使用 doc_id 作为前缀避免文件名冲突，但不单独创建文件夹
            # 注意：使用 collection_name 而不是 kb_id，因为用户可能修改知识库名称，但 collection_name 不变
            object_name = f"kb-documents/{user_id}/{collection_name}/{doc_id}_{filename}"
            
            logger.info(f"上传知识库文档到MinIO: {object_name}, 大小: {len(file_data)} 字节")
            
            # 上传到MinIO
            self.client.put_object(
                self.bucket_name,
                object_name,
                io.BytesIO(file_data),
                len(file_data),
                content_type=content_type
            )
            
            minio_url = f"minio://{self.bucket_name}/{object_name}"
            logger.info(f"✅ 知识库文档上传成功: {minio_url}")
            return minio_url
            
        except Exception as e:
            logger.error(f"❌ 知识库文档上传失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            raise
    
    def download_kb_document(self, minio_url: str) -> bytes:
        """
        从 MinIO 下载知识库文档
        
        Args:
            minio_url: MinIO URL (格式: minio://{bucket}/{object_name}) 或对象路径
        
        Returns:
            文件二进制数据
        """
        if not self._is_configured():
            raise Exception("MinIO未配置")
        
        try:
            # 解析 minio:// URL 或直接使用对象路径
            if minio_url.startswith("minio://"):
                path_parts = minio_url.replace("minio://", "").split("/", 1)
                if len(path_parts) == 2:
                    bucket, object_name = path_parts
                else:
                    raise ValueError(f"无效的MinIO URL格式: {minio_url}")
            else:
                # 兼容旧的直接路径格式
                object_name = minio_url
            
            logger.info(f"从MinIO下载文档: {object_name}")
            
            response = self.client.get_object(self.bucket_name, object_name)
            file_data = response.read()
            response.close()
            response.release_conn()
            
            logger.info(f"✅ 文档下载成功: {object_name}, 大小: {len(file_data)} 字节")
            return file_data
            
        except Exception as e:
            logger.error(f"❌ 文档下载失败: {e}")
            raise
    
    def delete_kb_document(self, minio_url: str) -> bool:
        """
        从 MinIO 删除知识库文档
        
        Args:
            minio_url: MinIO URL (格式: minio://{bucket}/{object_name}) 或对象路径
        
        Returns:
            是否删除成功
        """
        if not self._is_configured():
            logger.warning("MinIO未配置，跳过删除文档")
            return False
        
        try:
            # 解析 minio:// URL 或直接使用对象路径
            if minio_url.startswith("minio://"):
                path_parts = minio_url.replace("minio://", "").split("/", 1)
                if len(path_parts) == 2:
                    bucket, object_name = path_parts
                else:
                    logger.error(f"无效的MinIO URL格式: {minio_url}")
                    return False
            else:
                # 兼容旧的直接路径格式
                object_name = minio_url
            
            logger.info(f"从MinIO删除文档: {object_name}")
            self.client.remove_object(self.bucket_name, object_name)
            logger.info(f"✅ 文档删除成功: {object_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 文档删除失败: {e}")
            return False
    
    def delete_kb_all_documents(self, user_id: str, collection_name: str) -> int:
        """
        删除知识库下的所有文档
        
        Args:
            user_id: 用户ID
            collection_name: 知识库collection名称
        
        Returns:
            删除的文件数量
        """
        folder_prefix = f"kb-documents/{user_id}/{collection_name}/"
        return self.delete_folder(folder_prefix)

# 创建全局MinIO客户端实例（容错：未配置时不会抛出异常）
minio_client = MinioClient() 