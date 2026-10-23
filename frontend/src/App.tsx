import type { ReactElement } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Skeleton } from "./components/Bits";
import { Shell } from "./components/Shell";
import { Company } from "./pages/Company";
import { Dashboard } from "./pages/Dashboard";
import { Event } from "./pages/Event";
import { Feed } from "./pages/Feed";
import { Login } from "./pages/Login";
import { Quality } from "./pages/Quality";
import { useSession } from "./session";

function RequireUser({ children }: { children: ReactElement }) {
  const { user, ready } = useSession();
  const location = useLocation();
  if (!ready) return <div className="boot"><Skeleton lines={4} /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireUser><Shell /></RequireUser>}>
        <Route index element={<Dashboard />} />
        <Route path="news" element={<Feed />} />
        <Route path="news/:newsId" element={<Event />} />
        <Route path="company" element={<Company />} />
        <Route path="quality" element={<Quality />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
