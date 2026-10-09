/** Firestore rejects undefined at any depth. Preserve SDK values (timestamps,
 * references and field transforms) and clean only plain objects and arrays. */
export function stripUndefinedDeep<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.filter((entry) => entry !== undefined).map(stripUndefinedDeep) as T;
  }
  if (value && typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype === Object.prototype || prototype === null) {
      return Object.fromEntries(
        Object.entries(value).filter(([, entry]) => entry !== undefined)
          .map(([key, entry]) => [key, stripUndefinedDeep(entry)])
      ) as T;
    }
  }
  return value;
}
