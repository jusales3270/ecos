import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthProvider, ProtectedRoute } from "./auth";
import { AppShell } from "./components";
import {
  AdminPage,
  ApprovalsPage,
  AuditPage,
  ExecutionsPage,
  KnowledgePage,
  LoginPage,
  OverviewPage,
  SessionDetailPage,
  SessionsPage
} from "./pages";
import "./styles.css";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "sessions", element: <SessionsPage /> },
      { path: "sessions/:id", element: <SessionDetailPage /> },
      { path: "approvals", element: <ApprovalsPage /> },
      { path: "executions", element: <ExecutionsPage /> },
      { path: "knowledge", element: <KnowledgePage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "admin", element: <AdminPage /> }
    ]
  }
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </StrictMode>
);
