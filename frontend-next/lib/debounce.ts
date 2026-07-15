export type DebouncedFn = (() => void) & { cancel: () => void };

export function trailingDebounce(fn: () => void, waitMs: number): DebouncedFn {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const debounced = (() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn();
    }, waitMs);
  }) as DebouncedFn;
  debounced.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return debounced;
}
