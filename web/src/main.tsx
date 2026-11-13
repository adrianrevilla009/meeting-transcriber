import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";
import { auth } from "./api";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toasts";
import { RecorderProvider } from "./recorder/RecorderContext";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Meeting } from "./pages/Meeting";
import { Record } from "./pages/Record";
import { Search } from "./pages/Search";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 2000 } },
});

function App() {
  const [token, setToken] = useState(auth.get());

  useEffect(() => {
    const onUnauthorized = () => {
      auth.clear();
      setToken("");
    };
    window.addEventListener("mt:unauthorized", onUnauthorized);
    return () => window.removeEventListener("mt:unauthorized", onUnauthorized);
  }, []);

  if (!token) {
    return (
      <Login
        onLogin={(t) => {
          auth.set(t);
          queryClient.clear();
          setToken(t);
        }}
      />
    );
  }

  return (
    <RecorderProvider>
      <Routes>
        <Route
          element={
            <Layout
              onLogout={() => {
                auth.clear();
                setToken("");
              }}
            />
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="record" element={<Record />} />
          <Route path="meetings/:id" element={<Meeting />} />
          <Route path="search" element={<Search />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </RecorderProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <div className="aurora" aria-hidden />
          <App />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
