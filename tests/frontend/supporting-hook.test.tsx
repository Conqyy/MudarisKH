import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useSupportingAnalysis } from '../../src/hooks/useSupportingAnalysis';

const mocks = vi.hoisted(() => ({ user: { uid: 'u1' }, status: vi.fn(), report: vi.fn(), prepare: vi.fn() }));
vi.mock('@/lib/auth-context', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('@/lib/supporting-materials', () => ({ getSupportingStatus: mocks.status, getSupportingReport: mocks.report, prepareSupportingMaterial: mocks.prepare }));
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });
const state = (materialId: string, status = 'queued', jobId = 'job1') => ({ materialId, kind: 'tutorial', status, stage: status, jobId, sourceRevision: null, reportRevision: null, scopeRevision: null, coverage: null, legacy: false, stale: false, errorMessage: null, progress: { completedUnits: 0, totalUnits: null, completedRequirements: 0, totalRequirements: null } });

it('discards a late result when material changes while a status request is pending', async () => {
  let resolveOld!: (value: unknown) => void;
  mocks.status.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; })).mockResolvedValueOnce(state('new', 'completed'));
  const view = renderHook(({ materialId }) => useSupportingAnalysis({ kind: 'tutorial', materialId, courseId: 'c1' }), { initialProps: { materialId: 'old' } });
  view.rerender({ materialId: 'new' });
  await act(async () => resolveOld(state('old', 'completed')));
  await waitFor(() => expect(view.result.current.status?.materialId).toBe('new'));
  expect(view.result.current.report).toBeNull();
});

it('polls a queued job and stops when it reaches a terminal status', async () => {
  vi.useFakeTimers();
  mocks.status.mockResolvedValueOnce(state('t1')).mockResolvedValueOnce(state('t1', 'completed'));
  const view = renderHook(() => useSupportingAnalysis({ kind: 'tutorial', materialId: 't1', courseId: 'c1' }));
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(view.result.current.status?.status).toBe('completed');
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(mocks.status).toHaveBeenCalledTimes(2);
});
