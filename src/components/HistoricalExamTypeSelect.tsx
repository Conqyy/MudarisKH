"use client";
import { useLang } from "@/lib/i18n";
import { EXAM_TYPE_LABELS, HISTORICAL_EXAM_TYPES, HistoricalExamType } from "@/lib/historical-exam-types";

export default function HistoricalExamTypeSelect({ value, onChange, label = "Past exam type", disabled = false, required = false }: { value: HistoricalExamType | ""; onChange: (type: HistoricalExamType) => void; label?: string; disabled?: boolean; required?: boolean }) {
  const { t } = useLang();
  return <label className="block text-sm font-medium text-ink-soft mb-5">
    {t(label)}
    <select aria-label={t(label)} value={value} required={required} disabled={disabled} onChange={event => onChange(event.target.value as HistoricalExamType)} className="block w-full mt-2 px-4 py-3 rounded-xl border border-line bg-paper text-ink focus:outline-none focus:border-accent">
      <option value="" disabled>{t("Choose an exam type")}</option>
      {HISTORICAL_EXAM_TYPES.map(type => <option key={type} value={type}>{t(EXAM_TYPE_LABELS[type])}</option>)}
    </select>
  </label>;
}
