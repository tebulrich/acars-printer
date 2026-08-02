#Requires -Version 5.1
<#
.SYNOPSIS
  Listen on TCP 9100 and forward raw bytes to a local Windows printer (ESC/POS / POS-80).

.DESCRIPTION
  Run this on the Windows PC that has the POS-80 on USB. Then from Ubuntu / ACARS:

    tcp://THIS_PC_IP:9100

  Example:
    powershell -ExecutionPolicy Bypass -File windows_pos_raw_bridge.ps1 -PrinterName "POS-80"
#>
param(
    [string]$PrinterName = "POS-80",
    [int]$Port = 9100,
    [string]$BindAddress = "0.0.0.0"
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Printing
# winspool RAW jobs via .NET PrintDocument are awkward; use Win32 raw API.
$code = @"
using System;
using System.Runtime.InteropServices;

public static class RawPrinter {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)]
  public class DOCINFOA {
    [MarshalAs(UnmanagedType.LPStr)] public string pDocName;
    [MarshalAs(UnmanagedType.LPStr)] public string pOutputFile;
    [MarshalAs(UnmanagedType.LPStr)] public string pDataType;
  }

  [DllImport("winspool.Drv", EntryPoint="OpenPrinterA", SetLastError=true, CharSet=CharSet.Ansi)]
  public static extern bool OpenPrinter(string szPrinter, out IntPtr hPrinter, IntPtr pd);

  [DllImport("winspool.Drv", EntryPoint="ClosePrinter", SetLastError=true)]
  public static extern bool ClosePrinter(IntPtr hPrinter);

  [DllImport("winspool.Drv", EntryPoint="StartDocPrinterA", SetLastError=true, CharSet=CharSet.Ansi)]
  public static extern bool StartDocPrinter(IntPtr hPrinter, Int32 level, [In] DOCINFOA di);

  [DllImport("winspool.Drv", EntryPoint="EndDocPrinter", SetLastError=true)]
  public static extern bool EndDocPrinter(IntPtr hPrinter);

  [DllImport("winspool.Drv", EntryPoint="StartPagePrinter", SetLastError=true)]
  public static extern bool StartPagePrinter(IntPtr hPrinter);

  [DllImport("winspool.Drv", EntryPoint="EndPagePrinter", SetLastError=true)]
  public static extern bool EndPagePrinter(IntPtr hPrinter);

  [DllImport("winspool.Drv", EntryPoint="WritePrinter", SetLastError=true)]
  public static extern bool WritePrinter(IntPtr hPrinter, IntPtr pBytes, Int32 dwCount, out Int32 dwWritten);

  public static void SendBytes(string printer, byte[] data) {
    IntPtr hPrinter;
    if (!OpenPrinter(printer, out hPrinter, IntPtr.Zero)) {
      throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "OpenPrinter failed");
    }
    try {
      var di = new DOCINFOA();
      di.pDocName = "ACARS raw";
      di.pDataType = "RAW";
      if (!StartDocPrinter(hPrinter, 1, di)) {
        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "StartDocPrinter failed");
      }
      try {
        if (!StartPagePrinter(hPrinter)) {
          throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "StartPagePrinter failed");
        }
        try {
          IntPtr p = Marshal.AllocHGlobal(data.Length);
          try {
            Marshal.Copy(data, 0, p, data.Length);
            int written;
            if (!WritePrinter(hPrinter, p, data.Length, out written)) {
              throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "WritePrinter failed");
            }
          } finally {
            Marshal.FreeHGlobal(p);
          }
        } finally {
          EndPagePrinter(hPrinter);
        }
      } finally {
        EndDocPrinter(hPrinter);
      }
    } finally {
      ClosePrinter(hPrinter);
    }
  }
}
"@

if (-not ("RawPrinter" -as [type])) {
    Add-Type -TypeDefinition $code -Language CSharp
}

$printers = Get-Printer | Select-Object -ExpandProperty Name
if ($printers -notcontains $PrinterName) {
    Write-Host "Printer '$PrinterName' not found. Installed printers:" -ForegroundColor Yellow
    $printers | ForEach-Object { Write-Host "  - $_" }
    throw "Set -PrinterName to the exact Windows printer name."
}

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($BindAddress), $Port)
$listener.Start()
Write-Host "POS raw bridge listening on ${BindAddress}:${Port} -> '$PrinterName'" -ForegroundColor Green
Write-Host "From Ubuntu use: tcp://$((Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' } | Select-Object -First 1 -ExpandProperty IPAddress)):$Port"
Write-Host "Ctrl+C to stop."

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        $remote = $client.Client.RemoteEndPoint.ToString()
        $stream = $client.GetStream()
        $ms = New-Object System.IO.MemoryStream
        $buffer = New-Object byte[] 8192
        try {
            while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $ms.Write($buffer, 0, $read)
                if (-not $stream.DataAvailable) { break }
            }
            $bytes = $ms.ToArray()
            Write-Host "$(Get-Date -Format o)  $remote  $($bytes.Length) bytes"
            if ($bytes.Length -gt 0) {
                [RawPrinter]::SendBytes($PrinterName, $bytes)
                Write-Host "  -> sent RAW to $PrinterName" -ForegroundColor Green
            }
        } catch {
            Write-Host "  ERROR: $_" -ForegroundColor Red
        } finally {
            $ms.Dispose()
            $stream.Close()
            $client.Close()
        }
    }
} finally {
    $listener.Stop()
}
