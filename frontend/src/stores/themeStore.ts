import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Theme = 'light' | 'dark';

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
        document.body.style.backgroundColor = theme === 'dark' ? '#141414' : '#f0f2f5';
      },
      
      toggleTheme: () => {
        const currentTheme = get().theme;
        const newTheme: Theme = currentTheme === 'light' ? 'dark' : 'light';
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