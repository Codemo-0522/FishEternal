/**
 * 移动端真实视口高度解决方案
 * 
 * 问题：
 * 移动端浏览器的地址栏、底部工具栏会占用空间，导致 100vh 不准确
 * iOS Safari、Chrome、各种国产浏览器都有这个问题
 * 
 * 解决方案：
 * 1. 优先使用 CSS dvh (dynamic viewport height) - 现代浏览器自动处理
 * 2. Fallback: 使用 JavaScript 动态计算并设置 CSS 变量 --real-vh
 * 3. 监听 resize 事件实时更新
 */

let isInitialized = false;

/**
 * 计算并设置真实的 vh 值
 */
function setRealVH(): void {
  // 获取实际可视窗口高度
  const vh = window.innerHeight * 0.01;
  
  // 设置 CSS 变量 --real-vh
  document.documentElement.style.setProperty('--real-vh', `${vh}px`);
  
  console.log('[ViewportHeight] 更新真实视口高度:', window.innerHeight, 'px');
}

/**
 * 初始化视口高度处理
 */
export function initViewportHeight(): void {
  if (isInitialized) {
    return;
  }

  // 首次设置
  setRealVH();

  // 监听窗口大小变化（包括地址栏显示/隐藏）
  let resizeTimer: number | null = null;
  
  window.addEventListener('resize', () => {
    // 防抖处理，避免频繁计算
    if (resizeTimer) {
      clearTimeout(resizeTimer);
    }
    
    resizeTimer = window.setTimeout(() => {
      setRealVH();
      resizeTimer = null;
    }, 100);
  });

  // 监听屏幕方向变化
  window.addEventListener('orientationchange', () => {
    // 延迟一下，等待浏览器完成旋转
    setTimeout(() => {
      setRealVH();
    }, 200);
  });

  // iOS Safari 特殊处理：滚动时地址栏可能显示/隐藏
  if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
    // 使用 visualViewport API (iOS 13+)
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', () => {
        setRealVH();
      });
    }
  }

  isInitialized = true;
  console.log('[ViewportHeight] 视口高度处理已初始化');
}

/**
 * 获取当前真实视口高度
 */
export function getRealViewportHeight(): number {
  return window.innerHeight;
}

/**
 * 检查是否支持 dvh 单位
 */
export function supportsDVH(): boolean {
  if (typeof CSS === 'undefined' || !CSS.supports) {
    return false;
  }
  return CSS.supports('height', '100dvh');
}

