import { describe, expect, it } from "vitest";
import { formatMessageTime } from "./time";

describe("formatMessageTime", () => {
  it("uses d.m.Y - H:i:s in UTC", () => {
    expect(formatMessageTime("2026-08-11T15:53:17+00:00")).toBe(
      "11.08.2026 - 15:53:17",
    );
    expect(formatMessageTime("2026-08-02T08:05:09Z")).toBe("02.08.2026 - 08:05:09");
  });

  it("keeps seconds that HH:MM slices used to drop", () => {
    expect(formatMessageTime("2026-08-11T16:35:42+00:00")).toBe(
      "11.08.2026 - 16:35:42",
    );
  });

  it("handles empty values", () => {
    expect(formatMessageTime("")).toBe("—");
    expect(formatMessageTime(undefined)).toBe("—");
  });
});
