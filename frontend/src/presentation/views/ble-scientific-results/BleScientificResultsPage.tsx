import { useState } from 'react';
import AcquisitionQualityTab from './AcquisitionQualityTab';
import AssociationTab from './AssociationTab';
import CampaignTab from './CampaignTab';
import ChannelTransportTab from './ChannelTransportTab';
import CoverageTab from './CoverageTab';
import EvidenceDashboardTab from './EvidenceDashboardTab';
import EvidenceQualityTab from './EvidenceQualityTab';
import ExperimentHealthTab from './ExperimentHealthTab';
import GuidedValidationTab from './GuidedValidationTab';
import IntegrityLeakageTab from './IntegrityLeakageTab';
import OnlineEquivalenceTab from './OnlineEquivalenceTab';
import PaperExportTab from './PaperExportTab';
import PaperReadinessTab from './PaperReadinessTab';
import ProtocolTab from './ProtocolTab';
import ProvenanceTab from './ProvenanceTab';
import QualificationTab from './QualificationTab';
import ReadinessTab from './ReadinessTab';
import Rq1Tab from './Rq1Tab';
import Rq2Tab from './Rq2Tab';
import Rq3Tab from './Rq3Tab';
import Rq4Tab from './Rq4Tab';
import ScientificCompletenessTab from './ScientificCompletenessTab';
import SensitivityTab from './SensitivityTab';
import StudyControlCenterTab from './StudyControlCenterTab';
import StudyOverviewTab from './StudyOverviewTab';
import SupportingTablesTab from './SupportingTablesTab';

// Paper progress dashboard (2026-08-10): every tab below is real and reads
// only canonical backend artifacts -- none computes science, none mutates
// the protocol contract, and none can open FUTURE_TEST (the only mutating
// call anywhere in this set is PaperExportTab's "Generar exports" button,
// which only writes report files). `forensics`/`reproducibility` stay
// disabled -- no canonical artifact/endpoint is designed for them yet.
//
// 4-level architecture (2026-08-11): the dashboard is NOT a flat tab list --
// A. EXPERIMENT HEALTH (is the study machinery in a sane state?),
// B. DATA/EVIDENCE QUALITY (what does the evidence itself look like?),
// C. SCIENTIFIC RESULTS (RQ1-4/coverage/statistical inspection/sensitivity/
//    S1/S2 -- the actual paper findings), D. PAPER READINESS (what's left
//    before each paper element can be written). Every tab component below
//    is unchanged -- this is a navigation regrouping, not a rewrite.
interface DashboardTab { id: string; label: string; enabled: boolean }
interface DashboardSection { id: string; label: string; hint: string; tabs: DashboardTab[] }

const SECTIONS: DashboardSection[] = [
  {
    id: 'health', label: 'A. Experiment Health',
    hint: 'Estado de la maquinaria experimental: cronologia del estudio, calificacion de hardware, estado del receptor, calidad de captura, completitud de campana, estado de asociacion, admision/exclusion, estado del protocolo, estado del holdout.',
    tabs: [
      { id: 'experiment-health', label: 'Experiment Health', enabled: true },
      { id: 'control-center', label: 'Study Control Center', enabled: true },
      { id: 'overview', label: 'Study Overview', enabled: true },
      { id: 'guided-validation', label: 'Guided Validation', enabled: true },
      { id: 'protocol', label: 'Protocol', enabled: true },
      { id: 'readiness', label: 'Readiness', enabled: true },
      { id: 'hw-qualification', label: 'Hardware & Qualification', enabled: true },
      { id: 'association', label: 'Association', enabled: true },
      { id: 'campaign', label: 'Campaign', enabled: true },
    ],
  },
  {
    id: 'data-quality', label: 'B. Data / Evidence Quality',
    hint: 'Tablas y visualizaciones de la evidencia misma: capturas por unidad fisica/dia/rol, bursts candidatos, CRC valido, admitidos, discontinuidades, exclusiones y razones, ventanas elegibles, abstencion por evidencia insuficiente.',
    tabs: [
      { id: 'evidence-quality', label: 'Evidence Quality', enabled: true },
      { id: 'integrity', label: 'Integrity and Leakage', enabled: true },
      { id: 'quality', label: 'Acquisition Quality', enabled: true },
    ],
  },
  {
    id: 'results', label: 'C. Scientific Results',
    hint: 'RQ1-4, coverage/risk-coverage, inspeccion estadistica comun, sensibilidad (nunca mezclada con el resultado confirmatorio principal), S1 (bounded channel transport) y S2 (online/offline equivalence).',
    tabs: [
      { id: 'evidence-dashboard', label: 'Evidence Dashboard', enabled: true },
      { id: 'rq1', label: 'RQ1', enabled: true },
      { id: 'rq2', label: 'RQ2', enabled: true },
      { id: 'rq3', label: 'RQ3', enabled: true },
      { id: 'rq4', label: 'RQ4', enabled: true },
      { id: 'coverage', label: 'Coverage / Abstention', enabled: true },
      { id: 's1', label: 'Channel Transport (S1)', enabled: true },
      { id: 's2', label: 'Online Equivalence (S2)', enabled: true },
      { id: 'sensitivity', label: 'Sensitivity', enabled: true },
      { id: 'supporting-tables', label: 'Supporting Tables', enabled: true },
    ],
  },
  {
    id: 'paper-readiness', label: 'D. Paper Readiness',
    hint: 'Por elemento del paper: mecanismo, madurez de datos, artefacto canonico, estadisticas, tabla, figura, evidencia -- mas la cadena de provenance y el export canonico (CSV/LaTeX/PDF vectorial).',
    tabs: [
      { id: 'provenance', label: 'Provenance', enabled: true },
      { id: 'paper-readiness', label: 'Paper Readiness', enabled: true },
      { id: 'scientific-completeness', label: 'Scientific Completeness', enabled: true },
      { id: 'export', label: 'Paper Export', enabled: true },
      { id: 'forensics', label: 'Calibration and Forensics', enabled: false },
      { id: 'reproducibility', label: 'Reproducibility', enabled: false },
    ],
  },
];

export default function BleScientificResultsPage() {
  const [activeSection, setActiveSection] = useState('health');
  const [activeTab, setActiveTab] = useState('control-center');
  const [showFutureAnalysisInfo, setShowFutureAnalysisInfo] = useState(false);

  const section = SECTIONS.find((s) => s.id === activeSection) ?? SECTIONS[0];
  // Rutas y componentes de las pestañas "Fase 3+" NO se eliminan -- solo se
  // agrupan visualmente detrás de una unica entrada mientras la
  // identificacion fisica no este disponible (ver GuidedValidationTab).
  const visibleTabs = section.tabs.filter((tab) => tab.enabled);
  const futureTabs = section.tabs.filter((tab) => !tab.enabled);

  const selectSection = (sectionId: string) => {
    setActiveSection(sectionId);
    const firstEnabled = SECTIONS.find((s) => s.id === sectionId)?.tabs.find((t) => t.enabled);
    if (firstEnabled) setActiveTab(firstEnabled.id);
  };

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/95 px-4 py-2 backdrop-blur">
        <div className="mb-2">
          <div className="text-base font-bold text-slate-100">BLE Scientific Results Studio</div>
          <div className="text-xs text-slate-500">
            Capa autoritativa para los resultados empiricos del paper BLE -- contratos de analisis congelados,
            preflight cientifico, registros canonicos y contabilidad de campana. Fase 2 de 6. Nunca modifica los
            manifests o artefactos de BLE-RFFI Studio.
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 pb-2">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`rounded px-3 py-1.5 text-xs font-semibold transition-colors ${
                activeSection === s.id ? 'bg-cyan-600/30 text-cyan-100' : 'text-slate-400 hover:bg-slate-800'
              }`}
              onClick={() => selectSection(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="mt-1 text-[11px] text-slate-500">{section.hint}</div>

        <div className="mt-2 flex flex-wrap items-center gap-1">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                activeTab === tab.id ? 'bg-slate-700/60 text-slate-100' : 'text-slate-400 hover:bg-slate-800'
              }`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
          {futureTabs.length > 0 && (
            <button
              className="rounded px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-800 hover:text-slate-400"
              onClick={() => setShowFutureAnalysisInfo((v) => !v)}
            >
              Análisis científicos posteriores
            </button>
          )}
        </div>
        {showFutureAnalysisInfo && futureTabs.length > 0 && (
          <div className="mt-2 rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-slate-400">
            Estas funciones ({futureTabs.map((tab) => tab.label).join(', ')}) se habilitarán cuando la asociación
            física haya sido comprobada.
          </div>
        )}
      </div>

      {activeTab === 'experiment-health' && <ExperimentHealthTab />}
      {activeTab === 'evidence-quality' && <EvidenceQualityTab />}
      {activeTab === 'control-center' && <StudyControlCenterTab />}
      {activeTab === 'overview' && <StudyOverviewTab />}
      {activeTab === 'guided-validation' && <GuidedValidationTab />}
      {activeTab === 'protocol' && <ProtocolTab />}
      {activeTab === 'readiness' && <ReadinessTab />}
      {activeTab === 'hw-qualification' && <QualificationTab />}
      {activeTab === 'association' && <AssociationTab />}
      {activeTab === 'campaign' && <CampaignTab />}
      {activeTab === 'integrity' && <IntegrityLeakageTab />}
      {activeTab === 'quality' && <AcquisitionQualityTab />}
      {activeTab === 'evidence-dashboard' && <EvidenceDashboardTab />}
      {activeTab === 'rq1' && <Rq1Tab />}
      {activeTab === 'rq2' && <Rq2Tab />}
      {activeTab === 'rq3' && <Rq3Tab />}
      {activeTab === 'rq4' && <Rq4Tab />}
      {activeTab === 'coverage' && <CoverageTab />}
      {activeTab === 's1' && <ChannelTransportTab />}
      {activeTab === 's2' && <OnlineEquivalenceTab />}
      {activeTab === 'sensitivity' && <SensitivityTab />}
      {activeTab === 'supporting-tables' && <SupportingTablesTab />}
      {activeTab === 'provenance' && <ProvenanceTab />}
      {activeTab === 'paper-readiness' && <PaperReadinessTab />}
      {activeTab === 'scientific-completeness' && <ScientificCompletenessTab />}
      {activeTab === 'export' && <PaperExportTab />}
    </div>
  );
}
