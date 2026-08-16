import { describe, expect, it } from "vitest";
import {
  destinationFromPathDraft,
  inferPrinterInputMode,
  normalizePrinterDestination,
  parseTcpPrinter,
  tcpPrinterDestination,
  windowsSharePath,
} from "./printerDest";

describe("tcp printer destination", () => {
  it("builds tcp://host:port", () => {
    expect(tcpPrinterDestination("192.168.1.50", 9100)).toBe(
      "tcp://192.168.1.50:9100",
    );
    expect(tcpPrinterDestination("  pos.local  ", 9101)).toBe(
      "tcp://pos.local:9101",
    );
    expect(tcpPrinterDestination("", 9100)).toBe("");
    expect(tcpPrinterDestination("pos.local", 0)).toBe("tcp://pos.local:9100");
  });

  it("parses host and default port", () => {
    expect(parseTcpPrinter("tcp://192.168.1.50:9100")).toEqual({
      host: "192.168.1.50",
      port: 9100,
    });
    expect(parseTcpPrinter("tcp://pos.local")).toEqual({
      host: "pos.local",
      port: 9100,
    });
    expect(parseTcpPrinter("win32://EPSON")).toBeNull();
    expect(parseTcpPrinter("console")).toBeNull();
  });

  it("normalizes UNC share paths to win32://", () => {
    expect(normalizePrinterDestination("\\\\192.168.1.10\\POS-80")).toBe(
      "win32://\\\\192.168.1.10\\POS-80",
    );
    expect(normalizePrinterDestination("//pedestal/POS-80")).toBe(
      "win32://\\\\pedestal\\POS-80",
    );
    expect(normalizePrinterDestination("win32://EPSON")).toBe("win32://EPSON");
    expect(normalizePrinterDestination("tcp://10.0.0.8:9100")).toBe(
      "tcp://10.0.0.8:9100",
    );
    expect(normalizePrinterDestination("")).toBe("console");
  });

  it("extracts a typed Windows share from a destination", () => {
    expect(windowsSharePath("win32://\\\\192.168.1.10\\POS-80")).toBe(
      "\\\\192.168.1.10\\POS-80",
    );
    expect(windowsSharePath("win32://EPSON")).toBe("");
    expect(windowsSharePath("tcp://10.0.0.1:9100")).toBe("");
  });

  it("infers list, ip, or windows path", () => {
    expect(inferPrinterInputMode("console")).toBe("list");
    expect(inferPrinterInputMode("win32://EPSON")).toBe("list");
    expect(inferPrinterInputMode("win32://\\\\192.168.1.10\\POS-80")).toBe("path");
    expect(inferPrinterInputMode("tcp://10.0.0.8:9100")).toBe("ip");
  });

  it("keeps a typed draft until it is a full UNC share", () => {
    expect(
      destinationFromPathDraft("\\\\192.168.1.10", "console", "console"),
    ).toBe("\\\\192.168.1.10");
    expect(
      destinationFromPathDraft(
        "\\\\192.168.1.10\\POS-80",
        "console",
        "console",
      ),
    ).toBe("win32://\\\\192.168.1.10\\POS-80");
    expect(
      destinationFromPathDraft("", "win32://\\\\192.168.1.10\\POS-80", "console"),
    ).toBe("console");
  });
});
