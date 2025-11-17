import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './stores/authStore';
import { useThemeStore } from './stores/themeStore';
import Welcome from './pages/Welcome/Welcome'
import Chat from './pages/Chat/Chat';
import Call from './pages/Call/Call';
import ModelConfig from './pages/ModelConfig/ModelConfig';
import Moments from './pages/Moments/Moments';
import KnowledgeBase from './pages/KnowledgeBase/KnowledgeBase';
import KBMarketplace from './pages/KBMarketplace/KBMarketplace';
import './styles/themes.css';

// 受保护的路由组件
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? <>{children}</> : <Navigate to="/welcome" />;
};

const App: React.FC = () => {
  const { initializeAuth, isAuthenticated } = useAuthStore();
  const { initializeTheme } = useThemeStore();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const init = async () => {
      try {
        await initializeAuth();
        initializeTheme(); // 初始化主题
      } catch (error) {
        console.error('Failed to initialize app:', error);
      } finally {
        setIsLoading(false);
      }
    };

    init();
  }, [initializeAuth, initializeTheme]);

  if (isLoading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100%'
      }}>
        Loading...
      </div>
    );
  }

  return (
    <Router>
      <Routes>
        <Route
          path="/"
          element={
            isAuthenticated ? (
              <Navigate to="/chat" replace />
            ) : (
              <Navigate to="/welcome" replace />
            )
          }
        />
        <Route
          path="/welcome"
          element={
            isAuthenticated ? <Navigate to="/chat" replace /> : <Welcome />
          }
        />
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <Chat />
            </ProtectedRoute>
          }
        />
        <Route
          path="/call"
          element={
            <ProtectedRoute>
              <Call />
            </ProtectedRoute>
          }
        />
        <Route
          path="/model-config"
          element={
            <ProtectedRoute>
              <ModelConfig />
            </ProtectedRoute>
          }
        />
        <Route
          path="/moments/:sessionId"
          element={
            <ProtectedRoute>
              <Moments />
            </ProtectedRoute>
          }
        />
        <Route
          path="/knowledge-base"
          element={
            <ProtectedRoute>
              <KnowledgeBase />
            </ProtectedRoute>
          }
        />
        <Route
          path="/kb-marketplace"
          element={
            <ProtectedRoute>
              <KBMarketplace />
            </ProtectedRoute>
          }
        />
      </Routes>
    </Router>
  );
};

export default App; 