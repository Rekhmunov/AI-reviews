/**
 * Pure helpers for Ozon FBS cargo-place (ГМ) QR matching.
 * Shared by web bind UI and Ozon FBS TSD — no DOM, no fetch.
 */
(function (root) {
  "use strict";

  function normalizeContainerScan(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    const digits = raw.replace(/\D+/g, "");
    return digits || raw;
  }

  /**
   * True when postings can still be scanned/bound into this cargo place.
   * Prefers API `can_fill` when present; otherwise mirrors status heuristics.
   */
  function containerAcceptsFill(c) {
    if (!c || typeof c !== "object") return false;
    if (c.can_fill === false) return false;
    if (c.can_fill === true) return true;
    const st = String(c.status || "").trim().toLowerCase();
    if (
      [
        "approved",
        "formed",
        "ready",
        "shipped",
        "closed",
        "cancelled",
        "canceled",
        "deleted",
      ].includes(st)
    ) {
      return false;
    }
    return true;
  }

  /**
   * Match scanned QR to a known container.
   * Order: container_id, container_barcode/barcode, then long container_number.
   */
  function matchContainerByScan(containers, scan) {
    const key = normalizeContainerScan(scan);
    if (!key) return null;
    const list = Array.isArray(containers) ? containers : [];
    for (const row of list) {
      if (!row || typeof row !== "object") continue;
      const cid = String(row.container_id || "").trim();
      if (cid && cid === key) return row;
    }
    for (const row of list) {
      if (!row || typeof row !== "object") continue;
      const barcode = normalizeContainerScan(
        row.container_barcode || row.barcode || ""
      );
      if (barcode && barcode === key) return row;
    }
    for (const row of list) {
      if (!row || typeof row !== "object") continue;
      const number = String(row.container_number || "").trim();
      if (number && number === key && key.length >= 6) return row;
    }
    return null;
  }

  const api = {
    normalizeContainerScan,
    containerAcceptsFill,
    matchContainerByScan,
  };

  root.OzonFbsContainerMatch = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
