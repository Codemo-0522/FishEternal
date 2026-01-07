// src/utils/url.ts

/**
 * 构建完整的后端 API URL
 * @param path - API 路径，例如 /auth/avatar/...
 * @returns 完整的 URL
 */
const buildFullUrl = (path: string): string => {
  // 在 Vite 中，可以使用 import.meta.env.VITE_API_BASE_URL
  // 这里我们先硬编码，或者假设有一个全局的配置
  const baseUrl = import.meta.env.VITE_API_URL || '';
  return `${baseUrl}${path}`;
};

/**
 * 将MinIO URL转换为HTTP API URL
 * @param minioUrl - minio:// 格式的 URL
 * @returns 可通过浏览器访问的 HTTP URL
 */
export const convertMinioUrlToHttp = (minioUrl: string): string => {
  try {
    if (!minioUrl || !minioUrl.startsWith('minio://')) {
      return minioUrl;
    }

    const urlParts = minioUrl.replace('minio://', '').split('/');
    if (urlParts.length < 2) {
      return minioUrl;
    }

    const pathParts = urlParts.slice(1);

    // 用户头像: users/{userId}/avatar/{filename}
    if (pathParts.length === 4 && pathParts[0] === 'users' && pathParts[2] === 'avatar') {
      return buildFullUrl(`/api/auth/avatar/${pathParts[1]}/${pathParts[3]}`);
    }

    // 传统会话角色头像: users/{userId}/sessions/{sessionId}/role_avatar/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'role_avatar') {
      return buildFullUrl(`/api/auth/role-avatar/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }

    // 传统会话背景图: users/{userId}/sessions/{sessionId}/role_background/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'role_background') {
      return buildFullUrl(`/api/auth/role-background/${pathParts[3]}`);
    }

    // 传统会话消息图片: users/{userId}/sessions/{sessionId}/message_image/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'message_image') {
      return buildFullUrl(`/api/auth/message-image/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }
    
    // 朋友圈图片: users/{userId}/{sessionId}/moment_{momentId}_{index}/{filename}
    if (pathParts.length === 5 && pathParts[0] === 'users' && pathParts[3].startsWith('moment_')) {
      return buildFullUrl(`/api/auth/new-message-image/${pathParts[1]}/${pathParts[2]}/${pathParts[3]}/${pathParts[4]}`);
    }

    // 新格式会话消息图片：users/{userId}/{sessionId}/{messageId}/{filename}
    if (pathParts.length === 5 && pathParts[0] === 'users') {
      return buildFullUrl(`/api/auth/new-message-image/${pathParts[1]}/${pathParts[2]}/${pathParts[3]}/${pathParts[4]}`);
    }

    // 群聊头像：group-chats/{groupId}/{filename}
    if (pathParts.length === 3 && pathParts[0] === 'group-chats') {
      return buildFullUrl(`/api/auth/group-avatar/${pathParts[1]}/${pathParts[2]}`);
    }

    return minioUrl; // 如果解析失败，返回原URL
  } catch (error) {
    console.error('转换MinIO URL失败:', error);
    return minioUrl; // 出错时返回原URL
  }
};
