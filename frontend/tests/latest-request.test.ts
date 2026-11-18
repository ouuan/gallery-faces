import { effectScope } from "vue";
import { expect, it } from "vitest";
import { useLatestRequest } from "../src/use-latest-request";

it("cancels replaced reads, explicit dismissals, and reads on scope disposal", () => {
  const scope = effectScope();
  const request = scope.run(useLatestRequest)!;
  const first = request.start();
  const second = request.start();
  expect(first.aborted).toBe(true);
  expect(second.aborted).toBe(false);
  request.cancel();
  expect(second.aborted).toBe(true);
  const third = request.start();
  scope.stop();
  expect(third.aborted).toBe(true);
  expect(request.start().aborted).toBe(true);
});
