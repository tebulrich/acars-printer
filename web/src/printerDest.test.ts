import { describe, expect, it } from "vitest";
import { parseTcpPrinter, tcpPrinterDestination } from "./printerDest";

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
});
