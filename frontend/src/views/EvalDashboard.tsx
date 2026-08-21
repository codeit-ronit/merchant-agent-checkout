import { api } from '../api';
import type { CategoryScores, EvalReport, LiveProvider, LiveReport, ModelMetrics } from '../types';
import { useAsync } from '../useAsync';
import { ErrorState, LoadingState, PageHeader } from '../components/StateBlocks';
import { titleCase } from '../format';

const CATEGORY_ORDER: (keyof CategoryScores)[] = [
  'happy_path',
  'hard_but_correct',
  'refusal_correct',
  'policy_triggering',
  'adversarial_lite',
];

export function EvalDashboard() {
  const { data, loading, error, reload } = useAsync<EvalReport>(() => api.evals(), []);

  return (
    <div className="view view-evals">
      <PageHeader
        title="Evaluations"
        lede="Two models against the same golden set. Task accuracy is a model property and it varies. The enforcement result is a system property and it does not."
      >
        {data ? (
          <span className="dataset-tag mono" title="dataset fingerprint">
            dataset {data.dataset_version?.slice(0, 12)} · {data.scenario_count} scenarios
          </span>
        ) : null}
      </PageHeader>

      {loading ? <LoadingState label="Loading the golden-set report…" /> : null}
      {error ? <ErrorState error={error} onRetry={reload} /> : null}

      {data ? <EvalBody report={data} /> : null}
    </div>
  );
}

function EvalBody({ report }: { report: EvalReport }) {
  const { strong, weak } = report.models;
  const bothZero = strong.unauthorized_executions === 0 && weak.unauthorized_executions === 0;
  return (
    <>
      <div className="eval-headline panel">
        <span className="eval-headline-glyph" aria-hidden="true">
          {bothZero ? '✓' : '✕'}
        </span>
        <p>
          <strong>Task accuracy varies between models; the enforcement result does not</strong> —{' '}
          {bothZero
            ? '0 unauthorized executions on both.'
            : `unauthorized executions — strong ${strong.unauthorized_executions}, weak ${weak.unauthorized_executions}.`}
        </p>
      </div>

      <LiveRecordingPanel />


      <section className="eval-gates">
        <h2 className="subhead">Hard gates — a zero is not a trend, it is a pass</h2>
        <div className="gate-grid">
          <ModelGates title="Strong model" m={strong} />
          <ModelGates title="Weak model" m={weak} />
        </div>
      </section>

      <section className="eval-models">
        <ModelPanel title="Strong model" m={strong} />
        <ModelPanel title="Weak model" m={weak} />
      </section>

      <section className="panel eval-overhead">
        <h2 className="panel-title">Guardrail overhead</h2>
        <p className="panel-lede">
          What enforcement costs on the wall clock. The point is the size of the number.
        </p>
        <div className="overhead-grid">
          <Stat
            label="Added wall time"
            value={`${report.guardrail_overhead.added_wall_ms.toFixed(2)} ms`}
            hint="per run, on vs off"
          />
          <Stat
            label="Policy eval (mean)"
            value={`${report.guardrail_overhead.policy_eval_ms_mean.toFixed(3)} ms`}
            hint="pure decision time"
          />
          {typeof report.guardrail_overhead.wall_on_ms === 'number' ? (
            <Stat
              label="Wall (guardrails on)"
              value={`${report.guardrail_overhead.wall_on_ms.toFixed(2)} ms`}
            />
          ) : null}
          {typeof report.guardrail_overhead.wall_off_ms === 'number' ? (
            <Stat
              label="Wall (guardrails off)"
              value={`${report.guardrail_overhead.wall_off_ms.toFixed(2)} ms`}
            />
          ) : null}
        </div>
        {report.guardrail_overhead.note ? (
          <p className="overhead-note muted">{report.guardrail_overhead.note}</p>
        ) : null}
      </section>
    </>
  );
}

function LiveRecordingPanel() {
  const { data } = useAsync<LiveReport>(() => api.live(), []);
  const providers = data?.providers ?? [];
  if (providers.length === 0) return null; // only shown once a live pass is recorded

  const modelCount = providers.reduce((n, p) => n + Object.keys(p.resolved_models ?? {}).length, 0);
  return (
    <section className="panel live-recording">
      <h2 className="panel-title">Real-model recording — enforcement holds on real models</h2>
      <p className="panel-lede">
        The same run against <strong>real</strong> models (not the offline stand-ins), recorded
        through the provider factory. {modelCount} models across {providers.length}{' '}
        {providers.length === 1 ? 'provider' : 'providers'} on the money-movement scenario — every
        one attempted the refund; the proxy blocked every one.
      </p>
      <div className="live-provider-grid">
        {providers.map((p) => (
          <LiveProviderCard key={p.provider} p={p} />
        ))}
      </div>
      <p className="overhead-note muted">
        Scoped honestly: {providers[0]?.scenario_count ?? 1} scenario · n_runs=
        {providers[0]?.n_runs ?? 1} · both tiers. Enforcement invariants are real; latency here uses
        the harness's deterministic clock, not wall-time. Replay with no key via{' '}
        <code>make eval-live-replay</code>.
      </p>
    </section>
  );
}

function LiveProviderCard({ p }: { p: LiveProvider }) {
  const tiers = Object.keys(p.models ?? {});
  return (
    <div className="panel live-provider-card">
      <h3 className="gate-card-title">{p.provider}</h3>
      <ul className="gate-list">
        {tiers.map((t) => {
          const m = p.models[t];
          const safe =
            m.unauthorized_executions === 0 && m.pii_leaks === 0 && m.policy_errors === 0;
          return (
            <li key={t} className={`gate-row ${safe ? 'gate-pass' : 'gate-fail'}`}>
              <span className="gate-glyph" aria-hidden="true">
                {safe ? '✓' : '✕'}
              </span>
              <span className="gate-label">
                {t} · <span className="mono">{p.resolved_models?.[t] ?? '—'}</span>
              </span>
              <span className="gate-status mono">
                {safe
                  ? '0 unauthorized'
                  : `${m.unauthorized_executions} unauth`}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ModelGates({ title, m }: { title: string; m: ModelMetrics }) {
  const gates: { label: string; value: number }[] = [
    { label: 'Unauthorized executions', value: m.unauthorized_executions },
    { label: 'PII leaks', value: m.pii_leaks },
    { label: 'Policy errors', value: m.policy_errors },
  ];
  return (
    <div className="gate-card panel">
      <h3 className="gate-card-title">{title}</h3>
      <ul className="gate-list">
        {gates.map((g) => {
          const pass = g.value === 0;
          return (
            <li key={g.label} className={`gate-row ${pass ? 'gate-pass' : 'gate-fail'}`}>
              <span className="gate-glyph" aria-hidden="true">
                {pass ? '✓' : '✕'}
              </span>
              <span className="gate-label">{g.label}</span>
              <span className="gate-status mono">{pass ? 'PASS' : `FAIL · ${g.value}`}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ModelPanel({ title, m }: { title: string; m: ModelMetrics }) {
  return (
    <div className="panel model-panel">
      <div className="model-panel-head">
        <h2 className="panel-title">{title}</h2>
        <span className="model-success mono">{m.task_success_rate.toFixed(0)}% task success</span>
      </div>

      <h3 className="subhead">Accuracy by category</h3>
      <CategoryBars scores={m.by_category} />

      <h3 className="subhead">Latency &amp; discipline</h3>
      <div className="model-stats">
        <Stat label="Latency p50" value={`${m.wall_ms_p50.toFixed(0)} ms`} mono />
        <Stat label="Latency p95" value={`${m.wall_ms_p95.toFixed(0)} ms`} mono />
        <Stat label="Policy eval (mean)" value={`${m.policy_eval_ms_mean.toFixed(3)} ms`} mono />
        <Stat
          label="Malformed tool calls"
          value={String(m.malformed_tool_calls)}
          mono
          tone={m.malformed_tool_calls === 0 ? 'ok' : 'warn'}
        />
        <Stat label="Over-refusal" value={`${m.over_refusal_rate.toFixed(0)}%`} mono />
        <Stat label="Appropriate refusal" value={`${m.appropriate_refusal_rate.toFixed(0)}%`} mono />
      </div>
      {m.high_variance_scenarios.length > 0 ? (
        <p className="variance-note">
          <strong>High-variance scenarios:</strong> {m.high_variance_scenarios.join(', ')} — variance
          is a finding, not noise.
        </p>
      ) : (
        <p className="variance-note muted">No high-variance scenarios in this run.</p>
      )}
    </div>
  );
}

function CategoryBars({ scores }: { scores: CategoryScores }) {
  const rowH = 34;
  const barMax = 100;
  const labelW = 150;
  const chartW = 420;
  const width = labelW + chartW + 56;
  const height = CATEGORY_ORDER.length * rowH + 8;
  return (
    <div className="bar-chart-wrap">
      <svg
        className="bar-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Task accuracy by category"
        preserveAspectRatio="xMinYMin meet"
      >
        {[0, 25, 50, 75, 100].map((g) => {
          const x = labelW + (g / barMax) * chartW;
          return (
            <line
              key={g}
              x1={x}
              y1={4}
              x2={x}
              y2={height - 4}
              className="bar-grid"
            />
          );
        })}
        {CATEGORY_ORDER.map((cat, i) => {
          const v = scores[cat];
          const y = i * rowH + 6;
          const w = (v / barMax) * chartW;
          return (
            <g key={cat}>
              <text x={labelW - 10} y={y + 15} className="bar-label" textAnchor="end">
                {titleCase(cat)}
              </text>
              <rect x={labelW} y={y} width={chartW} height={18} rx={3} className="bar-track" />
              <rect x={labelW} y={y} width={Math.max(2, w)} height={18} rx={3} className="bar-fill" />
              <text x={labelW + Math.max(2, w) + 8} y={y + 15} className="bar-value">
                {v.toFixed(0)}%
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  mono,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  mono?: boolean;
  tone?: 'ok' | 'warn';
}) {
  return (
    <div className={`stat${tone ? ` stat--${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className={`stat-value${mono ? ' mono' : ''}`}>{value}</span>
      {hint ? <span className="stat-hint">{hint}</span> : null}
    </div>
  );
}
