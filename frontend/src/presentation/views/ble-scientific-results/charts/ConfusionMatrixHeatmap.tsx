import { useState } from 'react';
import NoDataNotice from '../NoDataNotice';

/** RQ1 capture-disjoint/FUTURE confusion matrices -- `matrix[trueLabel][predictedLabel]`
 * exactly SplitEvaluationReport.confusion_matrix's own dict-of-dicts shape.
 * No heatmap primitive exists anywhere in this codebase or in recharts, so
 * this is a small CSS-grid pattern: each cell's background intensity is a
 * simple linear interpolation of its own count against the matrix max --
 * a display-only computation, never a statistic.
 *
 * Paper-representation pass (2026-08-17): added a raw-count/row-normalized
 * toggle. The normalized view divides each cell by its own true-class row
 * total -- the exact same row-normalization
 * `paper_figure_aggregations.normalize_confusion_matrix` performs
 * server-side for the manuscript's PDF export -- computed here client-side
 * from the SAME already-fetched real counts (never a second network call,
 * never a different number than the color-intensity denominator above). */
export default function ConfusionMatrixHeatmap({
  matrix,
  noDataReason,
}: {
  matrix: Record<string, Record<string, number>> | null | undefined;
  noDataReason: string;
}) {
  const [normalized, setNormalized] = useState(false);
  const labels = matrix ? Object.keys(matrix) : [];
  if (!matrix || labels.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const maxCount = Math.max(1, ...labels.flatMap((t) => labels.map((p) => matrix[t]?.[p] ?? 0)));
  const rowTotals = Object.fromEntries(labels.map((t) => [t, labels.reduce((sum, p) => sum + (matrix[t]?.[p] ?? 0), 0)]));

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setNormalized((v) => !v)}
          className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10.5px] font-semibold text-slate-300 hover:bg-slate-800"
        >
          {normalized ? 'Ver conteos crudos' : 'Ver normalizado por clase verdadera (%)'}
        </button>
      </div>
      <div className="overflow-x-auto">
        <div
          role="table"
          aria-label="Confusion matrix"
          className="inline-grid gap-px bg-slate-800"
          style={{ gridTemplateColumns: `auto repeat(${labels.length}, minmax(48px, 1fr))` }}
        >
          <div />
          {labels.map((p) => (
            <div key={`col-${p}`} className="bg-slate-950 px-2 py-1 text-center text-[10px] text-slate-400">{p}</div>
          ))}
          {labels.map((t) => (
            <div key={`row-${t}`} className="contents">
              <div className="bg-slate-950 px-2 py-1 text-right text-[10px] text-slate-400">{t}</div>
              {labels.map((p) => {
                const count = matrix[t]?.[p] ?? 0;
                const intensity = count / maxCount;
                const rowTotal = rowTotals[t];
                const pct = rowTotal > 0 ? (100 * count) / rowTotal : 0;
                return (
                  <div
                    key={`${t}-${p}`}
                    data-testid="confusion-cell"
                    className="flex flex-col items-center justify-center py-2 text-xs font-mono text-slate-100"
                    style={{ backgroundColor: `rgba(43, 108, 176, ${0.12 + 0.68 * intensity})` }}
                  >
                    {normalized ? (
                      <>
                        <span>{pct.toFixed(1)}%</span>
                        <span className="text-[9px] text-slate-300/80">n={count}</span>
                      </>
                    ) : (
                      count
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
