"use client";
import { useLang } from "@/lib/i18n";
import { EXAM_TYPE_LABELS, HISTORICAL_EXAM_TYPES, HistoricalExamType } from "@/lib/historical-exam-types";

export default function HistoricalExamTypeSelect({ value, onChange, label = "Past exam type", disabled = false, required = false }: { value: HistoricalExamType | ""; onChange: (type: HistoricalExamType) => void; label?: string; disabled?: boolean; required?: boolean }) {
  const { t } = useLang();
  return <label className="block text-sm font-medium text-ink-soft mb-5">
    {t(label)}
    <select aria-label={t(label)} value={value} required={required} disabled={disabled} onChange={event => onChange(event.target.value as HistoricalExamType)} className="ui-input block w-full mt-2">
      <option value="" disabled>{t("Choose an exam type")}</option>
      {HISTORICAL_EXAM_TYPES.map(type => <option key={type} value={type}>{t(EXAM_TYPE_LABELS[type])}</option>)}
    </select>
  </label>;
}
