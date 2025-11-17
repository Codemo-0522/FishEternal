// API配置
// 始终使用相对路径，通过 Vite 代理访问后端
// 这样可以：
// 1. 在开发环境：HTTPS前端(5173) -> Vite代理 -> HTTP后端(8000)
// 2. 在生产环境：前端和后端使用相同协议，避免混合内容错误
export const API_BASE_URL = '';  // 始终使用空字符串，强制使用相对路径

// 获取完整的API URL
// 此函数确保所有API请求都使用相对路径，通过Vite代理访问后端
export const getFullUrl = (path?: string): string => {
    if (!path) {
        return '';  // 返回空字符串，使用相对路径
    }
    
    if (path.startsWith('http://') || path.startsWith('https://')) {
        // 如果是完整URL，转换为相对路径以使用代理
        console.warn(`检测到绝对URL: ${path}，建议使用相对路径`);
        return path;  // 暂时返回原URL，但应该避免使用绝对URL
    }
    
    // 确保路径以 / 开头
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return normalizedPath;
};

// 构建API URL，始终使用当前页面的协议和域名
// 这是图片URL等需要完整URL的场景使用的辅助函数
export const buildFullUrl = (path: string): string => {
    const protocol = window.location.protocol; // 'https:' or 'http:'
    const host = window.location.host;
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${protocol}//${host}${normalizedPath}`;
}; 