import { loader } from "@monaco-editor/react";

/**
 * Point the Monaco loader at the copy minilake serves.
 *
 * @monaco-editor/react loads Monaco from jsDelivr by default. The image is
 * deliberately offline-capable, so the editor is copied into public/monaco by
 * `scripts/copy-monaco.mjs` and loaded from this origin. The `/ui` prefix is the
 * app's basePath, which is not applied to runtime-constructed URLs.
 */
let configured = false;

export function configureMonacoLoader(): void {
  if (configured || typeof window === "undefined") return;
  configured = true;
  loader.config({ paths: { vs: "/ui/monaco/vs" } });
}
