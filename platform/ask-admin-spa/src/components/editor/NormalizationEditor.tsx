import type { VizNormalization, VizNormCurrency, VizNormUom } from '../../api/types';

interface NormalizationEditorProps {
  value: VizNormalization | null;
  onChange(v: VizNormalization | null): void;
}

const listToStr = (a?: string[]) => (a ?? []).join(', ');
const strToList = (s: string) => s.split(',').map((t) => t.trim()).filter(Boolean);

const inputCls =
  'w-full text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400';

export function NormalizationEditor({ value, onChange }: NormalizationEditorProps) {
  const currency = value?.currency ?? null;
  const uom = value?.uom ?? null;

  function emit(next: VizNormalization) {
    const cleaned: VizNormalization = {};
    if (next.currency) cleaned.currency = next.currency;
    if (next.uom) cleaned.uom = next.uom;
    onChange(cleaned.currency || cleaned.uom ? cleaned : null);
  }
  const patchCurrency = (p: Partial<VizNormCurrency>) =>
    emit({ currency: { ...(currency ?? {}), ...p }, uom });
  const patchUom = (p: Partial<VizNormUom>) =>
    emit({ currency, uom: { ...(uom ?? {}), ...p } });

  return (
    <div className="flex flex-col gap-3">
      {/* Currency */}
      <div className="border border-gray-200 rounded p-2 flex flex-col gap-1.5">
        <label className="flex items-center gap-2 text-[11px] font-medium text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={!!currency}
            onChange={(e) => emit({ currency: e.target.checked ? (currency ?? {}) : null, uom })}
            className="rounded"
          />
          Currency normalization
        </label>
        {currency && (
          <div className="grid grid-cols-2 gap-1.5">
            <Labeled label="currency_field" title="Source currency code column (e.g. WAERK)">
              <input className={inputCls} value={currency.currency_field ?? ''}
                onChange={(e) => patchCurrency({ currency_field: e.target.value })} />
            </Labeled>
            <Labeled label="target_currency" title="Target currency (e.g. USD)">
              <input className={inputCls} value={currency.target_currency ?? ''}
                onChange={(e) => patchCurrency({ target_currency: e.target.value })} />
            </Labeled>
            <Labeled label="amount_fields" title="Comma-separated fields to convert">
              <input className={inputCls} value={listToStr(currency.amount_fields)}
                placeholder="net_value, …"
                onChange={(e) => patchCurrency({ amount_fields: strToList(e.target.value) })} />
            </Labeled>
            <Labeled label="rate_type" title="Exchange rate type (e.g. M = average)">
              <input className={inputCls} value={currency.rate_type ?? ''}
                onChange={(e) => patchCurrency({ rate_type: e.target.value })} />
            </Labeled>
            <Labeled label="exchange_rate_entity" title="Silver entity id holding exchange rates">
              <input className={inputCls} value={currency.exchange_rate_entity ?? ''}
                onChange={(e) => patchCurrency({ exchange_rate_entity: e.target.value })} />
            </Labeled>
          </div>
        )}
      </div>

      {/* UoM */}
      <div className="border border-gray-200 rounded p-2 flex flex-col gap-1.5">
        <label className="flex items-center gap-2 text-[11px] font-medium text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={!!uom}
            onChange={(e) => emit({ currency, uom: e.target.checked ? (uom ?? {}) : null })}
            className="rounded"
          />
          Unit-of-measure normalization
        </label>
        {uom && (
          <div className="grid grid-cols-2 gap-1.5">
            <Labeled label="source_uom_field" title="Source UoM column (e.g. MEINS)">
              <input className={inputCls} value={uom.source_uom_field ?? ''}
                onChange={(e) => patchUom({ source_uom_field: e.target.value })} />
            </Labeled>
            <Labeled label="base_uom_entity" title="Material-master silver id with base UoM">
              <input className={inputCls} value={uom.base_uom_entity ?? ''}
                onChange={(e) => patchUom({ base_uom_entity: e.target.value })} />
            </Labeled>
            <Labeled label="quantity_fields" title="Comma-separated quantity fields to convert">
              <input className={inputCls} value={listToStr(uom.quantity_fields)}
                placeholder="order_qty, …"
                onChange={(e) => patchUom({ quantity_fields: strToList(e.target.value) })} />
            </Labeled>
            <Labeled label="conversion_numerator" title="Numerator field (e.g. UMREZ)">
              <input className={inputCls} value={uom.conversion_numerator ?? ''}
                onChange={(e) => patchUom({ conversion_numerator: e.target.value })} />
            </Labeled>
            <Labeled label="conversion_denominator" title="Denominator field (e.g. UMREN)">
              <input className={inputCls} value={uom.conversion_denominator ?? ''}
                onChange={(e) => patchUom({ conversion_denominator: e.target.value })} />
            </Labeled>
            <Labeled label="conversion_formula" title="ASK SQL: quantity * (UMREZ / UMREN)">
              <input className={inputCls} value={uom.conversion_formula ?? ''}
                onChange={(e) => patchUom({ conversion_formula: e.target.value })} />
            </Labeled>
          </div>
        )}
      </div>
    </div>
  );
}

function Labeled({ label, title, children }: { label: string; title?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5" title={title}>
      <span className="text-[9px] font-mono text-gray-400">{label}</span>
      {children}
    </label>
  );
}
