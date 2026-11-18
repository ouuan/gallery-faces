import { onScopeDispose } from "vue";

// Only read requests belong here: cancelling a write cannot undo server changes.
export function useLatestRequest() {
  let controller: AbortController | undefined;
  let disposed = false;
  function cancel() { controller?.abort(); }
  function start() {
    cancel();
    controller = new AbortController();
    if (disposed) controller.abort();
    return controller.signal;
  }
  onScopeDispose(() => { disposed = true; cancel(); });
  return { start, cancel };
}
