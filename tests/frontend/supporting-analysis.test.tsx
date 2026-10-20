import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { selectedSupportingBlocker, supportingPresentation, validatedSupportingRefs, getSupportingReport, retainSelectedRows } from '../../src/lib/supporting-materials';
import SupportingAnalysisReport from '../../src/components/SupportingAnalysisReport';
import SupportingSelectionNotice from '../../src/components/SupportingSelectionNotice';

vi.mock('@/lib/api', () => ({ API_URL: 'http://api.test', apiFetch: vi.fn(), fetchObjectUrl: vi.fn() }));
import { apiFetch } from '@/lib/api';
const hook = vi.hoisted(() => ({ value: { status: null as unknown, report: null as unknown, loading: false, error: null as unknown, retry: vi.fn(), loadMore: vi.fn() } }));
vi.mock('@/hooks/useSupportingAnalysis', () => ({ useSupportingAnalysis: () => hook.value }));
vi.mock('@/lib/auth-context', () => ({ useAuth: () => ({ user: { uid: 'u1' } }) }));
vi.mock('@/lib/i18n', () => ({ useLang: () => ({ t: (value: string) => value }) }));
afterEach(cleanup);

describe('supporting selection and report identity', () => {
  const ready = { id: 'h1', materialId: 'h1', kind: 'historical_exam' as const, status: 'completed', jobId: 'j1', sourceRevision: 's1', reportRevision: 'r1', stale: false, legacy: false };
  it('keeps pending and legacy selected materials visible as blockers, while an empty selection means none', () => {
    expect(selectedSupportingBlocker(new Set(), [ready])).toBeNull();
    expect(selectedSupportingBlocker(new Set(['h1']), [{ ...ready, status: 'queued' }])?.reason).toBe('waiting');
    expect(selectedSupportingBlocker(new Set(['h1']), [{ ...ready, status: 'legacy', legacy: true }])?.reason).toBe('retry');
    expect(selectedSupportingBlocker(new Set(['h1']), [])?.reason).toBe('missing');
    expect(selectedSupportingBlocker(new Set(['h1']), [{ ...ready, status: 'missing' }])?.reason).toBe('missing');
    expect(supportingPresentation({ ...ready, status: 'completed', stale: true })).toBe('retry');
  });
  it('validates the separate four-key supporting reference identity', () => {
    const ref = { kind: 'notes', materialId: 'n1', sourceRevision: 's1', unitId: 'u1' };
    expect(validatedSupportingRefs([ref, ref, { ...ref, kind: 'bad' }, { documentId: 'd1', sourceRevision: 's1', unitId: 'u1' }])).toEqual([ref]);
  });
  it('keeps a selected removed row visible and offers refresh before deselection', () => {
    const rows = retainSelectedRows([], [ready], new Set(['h1']));
    expect(rows[0].status).toBe('missing');
    const onRefresh = vi.fn(), onDeselect = vi.fn();
    render(<SupportingSelectionNotice blocker={selectedSupportingBlocker(new Set(['h1']), rows)} onRefresh={onRefresh} onDeselect={onDeselect} />);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh material status' }));
    expect(onRefresh).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Deselect material' }));
    expect(onDeselect).toHaveBeenCalledWith('h1');
  });
  it('rejects a report page returned for a different revision or offset', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, json: async () => ({ reportRevision: 'old', offset: 50, limit: 50, total: 100, nextOffset: null, items: [], alignments: [], papers: [], topics: [], sharedContexts: [] }) } as Response);
    await expect(getSupportingReport('historical_exam', 'h1', 'r1', 50, 50, undefined, 'c1')).rejects.toThrow(/revision/i);
  });
  it('rejects a truncated page that hides remaining results', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, json: async () => ({ reportRevision: 'r1', offset: 0, limit: 50, total: 51, nextOffset: null, items: [], alignments: [], papers: [], topics: [], sharedContexts: [] }) } as Response);
    await expect(getSupportingReport('tutorial', 't1', 'r1', 0, 50, undefined, 'c1')).rejects.toThrow(/continuation/i);
  });
});

it('shows separate paper groups, partial requirements, distinct not-found/review and honest coverage', () => {
  hook.value.status = { status: 'incomplete', kind: 'historical_exam', materialId: 'h1', reportRevision: 'r1', stale: false, legacy: false, progress: { completedUnits: 9, totalUnits: 10, completedRequirements: 8, totalRequirements: 10 } };
  hook.value.report = { reportRevision: 'r1', nextOffset: null, total: 10,
    extractionCoverage: { unitIds: Array(10).fill(0), unresolvedUnitIds: ['u10'], complete: false },
    alignmentCoverage: { itemIds: Array(10).fill(0), checkedItemIds: Array(10).fill(0), unresolvedItemIds: ['i10'], complete: false },
    papers: Array.from({ length: 10 }, (_, index) => ({ paperId: `p${index}`, printedLabel: `Paper ${index + 1}` })),
    items: Array.from({ length: 10 }, (_, index) => ({ id: `i${index}`, paperId: `p${index}`, parentId: null, printedLabel: `Q${index + 1}`, itemType: 'question', text: `Question ${index + 1}`, printedMarks: null, sharedContextIds: [], requirements: [{ id: `req${index}`, text: `Concept ${index + 1}` }] })),
    alignments: Array.from({ length: 10 }, (_, index) => ({ itemId: `i${index}`, status: index === 0 ? 'partly_covered' : 'needs_review', requirements: [{ requirementId: `req${index}`, relation: index === 0 ? 'not_found' : 'unverified', reason: 'Checked source', lectureAnchorRefs: [], supportingSourceProofs: [] }], unresolvedRequirementIds: [] })), sharedContexts: [], topics: [] };
  render(<SupportingAnalysisReport kind="historical_exam" materialId="h1" courseId="c1" />);
  expect(screen.getAllByText(/Paper \d+/)).toHaveLength(10);
  expect(screen.getByText('Partly covered')).toBeTruthy();
  expect(screen.getByText('Not found in selected lectures')).toBeTruthy();
  expect(screen.getAllByText('Needs review').length).toBeGreaterThan(0);
  expect(screen.getAllByText(/9 \/ 10/).length).toBeGreaterThanOrEqual(2);
  expect(screen.queryByText('0 marks')).toBeNull();
});

it('keeps a stale saved report readable and offers an explicit retry after failure', () => {
  hook.value.status = { status: 'failed', kind: 'tutorial', materialId: 't1', reportRevision: 'old', stale: true, legacy: false, errorMessage: 'Source unavailable', progress: { completedUnits: 2, totalUnits: 3 } };
  hook.value.report = { reportRevision: 'old', nextOffset: null, total: 1, extractionCoverage: { unitIds: ['u1'], unresolvedUnitIds: [], complete: true }, alignmentCoverage: { itemIds: ['i1'], unresolvedItemIds: [], complete: true }, papers: [], items: [{ id: 'i1', paperId: null, parentId: null, printedLabel: 'Saved item', itemType: 'teaching_point', text: 'Saved concept', printedMarks: null, sharedContextIds: [], requirements: [] }], alignments: [], sharedContexts: [], topics: [] };
  render(<SupportingAnalysisReport kind="tutorial" materialId="t1" courseId="c1" />);
  expect(screen.getByText('Saved concept')).toBeTruthy();
  expect(screen.getByText('Report is out of date. Reanalyze this material.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }));
  expect(hook.value.retry).toHaveBeenCalledOnce();
});
