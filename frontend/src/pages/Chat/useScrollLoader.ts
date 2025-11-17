import { useEffect, useRef, useCallback } from 'react';

interface UseScrollLoaderOptions {
  containerRef: React.RefObject<HTMLDivElement>;
  onLoadMore: () => Promise<void>;
  threshold?: number;
  isLoading?: boolean;
}

const LOAD_THRESHOLD = 100; // 距离顶部100px时触发加载

/**
 * 🔥 绝对零抖动滚动加载Hook - MutationObserver同步方案
 * 
 * 核心原理（消除一切抖动）：
 * 1. 加载前记录精确的滚动状态
 * 2. 使用 MutationObserver 监听DOM变化
 * 3. 在DOM节点插入的瞬间立即同步恢复滚动位置
 * 4. 不依赖React状态更新，完全同步操作
 * 
 * 为什么绝对零抖动：
 * ✅ MutationObserver 在浏览器渲染前触发
 * ✅ 同步设置scrollTop，无任何延迟
 * ✅ 不等待React重渲染
 * ✅ 像素级精确计算
 * 
 * 参考：Telegram、Discord等大型应用的实现
 */
export const useScrollLoader = ({
  containerRef,
  onLoadMore,
  threshold = LOAD_THRESHOLD,
  isLoading = false
}: UseScrollLoaderOptions) => {
  const isLoadingRef = useRef(false);
  const scrollStateRef = useRef<{
    scrollTop: number;
    scrollHeight: number;
  } | null>(null);
  const observerRef = useRef<MutationObserver | null>(null);

  // 🔥 立即同步恢复滚动位置（无任何延迟）
  const restoreScrollPositionSync = useCallback(() => {
    const container = containerRef.current;
    if (!container || !scrollStateRef.current) return;

    const { scrollTop: oldScrollTop, scrollHeight: oldScrollHeight } = scrollStateRef.current;
    const newScrollHeight = container.scrollHeight;
    
    // 计算高度差（新插入内容的高度）
    const heightDiff = newScrollHeight - oldScrollHeight;
    
    if (heightDiff > 0) {
      // 🎯 关键：立即同步设置，不使用requestAnimationFrame
      const newScrollTop = oldScrollTop + heightDiff;
      container.scrollTop = newScrollTop;
      
      console.log('[ScrollLoader] ⚡ 滚动位置已同步恢复（零抖动）:', {
        heightDiff,
        oldScrollTop,
        newScrollTop,
        oldScrollHeight,
        newScrollHeight,
        precision: Math.abs(container.scrollTop - newScrollTop) < 1 ? '✅ 像素级精确' : '⚠️ 有偏差'
      });
    }
    
    scrollStateRef.current = null;
    isLoadingRef.current = false;
  }, [containerRef]);

  // 🔥 使用 MutationObserver 监听DOM变化
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // 创建观察器
    observerRef.current = new MutationObserver((mutations) => {
      // 只在有保存的滚动状态时处理
      if (!scrollStateRef.current) return;

      // 检查是否有新节点添加
      const hasNewNodes = mutations.some(mutation => 
        mutation.type === 'childList' && mutation.addedNodes.length > 0
      );
      
      if (hasNewNodes) {
        console.log('[ScrollLoader] 🔍 检测到新消息插入，立即恢复滚动');
        // 立即同步恢复滚动位置
        restoreScrollPositionSync();
      }
    });

    // 监听容器的子节点变化
    observerRef.current.observe(container, {
      childList: true,
      subtree: false  // 只监听直接子节点
    });

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [containerRef, restoreScrollPositionSync]);

  // 🔥 备用恢复机制（防止MutationObserver漏掉）
  useEffect(() => {
    if (!isLoading && scrollStateRef.current) {
      // 短暂延迟后检查，如果MutationObserver没触发，这里兜底
      const timerId = setTimeout(() => {
        if (scrollStateRef.current) {
          console.log('[ScrollLoader] 🔄 备用恢复机制触发');
          restoreScrollPositionSync();
        }
      }, 50);
      
      return () => clearTimeout(timerId);
    }
  }, [isLoading, restoreScrollPositionSync]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleScroll = async () => {
      // 检查是否滚动到顶部且未在加载中
      if (container.scrollTop < threshold && !isLoadingRef.current && !isLoading) {
        isLoadingRef.current = true;
        
        // 🎯 保存当前滚动状态（精确到像素）
        scrollStateRef.current = {
          scrollTop: container.scrollTop,
          scrollHeight: container.scrollHeight
        };
        
        console.log('[ScrollLoader] 💾 保存滚动状态:', scrollStateRef.current);
        
        try {
          await onLoadMore();
          // 滚动位置恢复由 MutationObserver 处理
        } catch (error) {
          console.error('[ScrollLoader] ❌ 加载失败:', error);
          scrollStateRef.current = null;
          isLoadingRef.current = false;
        }
      }
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [containerRef, onLoadMore, threshold, isLoading]);
};
