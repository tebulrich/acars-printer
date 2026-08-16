export type AppView = "messages" | "setup";

export interface Meta {
  version: string;
  product: string;
  data_dir: string;
}

export interface BridgeStatus {
  running: boolean;
  exchanges: number;
  last_error: string | null;
  network_id: string | null;
  network_label: string;
  link: { id: string; text: string; state: string; tip?: string };
  chips: {
    flt: string;
    link: string;
    pwr: string;
    sterile: string;
    ofp: string;
    clock: string;
  };
  chip_tips: Record<string, string>;
  auto_print: boolean;
  sim_connected: boolean;
  /** Total stored messages; UI reloads list when this changes. */
  message_count?: number;
}

export interface Settings {
  callsign: string;
  aircraft_registration: string;
  acars_network: string;
  networks: { id: string; label: string }[];
  printer_destination: string;
  printer_input_mode: string;
  paper_width: string;
  cut_enabled: boolean;
  print_render_mode: string;
  print_glyph_px: number;
  print_line_gap_px: number;
  print_font: string;
  print_char_width: number;
  print_char_height: number;
  print_bold: boolean;
  print_columns: number | null;
  print_line_spacing_dots: number | null;
  print_lead_in: number;
  print_tear_feed: number;
  auto_print: boolean;
  auto_connect: boolean;
  check_updates: boolean;
  printable_types: string[];
  printable_type_choices: string[];
  simbrief_ofp_tickets: string[];
  ofp_ticket_choices: string[];
  wx_auto_enabled: boolean;
  wx_auto_nm: number;
  wx_auto_kinds: string[];
  wx_auto_kind_choices: string[];
  atis_source: string;
  hotkeys_enabled: boolean;
  hotkey_bindings: Record<string, string>;
  hotkey_actions: string[];
  sterile_agl_ft: number;
  sterile_agl_choices: number[];
  print_when_powered: boolean;
  xplane_host: string;
  xplane_port: number;
  simbrief_user: string;
  simbrief_enabled: boolean;
  simbrief_post_landing_grace_seconds: number;
  active_print_profile: string | null;
  has_hoppie_logon: boolean;
  /** Write-only: send a new logon to save; leave empty to keep the stored one. */
  hoppie_logon?: string;
  companion_enabled: boolean;
  companion_station_enabled: boolean;
  companion_port: number;
  companion_token: string;
  companion_url: string;
  companion_qr_png?: string;
  station_blocked?: string;
}

export interface MessageRow {
  id: number;
  received_at: string;
  direction: string;
  station: string;
  message_type: string;
  print_status: string | null;
  print_mark: string;
  preview: string;
  callsign: string;
  normalized_body?: string;
  raw_payload?: string;
}

export interface PrinterChoice {
  label: string;
  destination: string;
}

export interface PrintProfile {
  id: string;
  label: string;
  builtin: boolean;
  payload: Record<string, unknown>;
}

export interface BootResult {
  meta: Meta;
  settings: Settings;
  status: BridgeStatus;
  messages: MessageRow[];
  printers: PrinterChoice[];
  profiles: PrintProfile[];
}

export interface Toast {
  message: string;
  error?: boolean;
}
