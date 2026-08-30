import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { NavRail } from './components/NavRail';
import { Header } from './components/Header';
import { TopNav } from './components/TopNav';
import { RunConsole } from './views/RunConsole';
import { Home } from './views/Home';
import { BuyerConsole } from './views/BuyerConsole';
import { MerchantConsole } from './views/MerchantConsole';
import { ApprovalQueue } from './views/ApprovalQueue';
import { PolicyEditor } from './views/PolicyEditor';
import { EvalDashboard } from './views/EvalDashboard';
import { RedteamResults } from './views/RedteamResults';
import { AuditViewer } from './views/AuditViewer';

const PRODUCT_ROUTES = new Set(['/', '/buy', '/merchant']);

// Two shells, one app. The product routes are the demo — a standalone site
// with a navbar, no admin chrome. The operator routes are SENTINEL's control
// room and keep the rail. The product links to the control room as "Under
// the hood"; the control room is never the headline.
export default function App() {
  const { pathname } = useLocation();
  const product = PRODUCT_ROUTES.has(pathname);

  const routes = (
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
  );

  if (product) {
    return (
      <div className="site cx-mode">
        <TopNav />
        <main className="site-main" id="main-content" tabIndex={-1}>
          {routes}
        </main>
      </div>
    );
  }
  return (
    <div className="app-shell">
      <NavRail />
      <div className="app-main">
        <Header />
        <main className="app-content" id="main-content" tabIndex={-1}>
          {routes}
        </main>
      </div>
    </div>
  );
}
