import type { CourseReminder } from "./firestore-helpers";
import { stripUndefinedDeep } from "./firestore-serialization";

export function sameStoredValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length &&
      left.every((value, index) => sameStoredValue(value, right[index]));
  }
  if (left && right && typeof left === "object" && typeof right === "object") {
    const a = left as Record<string, unknown>;
    const b = right as Record<string, unknown>;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((key) =>
      Object.prototype.hasOwnProperty.call(b, key) && sameStoredValue(a[key], b[key]));
  }
  return false;
}

export function courseConflict(): Error {
  return new Error("This course changed on another device. Reload the course and retry your change.");
}

/** Apply only changes relative to the list the user actually edited. Keep
 * unrelated reminders and independent field edits from other devices. */
export function mergeReminderChanges(
  baseline: CourseReminder[], requested: CourseReminder[], current: CourseReminder[]
): CourseReminder[] {
  const before = stripUndefinedDeep(baseline);
  const after = stripUndefinedDeep(requested);
  const live = stripUndefinedDeep(current);
  const beforeById = new Map(before.map((item) => [item.id, item]));
  const afterById = new Map(after.map((item) => [item.id, item]));
  const result = new Map(live.map((item) => [item.id, item]));
  const changedIds = new Set([...Array.from(beforeById.keys()), ...Array.from(afterById.keys())]);
  for (const id of Array.from(changedIds)) {
    const old = beforeById.get(id);
    const desired = afterById.get(id);
    if (sameStoredValue(old, desired)) continue;
    const actual = result.get(id);
    if (!old) {
      if (actual && !sameStoredValue(actual, desired)) throw courseConflict();
      result.set(id, desired!);
    } else if (!desired) {
      if (actual && !sameStoredValue(actual, old)) throw courseConflict();
      result.delete(id);
    } else {
      if (!actual) throw courseConflict();
      const merged = { ...actual } as unknown as Record<string, unknown>;
      const prior = old as unknown as Record<string, unknown>;
      const next = desired as unknown as Record<string, unknown>;
      for (const key of Array.from(new Set([...Object.keys(prior), ...Object.keys(next)]))) {
        if (sameStoredValue(prior[key], next[key])) continue;
        if (!sameStoredValue(merged[key], prior[key]) && !sameStoredValue(merged[key], next[key])) throw courseConflict();
        if (Object.prototype.hasOwnProperty.call(next, key)) merged[key] = next[key];
        else delete merged[key];
      }
      result.set(id, merged as unknown as CourseReminder);
    }
  }
  return Array.from(result.values());
}
