// The merchant's side: catalog with the trusted/untrusted line drawn in the
// open, mandates with an instant revoke, and orders with their receipts
// (frontend/DESIGN.md §7; other merchant views are sanctioned Phase-8 cuts).

import { useCallback, useEffect, useState } from 'react';
import { getCommerceCatalog, listCommerceOrders, listMandates, revokeMandate } from '../api';
import { formatMoney } from '../format';
import type { CatalogItemView, CommerceOrder, MandateView } from '../types';
import { ClaimChip, StateStamp } from '../components/commerce';

export function MerchantConsole() {
  const [items, setItems] = useState<CatalogItemView[]>([]);
  const [merchantName, setMerchantName] = useState('');
  const [version, setVersion] = useState(0);
  const [mandates, setMandates] = useState<MandateView[]>([]);
  const [orders, setOrders] = useState<CommerceOrder[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cat, mds, ords] = await Promise.all([
        getCommerceCatalog(),
        listMandates(),
        listCommerceOrders(),
      ]);
      setItems(cat.items);
      setMerchantName(cat.merchant.display_name);
      setVersion(cat.catalog_version);
      setMandates(mds);
      setOrders(ords);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the merchant view.');
    }
  }, []);

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
