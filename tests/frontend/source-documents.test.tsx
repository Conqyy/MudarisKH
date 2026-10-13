import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import MultiUploadModal from '../../src/components/MultiUploadModal';
import UploadDocumentModal from '../../src/components/UploadDocumentModal';
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), json: vi.fn(), user: { uid: 'u1' } }));
vi.mock('@/lib/auth-context', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('@/lib/api', () => ({ apiFetch: mocks.fetch, apiJson: mocks.json }));
vi.mock('@/lib/i18n', () => ({ useLang: () => ({ t: (s: string) => s }) }));
beforeEach(() => { vi.resetAllMocks(); mocks.user = { uid: 'u1' }; });
afterEach(() => { cleanup(); vi.useRealTimers(); });
async function upload() {
  const view = render(<UploadDocumentModal courseId="c1" onClose={vi.fn()} onSuccess={vi.fn()} />);
  fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'notes.pdf', { type: 'application/pdf' })] } });
  fireEvent.click(screen.getByRole('button', { name: /Upload & Analyze/ }));
  return view;
}
it('waits for both actual stages after accepted upload, with no skip option', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, status: 202, json: async () => ({ status: 'accepted', document_id: 'd1' }) });
  mocks.json.mockResolvedValue({ document: { id: 'd1', courseId: 'c1', preparationStatus: 'completed', guideStatus: 'processing' } });
  await upload();
  await waitFor(() => expect(mocks.json).toHaveBeenCalled());
  expect(screen.getByText('Preparing document')).toBeTruthy();
  expect(screen.getByText('Creating lightweight analysis')).toBeTruthy();
  expect(screen.queryByRole('checkbox', { name: /skip.*analysis/i })).toBeNull();
  expect(screen.queryByText('All files analyzed!')).toBeNull();
  expect((screen.getByRole('button', { name: 'Close dialog' }) as HTMLButtonElement).disabled).toBe(true);
});
it('aborts accepted polling on account switch', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, status: 202, json: async () => ({ document_id: 'd1' }) });
  mocks.json.mockImplementation(() => new Promise(() => {}));
  const view = await upload();
  await waitFor(() => expect(mocks.json).toHaveBeenCalled());
  const signal = mocks.json.mock.calls[0][1].signal;
  mocks.user = { uid: 'u2' };
  view.rerender(<UploadDocumentModal courseId="c1" onClose={vi.fn()} onSuccess={vi.fn()} />);
  expect(signal.aborted).toBe(true);
});

it('continues a batch after a preparation failure without counting the accepted failure as done', async () => {
  mocks.fetch.mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ document_id: 'bad' }) }).mockResolvedValueOnce({ ok: true, status: 202, json: async () => ({ document_id: 'good' }) });
  mocks.json.mockImplementation(async (url: string) => ({ document: url.endsWith('/bad') ? { id: 'bad', courseId: 'c1', preparationStatus: 'failed', guideStatus: 'pending', preparationError: 'Unsupported visuals: replace with a clearer PDF.' } : { id: 'good', courseId: 'c1', preparationStatus: 'completed', guideStatus: 'completed' } }));
  const success = vi.fn();
  const view = render(<UploadDocumentModal courseId="c1" onClose={vi.fn()} onSuccess={success} />);
  fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'bad.pdf'), new File(['b'], 'good.pdf')] } });
  fireEvent.click(screen.getByRole('button', { name: /Upload & Analyze/ }));
  await screen.findByText('Finished with some issues');
  expect(screen.getByText('Unsupported visuals: replace with a clearer PDF.')).toBeTruthy();
  expect(screen.getByText('2/2')).toBeTruthy();
  expect(screen.getAllByText(/● Done/)).toHaveLength(1);
  expect(success).not.toHaveBeenCalled();
  expect(mocks.fetch).toHaveBeenCalledTimes(2);
});
it('requires preparation even when a guide incorrectly appears completed', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, status: 202, json: async () => ({ document_id: 'd1' }) });
  mocks.json.mockResolvedValue({ document: { id: 'd1', preparationStatus: 'processing', guideStatus: 'completed' } });
  await upload();
  await waitFor(() => expect(mocks.json).toHaveBeenCalled());
  expect(screen.queryByText('All files analyzed!')).toBeNull();
});
it('does not publish a late completion after switching courses', async () => {
  let resolve!: (value: unknown) => void;
  mocks.fetch.mockResolvedValue({ ok: true, status: 202, json: async () => ({ document_id: 'd1' }) });
  mocks.json.mockReturnValue(new Promise(r => { resolve = r; }));
  const view = await upload();
  await waitFor(() => expect(mocks.json).toHaveBeenCalled());
  const success = vi.fn();
  view.rerender(<UploadDocumentModal courseId="c2" onClose={vi.fn()} onSuccess={success} />);
  await act(async () => resolve({ document: { id: 'd1', courseId: 'c1', preparationStatus: 'completed', guideStatus: 'completed' } }));
  expect(screen.queryByText('All files analyzed!')).toBeNull();
  expect(success).not.toHaveBeenCalled();
});

it('leaves supporting uploads on their existing response completion path and size cap', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, status: 200, json: vi.fn() });
  const view = render(<MultiUploadModal courseId="c1" onClose={vi.fn()} onSuccess={vi.fn()} endpoint="/api/tutorials/upload" accent="#c8472f" icon="📄" acceptExts={['pdf']} acceptAttr=".pdf" heading="Supporting upload" subtitle="Supporting material" fileNoun="tutorial" steps={[{ id: 'upload', label: 'Uploading tutorial', duration: 1 }]} />);
  expect(screen.getByText(/50MB/)).toBeTruthy();
  fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'tutorial.pdf')] } });
  fireEvent.click(screen.getByRole('button', { name: /Upload & Analyze/ }));
  await screen.findByText('All files analyzed!');
  expect(mocks.json).not.toHaveBeenCalled();
});
