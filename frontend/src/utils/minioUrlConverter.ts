import { buildFullUrl } from '../config';

/**
 * 将MinIO URL转换为HTTP API URL
 * @param minioUrl MinIO格式的URL (例如: minio://bucket/users/xxx/avatar/xxx.jpg)
 * @returns HTTP格式的API URL
 */
export const convertMinioUrlToHttp = (minioUrl: string): string => {
  try {
    if (!minioUrl || !minioUrl.startsWith('minio://')) {
      return minioUrl;
    }
    
    // 解析 minio://bucket/path/to/file.jpg
    const urlParts = minioUrl.replace('minio://', '').split('/');
    if (urlParts.length < 2) {
      return minioUrl;
    }
    
    const pathParts = urlParts.slice(1); // 去掉 bucket 名称
    
    // 用户头像：users/{userId}/avatar/{filename}
    if (pathParts.length === 4 && pathParts[0] === 'users' && pathParts[2] === 'avatar') {
      return buildFullUrl(`/api/auth/avatar/${pathParts[1]}/${pathParts[3]}`);
    }
    
    // 传统会话角色头像：users/{userId}/sessions/{sessionId}/role_avatar/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'role_avatar') {
      return buildFullUrl(`/api/auth/role-avatar/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }
    
    // 传统会话背景图：users/{userId}/sessions/{sessionId}/role_background/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'role_background') {
      return buildFullUrl(`/api/auth/role-background/${pathParts[3]}`);
    }
    
    // 传统会话消息图片：users/{userId}/sessions/{sessionId}/message_image/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'sessions' && pathParts[4] === 'message_image') {
      return buildFullUrl(`/api/auth/message-image/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }
    
    // 新格式会话消息图片：users/{userId}/{sessionId}/{messageId}/{filename}
    if (pathParts.length === 5 && pathParts[0] === 'users') {
      return buildFullUrl(`/api/auth/new-message-image/${pathParts[1]}/${pathParts[2]}/${pathParts[3]}/${pathParts[4]}`);
    }
    
    // 助手头像：users/{userId}/assistants/{assistantId}/avatar/{filename}
    if (pathParts.length === 6 && pathParts[0] === 'users' && pathParts[2] === 'assistants' && pathParts[4] === 'avatar') {
      return buildFullUrl(`/api/auth/assistant-avatar/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}`);
    }
    
    // 助手会话角色头像：users/{userId}/assistants/{assistantId}/sessions/{sessionId}/role_avatar/{filename}
    if (pathParts.length === 8 && pathParts[0] === 'users' && pathParts[2] === 'assistants' && pathParts[4] === 'sessions' && pathParts[6] === 'role_avatar') {
      return buildFullUrl(`/api/auth/assistant-role-avatar/${pathParts[1]}/${pathParts[3]}/${pathParts[5]}/${pathParts[7]}`);
    }
    
    // 助手会话背景图：users/{userId}/assistants/{assistantId}/sessions/{sessionId}/role_background/{filename}
    if (pathParts.length === 8 && pathParts[0] === 'users' && pathParts[2] === 'assistants' && pathParts[4] === 'sessions' && pathParts[6] === 'role_background') {
      return buildFullUrl(`/api/auth/assistant-role-background/${pathParts[5]}`);
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

