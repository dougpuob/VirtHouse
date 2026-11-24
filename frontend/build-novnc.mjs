import * as esbuild from "esbuild";
import fs from "node:fs";

const browserPath = "node_modules/@novnc/novnc/lib/util/browser.js";
const browser = fs.readFileSync(browserPath, "utf8").replace(
  "exports.supportsWebCodecsH264Decode = supportsWebCodecsH264Decode = await _checkWebCodecsH264DecodeSupport();",
  "_checkWebCodecsH264DecodeSupport().then((supported) => { exports.supportsWebCodecsH264Decode = supportsWebCodecsH264Decode = supported; });",
);

await esbuild.build({
  entryPoints: ["node_modules/@novnc/novnc/lib/rfb.js"],
  bundle: true,
  format: "esm",
  outfile: "novnc.js",
  plugins: [
    {
      name: "keep-browser-as-script",
      setup(build) {
        build.onLoad({ filter: /\/util\/browser\.js$/ }, () => ({
          contents: browser,
          loader: "js",
        }));
      },
    },
  ],
});
