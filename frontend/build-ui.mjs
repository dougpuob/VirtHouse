import * as esbuild from "esbuild";

await esbuild.build({
  entryPoints: ["src/main.jsx"],
  bundle: true,
  outfile: "assets/app.js",
  format: "iife",
  platform: "browser",
  jsx: "automatic",
  target: ["es2020"],
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
});
