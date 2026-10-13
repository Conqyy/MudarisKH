import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import SourceCitation from '../../src/components/SourceCitation';
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), user: { uid: 'u1' } }));
vi.mock('@/lib/auth-context', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('@/lib/api', () => ({ apiFetch: mocks.fetch }));
vi.mock('@/lib/i18n', () => ({ useLang: () => ({ t: (s: string) => s }) }));
const ref = { documentId: 'd/a', sourceRevision: 'rev&1', unitId: 'p/2', label: 'Page 2' };
beforeEach(() => { vi.resetAllMocks(); mocks.user = { uid: 'u1' }; });
afterEach(cleanup);
it('requests the exact authenticated source version and shows its original unit', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ unit: { ...ref, text: 'Original evidence' }, images: [] }) });
  render(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  await screen.findByText('Original evidence');
  expect(mocks.fetch.mock.calls[0][0]).toContain('/d%2Fa/sources/p%2F2?source_revision=rev%261');
});
it.each([404, 409])('keeps unavailable version %s terminal without current-source fallback', async status => {
  mocks.fetch.mockResolvedValue({ ok: false, status });
  render(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  await screen.findByText('This source version is unavailable.');
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
});
it('ignores labels without trusted identity and late responses after account switch', async () => {
  let resolve!: (v: unknown) => void;
  mocks.fetch.mockReturnValue(new Promise(r => { resolve = r; }));
  const view = render(<SourceCitation sourceRefs={[ref, { label: 'Fake' }]} courseId="c1" />);
  expect(screen.queryByText('Fake')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  mocks.user = { uid: 'u2' };
  view.rerender(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  await act(async () => resolve({ ok: true, json: async () => ({ unit: { ...ref, text: 'Old private evidence' }, images: [] }) }));
  expect(screen.queryByText('Old private evidence')).toBeNull();
});

it('retries transport failure explicitly and displays only authenticated original images', async () => {
  mocks.fetch.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ok: true, json: async () => ({ unit: { ...ref, text: '' }, images: ['data:image/png;base64,YQ==', 'https://untrusted/image.png'] }) });
  render(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry source' }));
  await screen.findByRole('img');
  expect(screen.getAllByRole('img')).toHaveLength(1);
  expect(screen.getByRole('img').getAttribute('src')).toBe('data:image/png;base64,YQ==');
  expect(mocks.fetch).toHaveBeenCalledTimes(2);
});
it('aborts and hides a late old-reference preview on course or reference switch', async () => {
  let resolve!: (value: unknown) => void;
  mocks.fetch.mockReturnValue(new Promise(r => { resolve = r; }));
  const view = render(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  const signal = mocks.fetch.mock.calls[0][1].signal;
  view.rerender(<SourceCitation sourceRefs={[{ ...ref, sourceRevision: 'replacement', label: 'New version' }]} courseId="c2" />);
  expect(signal.aborted).toBe(true);
  await act(async () => resolve({ ok: true, json: async () => ({ unit: { ...ref, text: 'Old course evidence' }, images: [] }) }));
  expect(screen.queryByText('Old course evidence')).toBeNull();
  expect(screen.queryByRole('region')).toBeNull();
});
it('rejects mismatched server identity without displaying its evidence', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ unit: { ...ref, sourceRevision: 'different', text: 'Wrong version evidence' } }) });
  render(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('Wrong version evidence')).toBeNull();
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
});

it('shows faithful visual reading and source warnings alongside exact source images', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ unit: { ...ref, text: '', visualText: 'Diagram describes a binary tree.', warnings: ['Small labels are unclear.'] }, images: ['data:image/png;base64,YQ=='] }) });
  render(<SourceCitation sourceRefs={[ref]} courseId="c1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
  await screen.findByText('Diagram describes a binary tree.');
  expect(screen.getByText('Small labels are unclear.')).toBeTruthy();
});
