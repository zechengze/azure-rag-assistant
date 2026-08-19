import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

// eslint 10 已完全移除 eslintrc 支援,此檔取代原本的 .eslintrc.cjs。
// 遷移前用 `--ext ts,tsx` 限定檢查範圍,flat config 沒有該旗標,
// 因此改以 ignores + files 明確界定,維持「只檢查 src 下的 ts/tsx」。
export default tseslint.config(
  {
    ignores: [
      "dist",
      "coverage",
      ".vite", // Vite 相依預打包快取,產生物非原始碼
      "*.config.js", // tailwind / postcss / eslint 設定,遷移前因 --ext 未被檢查
      "vite.config.ts", // 對應遷移前 ignorePatterns 中的同一項
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      // react-hooks v7 的完整 recommended (17 條,React Compiler 規則集)。
      // 遷移到 eslint 10 時暫時只保留 v4 的兩條,此處補上其餘 15 條。
      ...reactHooks.configs["recommended-latest"].rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
