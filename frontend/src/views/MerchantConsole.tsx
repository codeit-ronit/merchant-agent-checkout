// The merchant's side: catalog with the trusted/untrusted line drawn in the
// open, mandates with an instant revoke, and orders with their receipts
// (frontend/DESIGN.md §7; other merchant views are sanctioned Phase-8 cuts).

import { useCallback, useEffect, useState } from 'react';
import {
  getAgentRevenue,
  getCommerceCatalog,
  listCommerceOrders,
  listMandates,
  onboardStorefront,
  revokeMandate,
} from '../api';
import type { OnboardResult, RevenueView } from '../api';
import { formatMoney } from '../format';
import type { CatalogItemView, CommerceOrder, MandateView } from '../types';
import { ClaimChip, StateStamp } from '../components/commerce';

export function MerchantConsole() {
  const [items, setItems] = useState<CatalogItemView[]>([]);
  const [merchantName, setMerchantName] = useState('');
  const [version, setVersion] = useState(0);
  const [mandates, setMandates] = useState<MandateView[]>([]);
  const [orders, setOrders] = useState<CommerceOrder[]>([]);
  const [revenue, setRevenue] = useState<RevenueView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shopUrl, setShopUrl] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<OnboardResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cat, mds, ords, rev] = await Promise.all([
        getCommerceCatalog(),
        listMandates(),
        listCommerceOrders(),
        getAgentRevenue(),
      ]);
      setItems(cat.items);
      setMerchantName(cat.merchant.display_name);
      setVersion(cat.catalog_version);
      setMandates(mds);
      setOrders(ords);
      setRevenue(rev);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the merchant view.');
    }
  }, []);

  async function importStore() {
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      const res = await onboardStorefront(shopUrl);
      setImportResult(res);
      await refresh();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : 'The import could not run.');
    } finally {
      setImporting(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function revoke(id: string) {
    await revokeMandate(id);
    await refresh();
  }

  if (error) {
    return <p className="error-words" role="alert">{error}</p>;
  }

  return (
    <div className="merchant-shell">
      <div className="page-intro">
        <h1>Your storefront, sellable to agents</h1>
        <p className="muted">
          This is the merchant’s side of CONDUIT: the catalog agents shop from, the spending caps
          buyers have granted you, and every order with its receipt.
        </p>
      </div>

      {revenue && (
        <div className="rev-band" role="group" aria-label="The agent channel, in revenue terms">
          <div className="rev-stat">
            <span className="rev-num mono">{formatMoney(revenue.gross_captured_minor)}</span>
            <span className="rev-words">captured via the agent channel</span>
          </div>
          <div className="rev-stat">
            <span className="rev-num mono">{formatMoney(revenue.upsell_attributed_minor)}</span>
            <span className="rev-words">of it from accepted upsells (pre-tax)</span>
          </div>
          <div className="rev-stat">
            <span className="rev-num mono">{revenue.orders_captured}/{revenue.orders_placed}</span>
            <span className="rev-words">orders captured / placed</span>
          </div>
          <div className="rev-stat">
            <span className="rev-num mono">{revenue.payments_declined}</span>
            <span className="rev-words">declines — money returned, zero double charges</span>
          </div>
        </div>
      )}

      <div className="commerce-panel onboard-panel">
        <div className="panel-head">
          <h3>Make your own store agent-sellable</h3>
          <span className="muted small">paste a product or collection page URL</span>
        </div>
        <p className="muted small">
          If the page carries standard product markup (schema.org JSON-LD, microdata, or Open
          Graph — what mainstream store platforms emit), its items land in this catalog and become
          orderable on the <strong>Order</strong> page immediately. Structure only, never prose;
          INR only in this demo; imports never overwrite existing prices.
        </p>
        <div className="onboard-row">
          <input
            className="onboard-input mono"
            value={shopUrl}
            onChange={(e) => setShopUrl(e.target.value)}
            placeholder="https://your-store.example/products/…"
            aria-label="Storefront URL"
          />
          <button className="btn-cta onboard-btn" onClick={() => void importStore()}
            disabled={importing || !shopUrl.trim()}>
            {importing ? 'Reading…' : 'Import products'}
          </button>
        </div>
        {importError && <p className="error-words" role="alert">{importError}</p>}
        {importResult && (
          <div className="onboard-result">
            <p>
              <strong>{importResult.imported}</strong> item{importResult.imported === 1 ? '' : 's'}{' '}
              imported from <span className="mono">{importResult.source}</span> markup · catalog is
              now <span className="mono">v{importResult.catalog_version}</span>
              {importResult.imported > 0 && ' — try ordering one on the Order page'}
            </p>
            {importResult.items.length > 0 && (
              <ul className="onboard-items">
                {importResult.items.map((it) => (
                  <li key={it.item_id}>
                    <span className="mono small">{it.item_id}</span> {it.name}{' '}
                    <span className="mono">{formatMoney(it.price_minor)}</span>
                  </li>
                ))}
              </ul>
            )}
            {importResult.skipped.length > 0 && (
              <details className="onboard-skips">
                <summary className="muted small">
                  {importResult.skipped.length} skipped — every skip has a reason
                </summary>
                <ul className="muted small">
                  {importResult.skipped.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </details>
            )}
          </div>
        )}
      </div>

      <div className="commerce-panel">
        <div className="panel-head">
          <h3>Catalog — {merchantName}</h3>
          <ClaimChip kind="modelled" />
          <span className="muted small mono">v{version}</span>
        </div>
        <p className="muted small">
          Your descriptions are treated as <strong>untrusted data</strong> — an agent will never
          obey instructions written in them. The columns on the left are machine truth; the ones on
          the right are your words.
        </p>
        <div className="table-scroll">
          <table className="catalog-table">
            <thead>
              <tr>
                <th colSpan={4} className="trust-head">trusted · machine truth</th>
                <th colSpan={2} className="untrust-head">untrusted · your text</th>
              </tr>
              <tr>
                <th>id</th>
                <th>price</th>
                <th>stock</th>
                <th>attributes</th>
                <th>name</th>
                <th>description</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.item_id}>
                  <td className="mono small">{it.item_id}</td>
                  <td className="mono">{formatMoney(it.price_minor)}</td>
                  <td className="mono small">
                    {it.stock}
                    {it.stock_count != null ? ` (${it.stock_count})` : ''}
                  </td>
                  <td className="small">{it.attributes.join(', ')}</td>
                  <td className="untrust-cell">{it.name}</td>
                  <td className="untrust-cell small">{it.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="commerce-panel">
        <div className="panel-head">
          <h3>Mandates</h3>
          <ClaimChip kind="modelled" />
        </div>
        {mandates.length === 0 && (
          <p className="muted">None yet — buyers set money aside on the Buy view.</p>
        )}
        {mandates.map((m) => (
          <div key={m.mandate_id} className="mandate-row">
            <span className="mono">{m.mandate_id}</span>
            <StateStamp state={m.status} />
            <span className="mono">
              {formatMoney(m.remaining_minor)} / {formatMoney(m.locked_minor)}
            </span>
            {m.status === 'ACTIVE' ? (
              <button className="btn btn-danger" onClick={() => void revoke(m.mandate_id)}>
                Revoke now
              </button>
            ) : (
              <span className="muted small">nothing further can be spent</span>
            )}
          </div>
        ))}
      </div>

      <div className="commerce-panel">
        <div className="panel-head">
          <h3>Orders</h3>
          <span className="muted small">order ids are Razorpay-minted; settlement is the modelled rail</span>
        </div>
        {orders.length === 0 && <p className="muted">No orders yet.</p>}
        {orders.map((o) => (
          <div key={o.order_id} className="order-row">
            <span className="mono">{o.order_id}</span> <ClaimChip kind="real" />
            <span className="mono">{formatMoney(o.amount_minor)}</span>
            <span className="small muted mono">{o.mandate_id}</span>
            <span className="small">
              {o.payments.map((p) => (
                <span key={p.id} className="mono small">
                  {p.status}{' '}
                </span>
              ))}
              <ClaimChip kind="modelled" />
            </span>
            {Object.keys(o.upsells).length > 0 && (
              <span className="small muted">includes an accepted merchant offer</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
