import { describe, expect, it } from "vitest";
import { chipTone, isElevationError, mergeStatus } from "./api";
import type { BridgeStatus } from "../types";

describe("chipTone", () => {
  it("marks hoppie ok as success", () => {
    expect(chipTone("Hoppie ok · DLH4MC")).toContain("success");
    expect(chipTone("SI ok · DLH4MC")).toContain("success");
    expect(chipTone("GFO ok · BAW12G")).toContain("success");
  });

  it("marks errors as danger", () => {
    expect(chipTone("LINK issue · 12:00Z")).toContain("danger");
    expect(chipTone("Hoppie rejected logon")).toContain("danger");
  });

  it("marks idle as muted", () => {
    expect(chipTone("LINK off")).toContain("muted");
  });

  it("marks hoppie wait as in-progress", () => {
    expect(chipTone("Hoppie wait")).toContain("accent");
    expect(chipTone("PWR ?")).toContain("muted");
  });

  it("tolerates undefined", () => {
    expect(chipTone(undefined)).toContain("muted");
  });
});

describe("isElevationError", () => {
  it("only matches the bridge NEEDS_ELEVATION marker", () => {
    expect(isElevationError("NEEDS_ELEVATION:Run as Administrator")).toBe(true);
    expect(
      isElevationError(
        "Run this app as Administrator so it can intercept ACARS traffic",
      ),
    ).toBe(false);
    expect(isElevationError("printer requires elevated privileges")).toBe(false);
    expect(isElevationError("printer offline")).toBe(false);
  });
});

describe("mergeStatus", () => {
  const base: BridgeStatus = {
    running: false,
    exchanges: 0,
    last_error: null,
    network_id: null,
    network_label: "",
    link: { id: "link", text: "LINK off", state: "off" },
    chips: {
      flt: "FLT —",
      link: "LINK off",
      pwr: "PWR —",
      sterile: "STERILE off",
      ofp: "OFP —",
      clock: "UTC —",
    },
    chip_tips: {},
    auto_print: true,
    sim_connected: false,
    message_count: 0,
  };

  it("keeps chips when payload is partial or null", () => {
    expect(mergeStatus(base, null).chips.link).toBe("LINK off");
    expect(mergeStatus(base, { running: true }).chips.link).toBe("LINK off");
    expect(
      mergeStatus(base, { chips: { link: "LINK ok · 12:00Z" } }).chips.link,
    ).toBe("LINK ok · 12:00Z");
  });
});
