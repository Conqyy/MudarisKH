// Helpers for applying the user's custom ordering + renamed titles that are
// stored on the course document. Used everywhere course materials are listed
// (course page, tutor, exam, flashcards, summary) so the order/names stay
// consistent across the whole app.

// Sort items to match an array of ids. Items not present in `order`
// (e.g. newly uploaded) keep their original relative position at the end.
function sortByIdOrder<T extends { id: string }>(
  items: T[],
  order?: string[]
): T[] {
  if (!order || order.length === 0) return items;
  const pos = new Map(order.map((id, i) => [id, i]));
  return [...items].sort((a, b) => {
    const ap = pos.has(a.id) ? pos.get(a.id)! : Number.MAX_SAFE_INTEGER;
    const bp = pos.has(b.id) ? pos.get(b.id)! : Number.MAX_SAFE_INTEGER;
    return ap - bp;
  });
}

// Replace each item's title with the user's custom name when one exists.
function applyTitleOverrides<T extends { id: string; title: string }>(
  items: T[],
  overrides?: Record<string, string>
): T[] {
  if (!overrides || Object.keys(overrides).length === 0) return items;
  return items.map((it) =>
    overrides[it.id] ? { ...it, title: overrides[it.id] } : it
  );
}

// Apply both renamed titles and custom ordering in one call.
export function ordered<T extends { id: string; title: string }>(
  items: T[],
  order?: string[],
  overrides?: Record<string, string>
): T[] {
  return sortByIdOrder(applyTitleOverrides(items, overrides), order);
}
