import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, RadioTower, Microscope, DatabaseZap, ShieldCheck, BrainCircuit, BadgeCheck, ScanSearch, Boxes, RefreshCcw, FlaskConical } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { FingerprintingDashboardSummary } from '../../shared/types';

const api = new ApiService();

const kpiCardClass =
  'rounded-3xl border border-slate-200 bg-white/90 p-5 shadow-[0_22px_50px_rgba(15,23,42,0.08)] backdrop-blur';

const workflow = [
  {
    step: '01',
    title: 'Live Monitor',
    route: '/spectrum',
    icon: RadioTower,
    reason: 'Busca la señal, ajusta frecuencia y ganancia, y verifica que la banda útil está limpia antes de capturar.',
  },
  {
    step: '02',
    title: 'Capture Lab',
    route: '/capture',
    icon: Microscope,
    reason: 'Captura IQ real y define desde origen si la muestra pertenece a train, val o predict. Ese propósito manda todo el flujo posterior.',
  },
  {
    step: '03',
    title: 'Dataset Builder',
    route: '/dataset-builder',
    icon: DatabaseZap,
    reason: 'Acepta, marca como dudosa o rechaza la captura antes de incorporarla al dataset serio.',
  },
  {
    step: '04',
    title: 'RF Experiment Lab',
    route: '/rf-experiment-lab',
    icon: FlaskConical,
    reason: 'Ejecuta E5, E1 y E3 con splits disjuntos, trazabilidad de papers, artefactos reproducibles y benchmark cientifico.',
  },
  {
    step: '05',
    title: 'Training',
    route: '/training',
    icon: BrainCircuit,
    reason: 'Usa automáticamente las capturas marcadas como train para construir el modelo inicial.',
  },
  {
    step: '06',
    title: 'Retraining',
    route: '/retraining',
    icon: RefreshCcw,
    reason: 'Reentrena cuando han entrado nuevas capturas train o hay drift temporal, de hardware o de escenario.',
  },
  {
    step: '07',
    title: 'Validation',
    route: '/validation',
    icon: BadgeCheck,
    reason: 'Mide rendimiento con muestras reservadas como val. No deben haber participado en entrenamiento.',
  },
  {
    step: '08',
    title: 'Inference',
    route: '/inference',
    icon: ScanSearch,
    reason: 'Ejecuta predicción solo sobre capturas nuevas marcadas como predict.',
  },
  {
    step: '09',
    title: 'Models',
    route: '/models',
    icon: Boxes,
    reason: 'Consulta snapshots, artefactos, métricas y estado del modelo activo.',
  },
];

export const FingerprintingOverviewView: React.FC = () => {
  const [dashboard, setDashboard] = useState<FingerprintingDashboardSummary | null>(null);

  useEffect(() => {
    api.getFingerprintingDashboard().then(setDashboard).catch((error) => {
      console.error('Failed to load fingerprinting dashboard', error);
    });
  }, []);

  return (
    <div className="min-h-full bg-[radial-gradient(circle_at_top_left,_rgba(217,119,6,0.18),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(15,118,110,0.16),_transparent_32%),linear-gradient(180deg,_#f8fafc,_#eef4ff)] p-6">
      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
        <div className="rounded-[2rem] border border-slate-200 bg-slate-950 px-8 py-10 text-slate-50 shadow-[0_35px_90px_rgba(15,23,42,0.28)]">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-amber-400/30 bg-amber-300/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-amber-200">
            RF Fingerprinting Station
          </div>
          <h1 className="max-w-3xl font-serif text-4xl leading-tight">
            El flujo correcto no gira alrededor de una pestaña extra. Gira alrededor del propósito científico de cada captura.
          </h1>
          <p className="mt-5 max-w-3xl text-sm leading-7 text-slate-300">
            `Capture Lab` es ahora la puerta de entrada real. Allí se decide si una captura pertenece a entrenamiento,
            validación o predicción. Después cada pestaña detecta automáticamente solo las muestras de su split.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to="/spectrum"
              className="rounded-full bg-amber-400 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-amber-300"
            >
              Start With Live Monitor
            </Link>
            <Link
              to="/capture"
              className="rounded-full border border-slate-700 px-5 py-3 text-sm font-semibold text-slate-100 transition hover:border-slate-500 hover:bg-slate-900"
            >
              Open Capture Lab
            </Link>
            <Link
              to="/dataset-builder"
              className="rounded-full border border-teal-500/40 px-5 py-3 text-sm font-semibold text-teal-200 transition hover:bg-teal-500/10"
            >
              Review Dataset
            </Link>
          </div>
        </div>

        <div className="grid gap-4">
          <div className={kpiCardClass}>
            <div className="flex items-center gap-3 text-slate-800">
              <ShieldCheck className="h-5 w-5 text-emerald-600" />
              <span className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">QC Snapshot</span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div>
                <div className="text-3xl font-semibold text-slate-900">{dashboard?.summary.total_captures ?? 0}</div>
                <div className="text-sm text-slate-500">Capturas trazadas</div>
              </div>
              <div>
                <div className="text-3xl font-semibold text-emerald-700">{dashboard?.summary.valid_captures ?? 0}</div>
                <div className="text-sm text-slate-500">Válidas</div>
              </div>
              <div>
                <div className="text-3xl font-semibold text-amber-600">{dashboard?.summary.doubtful_captures ?? 0}</div>
                <div className="text-sm text-slate-500">Dudosas</div>
              </div>
              <div>
                <div className="text-3xl font-semibold text-rose-700">{dashboard?.summary.rejected_captures ?? 0}</div>
                <div className="text-sm text-slate-500">Rechazadas</div>
              </div>
            </div>
          </div>

          <div className={kpiCardClass}>
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Critical thresholds</div>
            <div className="mt-4 space-y-2 text-sm text-slate-700">
              <div>SNR válido mínimo: {dashboard?.thresholds.min_valid_snr_db ?? 12} dB</div>
              <div>Clipping máximo recomendado: {dashboard?.thresholds.max_valid_clipping_pct ?? 0.5}%</div>
              <div>Offset máximo recomendado: {dashboard?.thresholds.max_valid_frequency_offset_hz ?? 5000} Hz</div>
            </div>
          </div>
        </div>
      </section>

      <section className="mt-6 rounded-[2rem] border border-slate-200 bg-white/85 p-6 shadow-[0_22px_50px_rgba(15,23,42,0.08)]">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Recommended Flow</div>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-700">
              El orden correcto es: encontrar señal, capturar con propósito explícito, revisar calidad, entrenar o reentrenar,
              validar de forma externa e inferir solo sobre muestras nuevas.
            </p>
          </div>
          <div className="rounded-full border border-slate-300 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-600">
            Sigue el orden 01 → 08
          </div>
        </div>
        <div className="mt-6 grid gap-4 xl:grid-cols-2">
          {workflow.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.step}
                to={item.route}
                className="group rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5 transition hover:border-slate-300 hover:bg-white"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="rounded-2xl bg-slate-950 px-3 py-2 text-xs font-semibold tracking-[0.18em] text-white">
                      {item.step}
                    </div>
                    <div className="rounded-2xl bg-white p-3 text-slate-900 shadow-sm">
                      <Icon className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-slate-900">{item.title}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-600">{item.reason}</div>
                    </div>
                  </div>
                  <ArrowRight className="h-5 w-5 text-slate-400 transition group-hover:text-slate-700" />
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mt-6 grid gap-4 xl:grid-cols-3">
        {dashboard?.modes.map((mode) => {
          const icon =
            mode.id === 'live_monitor' ? RadioTower : mode.id === 'guided_capture' ? Microscope : DatabaseZap;
          const Icon = icon;
          const title = mode.id === 'guided_capture' ? 'Capture Lab' : mode.title;
          const goal =
            mode.id === 'guided_capture'
              ? 'Captura IQ real con split explícito train, val o predict para que el resto del pipeline detecte automáticamente su propósito.'
              : mode.goal;
          return (
            <article key={mode.id} className={kpiCardClass}>
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">{title}</div>
                <Icon className="h-5 w-5 text-slate-700" />
              </div>
              <p className="mt-4 text-sm leading-6 text-slate-700">{goal}</p>
            </article>
          );
        })}
      </section>

      <section className="mt-6 rounded-[2rem] border border-slate-200 bg-white/85 p-6 shadow-[0_22px_50px_rgba(15,23,42,0.08)]">
        <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Mandatory metadata</div>
        <div className="mt-4 flex flex-wrap gap-2">
          {(dashboard?.required_metadata ?? []).map((field) => (
            <span
              key={field}
              className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700"
            >
              {field}
            </span>
          ))}
        </div>
      </section>

      <section className="mt-6 grid gap-4 xl:grid-cols-3">
        <article className={kpiCardClass}>
          <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Why Recordings Exists</div>
          <p className="mt-4 text-sm leading-6 text-slate-700">
            Sirve para revisar y descargar IQ o audio del analizador. No sustituye a `Capture Lab` ni al control de calidad del dataset.
          </p>
        </article>
        <article className={kpiCardClass}>
          <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Why Demodulation Exists</div>
          <p className="mt-4 text-sm leading-6 text-slate-700">
            Es una herramienta de inspección de banda y comprensión de señal. Ayuda a interpretar, no a construir dataset por sí sola.
          </p>
        </article>
        <article className={kpiCardClass}>
          <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Why Capture Lab Exists</div>
          <p className="mt-4 text-sm leading-6 text-slate-700">
            Aquí se define el propósito de cada captura. Si marcas `train`, aparecerá en `Training`; si marcas `val`, aparecerá en `Validation`; si marcas `predict`, aparecerá en `Inference`.
          </p>
        </article>
      </section>
    </div>
  );
};
