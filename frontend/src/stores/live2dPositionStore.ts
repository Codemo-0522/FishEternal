import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface Live2DPositionState {
  visible: boolean;
  position: { right: number; bottom: number } | null;
  chatPagePosition: { right: number; bottom: number } | null;
  isHiddenByModal: boolean;
  
  setVisible: (visible: boolean) => void;
  setPosition: (position: { right: number; bottom: number }) => void;
  saveChatPagePosition: (position: { right: number; bottom: number }) => void;
  getChatPagePosition: () => { right: number; bottom: number } | null;
  hideByModal: () => void;
  showByModal: () => void;
  resetToDefault: () => void;
}

export const useLive2DPositionStore = create<Live2DPositionState>()(
  persist(
    (set, get) => ({
      visible: true,
      position: null,
      chatPagePosition: null,
      isHiddenByModal: false,
      
      setVisible: (visible: boolean) => {
        set({ visible });
      },
      
      setPosition: (position: { right: number; bottom: number }) => {
        set({ position });
      },
      
      saveChatPagePosition: (position: { right: number; bottom: number }) => {
        set({ chatPagePosition: position });
      },
      
      getChatPagePosition: () => {
        return get().chatPagePosition;
      },
      
      hideByModal: () => {
        set({ isHiddenByModal: true });
      },
      
      showByModal: () => {
        set({ isHiddenByModal: false });
      },
      
      resetToDefault: () => {
        set({ position: { right: 0, bottom: 0 } });
      },
    }),
    {
      name: 'live2d-position-storage',
    }
  )
);
