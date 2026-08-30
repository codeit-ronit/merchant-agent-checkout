import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { NavRail } from './components/NavRail';
import { Header } from './components/Header';
import { RunConsole } from './views/RunConsole';
import { Home } from './views/Home';
import { BuyerConsole } from './views/BuyerConsole';
import { MerchantConsole } from './views/MerchantConsole';
import { ApprovalQueue } from './views/ApprovalQueue';
import { PolicyEditor } from './views/PolicyEditor';
import { EvalDashboard } from './views/EvalDashboard';
import { RedteamResults } from './views/RedteamResults';
import { AuditViewer } from './views/AuditViewer';

const CX_ROUTES = new Set(['/', '/buy', '/merchant']);

export default function App() {
  // cx-mode: the CONDUIT demo skin (ambient depth, glass, agent presence) on
  // the three demo-facing views; the under-the-hood operator views keep the
  // control-room look — two audiences, two registers, one app.
  const { pathname } = useLocation();
  const cx = CX_ROUTES.has(pathname);
  return (
    <div className={`app-shell${cx ? ' cx-mode' : ''}`}>
      {cx && (
        <div className="cx-ambient" aria-hidden="true">
          <div className="cx-glow cx-glow-a" />
          <div className="cx-glow cx-glow-b" />
          <div className="cx-glow cx-glow-c" />
          <div className="cx-grid" />
        </div>
      )}
      <NavRail />
      <div className="app-main">
        <Header />
        <main className="app-content" id="main-content" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/buy" element={<BuyerConsole />} />
            <Route path="/merchant" element={<MerchantConsole />} />
            <Route path="/runs" element={<RunConsole />} />
            <Route path="/approvals" element={<ApprovalQueue />} />
            <Route path="/policies" element={<PolicyEditor />} />
            <Route path="/evals" element={<EvalDashboard />} />
            <Route path="/redteam" element={<RedteamResults />} />
            <Route path="/audit" element={<AuditViewer />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
