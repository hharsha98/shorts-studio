import { useEffect, useState } from "react";
import { cancelRender, continueRender, delayRender, staticFile } from "remotion";
import { FONT } from "./theme";

const FILES: [number, string][] = [
  [400, "Regular"],
  [500, "Medium"],
  [600, "SemiBold"],
  [700, "Bold"],
  [800, "ExtraBold"],
];

let loading: Promise<void> | null = null;

const loadFonts = (): Promise<void> => {
  if (!loading) {
    loading = Promise.all(
      FILES.map(([weight, name]) => {
        const face = new FontFace(FONT, `url(${staticFile(`fonts/BeVietnamPro-${name}.ttf`)}) format("truetype")`, {
          weight: String(weight),
          style: "normal",
        });
        return face.load().then((loaded) => {
          (document.fonts as unknown as { add: (f: FontFace) => void }).add(loaded);
        });
      }),
    ).then(() => undefined);
  }
  return loading;
};

/** True once every weight is loaded; holds the frame capture until then (text is measured with the real font). */
export const useFontsReady = (): boolean => {
  const [handle] = useState(() => delayRender("Loading Be Vietnam Pro"));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadFonts()
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch((err: unknown) => cancelRender(err));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (ready) continueRender(handle);
  }, [ready, handle]);

  return ready;
};
