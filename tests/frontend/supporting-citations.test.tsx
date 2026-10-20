import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import SupportingCitation from '../../src/components/SupportingCitation';

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), original: vi.fn(), user: { uid: 'u1' } }));
vi.mock('@/lib/auth-context', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('@/lib/api', () => ({ API_URL: 'http://api.test', apiFetch: mocks.fetch, fetchObjectUrl: mocks.original }));
vi.mock('@/lib/i18n', () => ({ useLang: () => ({ t: (value: string) => value }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.resetAllMocks(); });
const ref = { kind: 'notes', materialId: 'n1', sourceRevision: 'rev1', unitId: 'u1' };

it('opens an authenticated exact supporting unit and labels typed notes as student content', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ref, unit: { unitId: 'u1', text: 'My notes', visualText: '', timing: null, position: 1, kind: 'notes', visualAssets: [] } }) });
  render(<SupportingCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'u1' }));
  await screen.findByText('My notes');
  expect(screen.getByText('This passage is from your typed notes.')).toBeTruthy();
  expect(screen.queryByText('Professor quote')).toBeNull();
  expect(mocks.fetch.mock.calls[0][0]).toContain('/api/supporting/notes/n1/source?revision=rev1&unit_id=u1&course_id=c1');
});

it('rejects a foreign echoed ref without showing its text', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ref: { ...ref, materialId: 'other' }, unit: { unitId: 'u1', text: 'Foreign evidence' } }) });
  render(<SupportingCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'u1' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('Foreign evidence')).toBeNull();
});

it('hides a late source preview after a course and reference switch', async () => {
  let resolveOld!: (value: unknown) => void;
  mocks.fetch.mockReturnValue(new Promise(resolve => { resolveOld = resolve; }));
  const view = render(<SupportingCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'u1' }));
  const signal = mocks.fetch.mock.calls[0][1].signal;
  view.rerender(<SupportingCitation sourceRefs={[{ ...ref, sourceRevision: 'new' }]} courseId="c2" />);
  expect(signal.aborted).toBe(true);
  await act(async () => resolveOld({ ok: true, json: async () => ({ ref, unit: { unitId: 'u1', text: 'Old private text' } }) }));
  expect(screen.queryByText('Old private text')).toBeNull();
});

it('treats a missing exact source as unavailable without fallback', async () => {
  mocks.fetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'missing' }) });
  render(<SupportingCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'u1' }));
  await screen.findByText('This source version is unavailable.');
  expect(screen.queryByRole('button', { name: 'Retry source' })).toBeNull();
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
});

it('uses only the server verified original page number for a PDF fragment', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ref, originalPage: 7, unit: { unitId: 'u1', position: 99, kind: 'page', text: '', visualText: '', visualAssets: [{ assetId: 'p1', kind: 'page' }], timing: null } }) });
  mocks.original.mockResolvedValue('blob:verified');
  vi.stubGlobal('URL', { ...URL, revokeObjectURL: vi.fn() });
  render(<SupportingCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'u1' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open original' }));
  expect((await screen.findByRole('link', { name: 'Open original' })).getAttribute('href')).toBe('blob:verified#page=7');
});

it('cancels an original read when the authenticated citation identity changes', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ref, unit: { unitId: 'u1', position: 1, kind: 'notes', text: 'My notes', visualText: '', visualAssets: [], timing: null } }) });
  let resolveOriginal!: (value: string) => void;
  mocks.original.mockReturnValue(new Promise(resolve => { resolveOriginal = resolve; }));
  const view = render(<SupportingCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'u1' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open original' }));
  const signal = mocks.original.mock.calls[0][1]?.signal as AbortSignal | undefined;
  view.rerender(<SupportingCitation sourceRefs={[ref]} courseId="c2" />);
  expect(signal?.aborted).toBe(true);
  await act(async () => resolveOriginal('blob:old'));
  expect(screen.queryByRole('link', { name: 'Open original' })).toBeNull();
});
