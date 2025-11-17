import authAxios from '../utils/authAxios';

const API_BASE_URL = '/api';

export interface ToolInfo {
  name: string;
  description: string;
  category?: string;
  enabled: boolean;
}

export interface ToolConfigResponse {
  available_tools: ToolInfo[];
  enabled_tools: string[];
}

export interface UserToolConfig {
  user_id: string;
  enabled_tools: string[];
  disabled_tools: string[];
  updated_at?: string;
}

// 获取所有可用工具及当前配置
export const getAvailableToolsConfig = async (): Promise<ToolConfigResponse> => {
  const response = await authAxios.get(`${API_BASE_URL}/tool-config/available-tools`);
  return response.data;
};

// 获取用户工具配置
export const getUserToolConfig = async (): Promise<UserToolConfig> => {
  const response = await authAxios.get(`${API_BASE_URL}/tool-config/my-config`);
  return response.data;
};

// 更新用户工具配置
export const updateToolConfig = async (enabledTools: string[]): Promise<{ success: boolean; message: string }> => {
  const response = await authAxios.post(`${API_BASE_URL}/tool-config/update`, {
    enabled_tools: enabledTools
  });
  return response.data;
};

// 重置工具配置
export const resetToolConfig = async (): Promise<{ success: boolean; message: string }> => {
  const response = await authAxios.delete(`${API_BASE_URL}/tool-config/reset`);
  return response.data;
};
