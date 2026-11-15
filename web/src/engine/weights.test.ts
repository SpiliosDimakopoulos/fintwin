import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { HEALTH_WEIGHTS } from "./types";

// The health score is computed in both engines; the weights live in one constant on each side.
test("health weights match the Python engine", () => {
  const py = readFileSync(new URL("../../../engine/fintwin/model/constants.py", import.meta.url), "utf8");
  const line = py.match(/^HEALTH_WEIGHTS = (\{.*\})$/m);
  expect(line).not.toBeNull();
  expect(JSON.parse(line![1].replace(/'/g, '"'))).toEqual(HEALTH_WEIGHTS);
});
