/**
 * 知识库广场 API
 */

const API_BASE_URL = '/api/kb-marketplace';

/**
 * 共享知识库到广场
 */
export const shareKnowledgeBase = async (
  token: string,
  kbId: string,
  description?: string
) => {
  const response = await fetch(`${API_BASE_URL}/share`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      kb_id: kbId,
      description,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '共享失败');
  }

  return response.json();
};

/**
 * 取消共享知识库
 */
export const unshareKnowledgeBase = async (token: string, kbId: string) => {
  const response = await fetch(`${API_BASE_URL}/unshare`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      kb_id: kbId,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '取消共享失败');
  }

  return response.json();
};

/**
 * 获取广场知识库列表
 */
export const listSharedKnowledgeBases = async (
  token: string,
  skip: number = 0,
  limit: number = 50,
  search?: string
) => {
  const params = new URLSearchParams({
    skip: skip.toString(),
    limit: limit.toString(),
  });

  if (search) {
    params.append('search', search);
  }

  const response = await fetch(`${API_BASE_URL}/list?${params.toString()}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '获取列表失败');
  }

  return response.json();
};

/**
 * 拉取共享知识库
 */
export const pullKnowledgeBase = async (
  token: string,
  sharedKbId: string,
  embeddingConfig: any,
  distanceMetric?: string,
  similarityThreshold?: number,
  topK?: number
) => {
  const response = await fetch(`${API_BASE_URL}/pull`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      shared_kb_id: sharedKbId,
      embedding_config: embeddingConfig,
      distance_metric: distanceMetric,
      similarity_threshold: similarityThreshold,
      top_k: topK,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '拉取失败');
  }

  return response.json();
};

/**
 * 获取已拉取的知识库列表
 */
export const listPulledKnowledgeBases = async (
  token: string,
  skip: number = 0,
  limit: number = 100
) => {
  const params = new URLSearchParams({
    skip: skip.toString(),
    limit: limit.toString(),
  });

  const response = await fetch(`${API_BASE_URL}/pulled?${params.toString()}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '获取列表失败');
  }

  return response.json();
};

/**
 * 更新已拉取知识库的配置
 */
export const updatePulledKnowledgeBase = async (
  token: string,
  pulledKbId: string,
  updateData: {
    embedding_config?: any;
    similarity_threshold?: number;
    top_k?: number;
    enabled?: boolean;
  }
) => {
  const response = await fetch(`${API_BASE_URL}/pulled/${pulledKbId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(updateData),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '更新失败');
  }

  return response.json();
};

/**
 * 删除已拉取的知识库
 */
export const deletePulledKnowledgeBase = async (
  token: string,
  pulledKbId: string
) => {
  const response = await fetch(`${API_BASE_URL}/pulled/${pulledKbId}`, {
    method: 'DELETE',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '删除失败');
  }

  return response.json();
};

/**
 * 检查知识库是否已共享
 */
export const checkKnowledgeBaseShared = async (
  token: string,
  kbId: string
) => {
  const response = await fetch(`${API_BASE_URL}/check-shared/${kbId}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '检查失败');
  }

  return response.json();
};

