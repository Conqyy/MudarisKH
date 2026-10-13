"use client";

import { useEffect, useState } from "react";
import { fetchFileObjectUrl, fetchObjectUrl } from "./api";

/** One authenticated file request per source/retry, with ownership and URL cleanup. */
export function useObjectUrl(source: string | null | undefined, storedFile = false, ownerKey = "") {
  const requestKey = `${ownerKey}:${source || ""}`;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ source: "", url: "", loading: false, error: "" });
  useEffect(() => {
    if (!source) { setState({ source: "", url: "", loading: false, error: "" }); return; }
    const controller = new AbortController();
    let created = "";
    setState({ source: requestKey, url: "", loading: true, error: "" });
    const fetchUrl = storedFile ? fetchFileObjectUrl : fetchObjectUrl;
    fetchUrl(source, { signal: controller.signal }).then(url => {
      if (controller.signal.aborted) { URL.revokeObjectURL(url); return; }
      created = url;
      setState({ source: requestKey, url, loading: false, error: "" });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ source: requestKey, url: "", loading: false, error: error?.message || "Could not load file." });
    });
    return () => { controller.abort(); if (created) URL.revokeObjectURL(created); };
  }, [source, storedFile, attempt, requestKey]);
  const current = source && state.source === requestKey ? state : { url: "", loading: !!source, error: "" };
  return { ...current, retry: () => setAttempt(n => n + 1) };
}
