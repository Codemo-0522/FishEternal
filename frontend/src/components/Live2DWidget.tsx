import React, { useEffect, useRef, useState } from 'react';
import { useLive2DStore } from '../stores/live2dStore';
import { useLive2DPositionStore } from '../stores/live2dPositionStore';
import { live2dConfig } from '../config/live2d.config';

declare global {
  interface Window {
    L2Dwidget: any;
  }
}

const Live2DWidget: React.FC = () => {
  const { getModelUrl, currentModel } = useLive2DStore();
  const { visible, saveChatPagePosition, getChatPagePosition } = useLive2DPositionStore();
  const isFirstLoad = useRef(true);
  const previousPath = useRef(window.location.pathname);
  const savedModalPosition = useRef<{ right: string; bottom: string; hideDirection?: 'top' | 'right' | 'bottom' | 'left' } | null>(null);

  useEffect(() => {
    if (!live2dConfig.enabled) return;

    // 完全清理函数
    const cleanup = () => {
      // 清除所有Live2D相关DOM元素
      const elements = document.querySelectorAll('[id^="live2d"], canvas[id="live2dcanvas"]');
      elements.forEach(el => el.remove());
      
      // 将L2Dwidget设置为undefined（不能delete window属性）
      if (window.L2Dwidget) {
        window.L2Dwidget = undefined;
      }
      
    };

    const initLive2D = () => {
      if (window.L2Dwidget) {
        try {
          window.L2Dwidget.init({
            pluginRootPath: 'live2dw/',
            pluginJsPath: 'lib/',
            pluginModelPath: 'assets/',
            tagMode: false,
            debug: false,
            model: {
              jsonPath: getModelUrl(),
              scale: 1
            },
            display: live2dConfig.display,
            mobile: live2dConfig.mobile,
            react: live2dConfig.react
          });
          
          
          // 等待canvas渲染完成
          let retryCount = 0;
          const maxRetries = 20;
          const retryInterval = setInterval(() => {
            const canvas = document.getElementById('live2dcanvas') || document.querySelector('canvas');
            if (canvas) {
              clearInterval(retryInterval);
              fixPosition();
              enableDragging();
            } else {
              retryCount++;
              if (retryCount >= maxRetries) {
                clearInterval(retryInterval);
              }
            }
          }, 200);
        } catch (error) {
        }
      }
    };

    const loadLive2D = () => {
      // 首次加载且L2Dwidget已存在（由HTML中的script加载）
      if (isFirstLoad.current && window.L2Dwidget && typeof window.L2Dwidget.init === 'function') {
        console.log('首次加载，L2Dwidget已存在，直接初始化');
        isFirstLoad.current = false;
        // 先清理旧的canvas
        const oldCanvas = document.getElementById('live2dcanvas');
        if (oldCanvas) {
          oldCanvas.remove();
        }
        setTimeout(() => initLive2D(), 100);
        return;
      }
      
      // 模型切换，需要重新加载脚本
      console.log('模型切换，重新加载Live2D脚本...');
      isFirstLoad.current = false;
      cleanup();
      
      // 删除旧的脚本标签
      const oldScript = document.querySelector('script[src*="L2Dwidget"]');
      if (oldScript) {
        oldScript.remove();
      }
      
      // 重新加载脚本
      const script = document.createElement('script');
      script.src = 'https://fastly.jsdelivr.net/npm/live2d-widget@3.1.4/lib/L2Dwidget.min.js';
      script.async = true;
      
      script.onload = () => {
        setTimeout(() => initLive2D(), 300);
      };
      
      script.onerror = () => {
      };
      
      document.head.appendChild(script);
    };

    const fixPosition = () => {
      const canvas = (document.getElementById('live2dcanvas') || document.querySelector('canvas')) as HTMLCanvasElement;
      if (canvas) {
        canvas.style.position = 'fixed';
        canvas.style.right = '0px';
        canvas.style.bottom = '0px';
        canvas.style.left = 'auto';
        canvas.style.top = 'auto';
        canvas.style.zIndex = '999';
        canvas.style.pointerEvents = 'auto';
        canvas.style.display = visible ? 'block' : 'none';
      } else {
      }
    };

    const enableDragging = () => {
      const canvas = (document.getElementById('live2dcanvas') || document.querySelector('canvas')) as HTMLCanvasElement;
      if (!canvas) {
        return;
      }
      
      
      // 从localStorage读取保存的缩放比例
      const savedScale = localStorage.getItem('live2d-scale');
      let currentScale = savedScale ? parseFloat(savedScale) : 1.0;
      
      // 应用初始缩放
      canvas.style.transform = `scale(${currentScale})`;
      canvas.style.transformOrigin = 'bottom right';

      let isDragging = false;
      let startX = 0;
      let startY = 0;
      let initialRight = 0;
      let initialBottom = 0;

      const onMouseDown = (e: MouseEvent) => {
        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;
        
        const rect = canvas.getBoundingClientRect();
        initialRight = window.innerWidth - rect.right;
        initialBottom = window.innerHeight - rect.bottom;
        
        canvas.style.cursor = 'grabbing';
        // 拖拽时禁用transition，避免延迟
        canvas.style.transition = 'none';
        e.preventDefault();
      };

      const onMouseMove = (e: MouseEvent) => {
        if (!isDragging) return;
        
        const deltaX = startX - e.clientX;
        const deltaY = startY - e.clientY;
        
        const newRight = initialRight + deltaX;
        const newBottom = initialBottom + deltaY;
        
        canvas.style.right = newRight + 'px';
        canvas.style.bottom = newBottom + 'px';
        canvas.style.left = 'auto';
        canvas.style.top = 'auto';
      };

      const onMouseUp = () => {
        isDragging = false;
        canvas.style.cursor = 'grab';
        canvas.style.transition = '';
        
        // 只在Chat页面才保存位置
        const currentPagePath = window.location.pathname;
        if (currentPagePath === '/chat') {
          const rect = canvas.getBoundingClientRect();
          const currentRight = window.innerWidth - rect.right;
          const currentBottom = window.innerHeight - rect.bottom;
          saveChatPagePosition({ right: currentRight, bottom: currentBottom });
        }
      };

      canvas.style.cursor = 'grab';
      canvas.style.userSelect = 'none';
      
      canvas.addEventListener('mousedown', onMouseDown);
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
      

      // 双指缩放相关变量
      let initialDistance = 0;
      let initialScale = currentScale;

      const onTouchStart = (e: TouchEvent) => {
        if (e.touches.length === 2) {
          // 双指触摸 - 缩放模式
          const touch1 = e.touches[0];
          const touch2 = e.touches[1];
          initialDistance = Math.hypot(
            touch2.clientX - touch1.clientX,
            touch2.clientY - touch1.clientY
          );
          initialScale = currentScale;
          isDragging = false;
        } else if (e.touches.length === 1) {
          // 单指触摸 - 拖拽模式
          isDragging = true;
          const touch = e.touches[0];
          startX = touch.clientX;
          startY = touch.clientY;
          
          const rect = canvas.getBoundingClientRect();
          initialRight = window.innerWidth - rect.right;
          initialBottom = window.innerHeight - rect.bottom;
          
          // 拖拽时禁用transition
          canvas.style.transition = 'none';
        }
        
        e.preventDefault();
      };

      const onTouchMove = (e: TouchEvent) => {
        if (e.touches.length === 2) {
          // 双指缩放
          const touch1 = e.touches[0];
          const touch2 = e.touches[1];
          const currentDistance = Math.hypot(
            touch2.clientX - touch1.clientX,
            touch2.clientY - touch1.clientY
          );
          
          const scale = (currentDistance / initialDistance) * initialScale;
          currentScale = Math.max(0.3, Math.min(3.0, scale));
          
          canvas.style.transform = `scale(${currentScale})`;
          canvas.style.transformOrigin = 'bottom right';
          
          localStorage.setItem('live2d-scale', currentScale.toString());
          
          e.preventDefault();
        } else if (e.touches.length === 1 && isDragging) {
          // 单指拖拽
          const touch = e.touches[0];
          const deltaX = startX - touch.clientX;
          const deltaY = startY - touch.clientY;
          
          const newRight = initialRight + deltaX;
          const newBottom = initialBottom + deltaY;
          
          canvas.style.right = newRight + 'px';
          canvas.style.bottom = newBottom + 'px';
          canvas.style.left = 'auto';
          canvas.style.top = 'auto';
        }
      };

      const onTouchEnd = (e: TouchEvent) => {
        if (e.touches.length === 0) {
          isDragging = false;
          canvas.style.transition = '';
          
          // 只在Chat页面才保存位置
          const currentPagePath = window.location.pathname;
          if (currentPagePath === '/chat') {
            const rect = canvas.getBoundingClientRect();
            const currentRight = window.innerWidth - rect.right;
            const currentBottom = window.innerHeight - rect.bottom;
            saveChatPagePosition({ right: currentRight, bottom: currentBottom });
          }
        }
      };

      canvas.addEventListener('touchstart', onTouchStart, { passive: false });
      canvas.addEventListener('touchmove', onTouchMove, { passive: false });
      canvas.addEventListener('touchend', onTouchEnd);
      
      // 添加滚轮缩放功能
      const onWheel = (e: WheelEvent) => {
        e.preventDefault();
        
        // 计算缩放增量
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        currentScale = Math.max(0.3, Math.min(3.0, currentScale + delta));
        
        // 应用缩放
        canvas.style.transform = `scale(${currentScale})`;
        canvas.style.transformOrigin = 'bottom right';
        
        // 保存到localStorage
        localStorage.setItem('live2d-scale', currentScale.toString());
        
      };
      
      canvas.addEventListener('wheel', onWheel, { passive: false });
      
    };

    loadLive2D();
    
    // 清理函数：组件卸载时执行
    return () => {
      // 清除所有Live2D相关DOM元素
      const elements = document.querySelectorAll('[id^="live2d"], canvas[id="live2dcanvas"]');
      elements.forEach(el => el.remove());
    };
  }, [currentModel, getModelUrl]);

  // 监听visible状态变化，实时更新显示/隐藏
  useEffect(() => {
    const canvas = document.getElementById('live2dcanvas') as HTMLCanvasElement;
    if (canvas) {
      canvas.style.display = visible ? 'block' : 'none';
      
      // 点击显示按钮后，直接恢复到右下角
      if (visible) {
        canvas.style.right = '0px';
        canvas.style.bottom = '0px';
        canvas.style.transition = 'right 0.3s ease, bottom 0.3s ease';
        
        // 清除所有保存的位置状态
        savedModalPosition.current = null;
      }
    }
  }, [visible]);

  // 监听路由变化
  useEffect(() => {
    const handleRouteChange = () => {
      const newPath = window.location.pathname;
      const oldPath = previousPath.current;
      
      if (oldPath === newPath) return;
      
      const canvas = document.getElementById('live2dcanvas') as HTMLCanvasElement;
      if (!canvas) return;
      
      // 如果模态框处于打开状态，先清除保存的位置并恢复
      if (savedModalPosition.current) {
        canvas.style.right = savedModalPosition.current.right;
        canvas.style.bottom = savedModalPosition.current.bottom;
        savedModalPosition.current = null;
      }
      
      // 离开Chat页面 -> 其他页面
      if (oldPath === '/chat' && newPath !== '/chat') {
        const rect = canvas.getBoundingClientRect();
        const right = window.innerWidth - rect.right;
        const bottom = window.innerHeight - rect.bottom;
        saveChatPagePosition({ right, bottom });
        
        canvas.style.right = '0px';
        canvas.style.bottom = '0px';
      }
      // 其他页面 -> Chat页面
      else if (oldPath !== '/chat' && newPath === '/chat') {
        const saved = getChatPagePosition();
        if (saved) {
          canvas.style.right = `${saved.right}px`;
          canvas.style.bottom = `${saved.bottom}px`;
        } else {
          canvas.style.right = '0px';
          canvas.style.bottom = '0px';
        }
        canvas.style.display = visible ? 'block' : 'none';
      }
      // 其他页面之间切换
      else if (oldPath !== '/chat' && newPath !== '/chat') {
        canvas.style.right = '0px';
        canvas.style.bottom = '0px';
      }
      
      previousPath.current = newPath;
    };

    window.addEventListener('popstate', handleRouteChange);
    
    const originalPushState = window.history.pushState;
    const originalReplaceState = window.history.replaceState;
    
    window.history.pushState = function(...args) {
      originalPushState.apply(window.history, args);
      handleRouteChange();
    };
    
    window.history.replaceState = function(...args) {
      originalReplaceState.apply(window.history, args);
      handleRouteChange();
    };

    return () => {
      window.removeEventListener('popstate', handleRouteChange);
      window.history.pushState = originalPushState;
      window.history.replaceState = originalReplaceState;
    };
  }, [getChatPagePosition, saveChatPagePosition]);

  // 监听模态框和抽屉的打开/关闭
  useEffect(() => {
    const checkModalAndDrawer = () => {
      const canvas = document.getElementById('live2dcanvas') as HTMLCanvasElement;
      if (!canvas) return;

      // 检查当前是否在Chat页面（实时获取）
      const currentIsChatPage = window.location.pathname === '/chat';

      // 检查是否有模态框或抽屉打开
      const hasModal = document.querySelector('.ant-modal-wrap') !== null;
      const hasDrawer = document.querySelector('.ant-drawer-open') !== null;
      const shouldHide = hasModal || hasDrawer;

      if (shouldHide && !savedModalPosition.current) {
        // 在Chat页面，从 store 获取保存的位置；其他页面使用当前canvas位置
        let currentRight: string;
        let currentBottom: string;
        
        if (currentIsChatPage) {
          const savedPos = getChatPagePosition();
          currentRight = savedPos ? `${savedPos.right}px` : (canvas.style.right || '0px');
          currentBottom = savedPos ? `${savedPos.bottom}px` : (canvas.style.bottom || '0px');
        } else {
          currentRight = canvas.style.right || '0px';
          currentBottom = canvas.style.bottom || '0px';
        }
        
        // 计算宠物当前位置
        const rect = canvas.getBoundingClientRect();
        const distanceToRight = window.innerWidth - rect.right;
        const distanceToLeft = rect.left;
        const distanceToTop = rect.top;
        const distanceToBottom = window.innerHeight - rect.bottom;
        
        // 找到最近的边缘
        const minDistance = Math.min(distanceToRight, distanceToLeft, distanceToTop, distanceToBottom);
        let hideDirection: 'top' | 'right' | 'bottom' | 'left';
        
        if (minDistance === distanceToRight) {
          hideDirection = 'right';
          canvas.style.right = '-500px';
        } else if (minDistance === distanceToLeft) {
          hideDirection = 'left';
          canvas.style.right = `${window.innerWidth + 500}px`;
        } else if (minDistance === distanceToTop) {
          hideDirection = 'top';
          canvas.style.bottom = `${window.innerHeight + 500}px`;
        } else {
          hideDirection = 'bottom';
          canvas.style.bottom = '-500px';
        }
        
        savedModalPosition.current = {
          right: currentRight,
          bottom: currentBottom,
          hideDirection
        };
        
        canvas.style.transition = 'right 0.3s ease, bottom 0.3s ease';
      } else if (!shouldHide && savedModalPosition.current) {
        // 模态框关闭，恢复位置
        if (currentIsChatPage) {
          canvas.style.right = savedModalPosition.current.right;
          canvas.style.bottom = savedModalPosition.current.bottom;
        } else {
          canvas.style.right = '0px';
          canvas.style.bottom = '0px';
        }
        canvas.style.transition = 'right 0.3s ease, bottom 0.3s ease';
        savedModalPosition.current = null;
      }
      // 模态框关闭但没有savedModalPosition（可能是用户隐藏了宠物后关闭模态框）
      else if (!shouldHide && !savedModalPosition.current) {
        // 检查宠物是否在屏幕外
        const currentRight = parseInt(canvas.style.right) || 0;
        const currentBottom = parseInt(canvas.style.bottom) || 0;
        
        if (currentRight < -100 || currentRight > window.innerWidth || 
            currentBottom < -100 || currentBottom > window.innerHeight) {
          // 在屏幕外，恢复到正确位置
          if (currentIsChatPage) {
            const saved = getChatPagePosition();
            if (saved) {
              canvas.style.right = `${saved.right}px`;
              canvas.style.bottom = `${saved.bottom}px`;
            } else {
              canvas.style.right = '0px';
              canvas.style.bottom = '0px';
            }
          } else {
            canvas.style.right = '0px';
            canvas.style.bottom = '0px';
          }
        }
      }
    };

    // 使用MutationObserver监听DOM变化，但限制触发频率
    let timeoutId: NodeJS.Timeout | null = null;
    const observer = new MutationObserver(() => {
      // 防抖，避免频繁触发
      if (timeoutId) clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        checkModalAndDrawer();
      }, 50);
    });

    // 只监听body的直接子节点，不监听深层子树
    observer.observe(document.body, {
      childList: true,
      subtree: false,
      attributes: false,
    });

    // 初始检查
    checkModalAndDrawer();

    return () => {
      observer.disconnect();
    };
  }, []);

  return null;
};

export default Live2DWidget;
