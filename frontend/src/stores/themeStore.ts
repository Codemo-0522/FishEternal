import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Theme = 'light' | 'dark' | 'romantic';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  initializeTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      
      setTheme: (theme: Theme) => {
        set({ theme });
        // 更新DOM属性
        document.documentElement.setAttribute('data-theme', theme);
        // 更新body背景色
        const bgColors = {
          light: '#f0f2f5',
          dark: '#141414',
          romantic: '#fff5f7'
        };
        document.body.style.backgroundColor = bgColors[theme];
      },
      
      toggleTheme: () => {
        const currentTheme = get().theme;
        const themeOrder: Theme[] = ['light', 'dark', 'romantic'];
        const currentIndex = themeOrder.indexOf(currentTheme);
        const newTheme: Theme = themeOrder[(currentIndex + 1) % themeOrder.length];
        get().setTheme(newTheme);
      },
      
      initializeTheme: () => {
        const { theme } = get();
        get().setTheme(theme);
      },
    }),
    {
      name: 'theme-storage',
    }
  )
); 