import { Routes, Route, Navigate } from 'react-router-dom';
import { NavRail } from './components/NavRail';
import { Header } from './components/Header';
import { RunConsole } from './views/RunConsole';
import { BuyerConsole } from './views/BuyerConsole';
import { MerchantConsole } from './views/MerchantConsole';
import { ApprovalQueue } from './views/ApprovalQueue';
import { PolicyEditor } from './views/PolicyEditor';
import { EvalDashboard } from './views/EvalDashboard';
import { RedteamResults } from './views/RedteamResults';
import { AuditViewer } from './views/AuditViewer';

export default function App() {
  return (
    <div className="app-shell">
      <NavRail />
      <div className="app-main">
        <Header />
        <main className="app-content" id="main-content" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<BuyerConsole />} />
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
