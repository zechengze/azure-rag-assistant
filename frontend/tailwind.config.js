import plugin from "tailwindcss/plugin";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [
    plugin(({ addVariant }) => {
      // 以「指標是否支援 hover」判斷,而非螢幕寬度 —— iPad 這類寬螢幕觸控裝置
      // 在 md: 之上仍然沒有 hover,用斷點會讓 hover 才出現的操作在上面消失。
      addVariant("can-hover", "@media (hover: hover) and (pointer: fine)");
    }),
  ],
};
