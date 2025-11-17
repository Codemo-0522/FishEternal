/**
 * 朋友圈 API 服务
 */

import authAxios from '../utils/authAxios';

export interface LikeUser {
  user_id: string;
  user_name: string;
}

export interface Moment {
  _id: string;
  content: string;
  images?: string[];
  mood?: string;
  created_at: string;
  scheduled_at: string;
  likes: string[]; // 兼容旧数据：user_id 数组
  like_users?: LikeUser[]; // 新增：点赞用户详细信息
  comments: Comment[];
}

export interface Comment {
  _id: string;
  user_id: string;
  user_name: string;
  content: string;
  created_at: string;
  is_ai?: boolean; // AI 评论标记
}

export interface MomentQueue {
  _id: string;
  session_id: string;
  content: string;
  mood?: string;
  need_image: boolean;
  image_prompt?: string;
  generated_images?: string[];
  status: 'pending' | 'published' | 'error' | 'cancelled';
  publish_at: string;
  created_at: string;
  published_at?: string;
  published_moment_id?: string;
  error_message?: string;
}

export interface GetMomentsResponse {
  moments: Moment[];
  total: number;
  has_more: boolean;
  has_updates?: boolean;
}

export interface GetQueueResponse {
  pending: MomentQueue[];
  published: MomentQueue[];
  error: MomentQueue[];
  cancelled: MomentQueue[];
  has_updates?: boolean;
}

/**
 * 获取会话的朋友圈列表
 */
export const getMoments = async (
  sessionId: string,
  limit: number = 20,
  offset: number = 0,
  since?: string
): Promise<GetMomentsResponse> => {
  const params: any = { limit, offset };
  if (since) {
    params.since = since;
  }
  const response = await authAxios.get(`/api/moments/sessions/${sessionId}`, {
    params
  });
  return response.data;
};

/**
 * 获取会话的朋友圈队列
 */
export const getMomentQueue = async (
  sessionId: string,
  since?: string
): Promise<GetQueueResponse> => {
  const params: any = {};
  if (since) {
    params.since = since;
  }
  const response = await authAxios.get(`/api/moments/sessions/${sessionId}/queue`, {
    params
  });
  return response.data;
};

/**
 * 点赞/取消点赞
 */
export const likeMoment = async (
  sessionId: string,
  momentId: string
): Promise<{ success: boolean; message: string }> => {
  const response = await authAxios.post(
    `/api/moments/sessions/${sessionId}/moments/${momentId}/like`
  );
  return response.data;
};

/**
 * 评论朋友圈
 */
export const commentMoment = async (
  sessionId: string,
  momentId: string,
  content: string
): Promise<{ success: boolean; comment: Comment }> => {
  const response = await authAxios.post(
    `/api/moments/sessions/${sessionId}/moments/${momentId}/comment`,
    null,
    { params: { content } }
  );
  return response.data;
};

/**
 * 删除朋友圈
 */
export const deleteMoment = async (
  sessionId: string,
  momentId: string
): Promise<{ success: boolean; message: string }> => {
  const response = await authAxios.delete(
    `/api/moments/sessions/${sessionId}/moments/${momentId}`
  );
  return response.data;
};

/**
 * 删除评论
 */
export const deleteComment = async (
  sessionId: string,
  momentId: string,
  commentId: string
): Promise<{ success: boolean; message: string }> => {
  const response = await authAxios.delete(
    `/api/moments/sessions/${sessionId}/moments/${momentId}/comments/${commentId}`
  );
  return response.data;
};

