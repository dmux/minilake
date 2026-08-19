import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Monaco's prebuilt AMD bundle, copied in by scripts/copy-monaco.mjs. Third-party
    // minified output — linting it produces thousands of warnings about code we do
    // not own and cannot change.
    "public/monaco/**",
  ]),
]);

export default eslintConfig;
