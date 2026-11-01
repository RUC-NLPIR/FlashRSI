// Development-only loader. Production Pi executes the Python Snapshot.
import { createRequire, isBuiltin } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";
const dependencies = process.env.PI_REFERENCE_DEPS;
const require = createRequire(path.join(dependencies, "@earendil-works/pi-coding-agent/package.json"));
export async function resolve(specifier, context, next) {
  // The Git checkout omits generated provider metadata. Provider oracles still
  // execute the original API source, using the matching hydrated release model
  // registry for this dependency only (no request/estimator logic is replaced).
  if (specifier.endsWith("/models.ts") && context.parentURL?.includes("/packages/ai/src/")) {
    return { url: pathToFileURL(path.join(dependencies, "@earendil-works/pi-ai/dist/models.js")).href, shortCircuit: true };
  }
  if (specifier === "@earendil-works/pi-ai" || specifier === "@earendil-works/pi-ai/compat") {
    const entry = specifier.endsWith("/compat") ? "compat.js" : "index.js";
    return { url: pathToFileURL(path.join(dependencies, "@earendil-works/pi-ai/dist", entry)).href, shortCircuit: true };
  }
  if (!specifier.startsWith(".") && !specifier.startsWith("/") && !specifier.startsWith("file:") && !isBuiltin(specifier)) {
    try { return { url: pathToFileURL(require.resolve(specifier)).href, shortCircuit: true }; } catch {}
  }
  return next(specifier, context);
}
