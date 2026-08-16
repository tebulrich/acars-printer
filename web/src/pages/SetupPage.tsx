import { useState } from "react";
import type {
  PrintProfile,
  PrinterChoice,
  Settings,
} from "../types";
import { FormatPage } from "./FormatPage";
import { HotkeysPage } from "./HotkeysPage";
import { NetworkPage } from "./NetworkPage";
import { PrintPage } from "./PrintPage";
import { SettingsPage } from "./SettingsPage";

type SetupSection = "printer" | "network" | "print" | "flight" | "hotkeys";

const SECTIONS: { id: SetupSection; label: string }[] = [
  { id: "printer", label: "Printer" },
  { id: "network", label: "Network" },
  { id: "print", label: "Print" },
  { id: "flight", label: "Flight" },
  { id: "hotkeys", label: "Hotkeys" },
];

interface Props {
  settings: Settings;
  printers: PrinterChoice[];
  profiles: PrintProfile[];
  profileId: string;
  tapConnected: boolean;
  onProfileId: (id: string) => void;
  onChange: (patch: Partial<Settings>) => void;
  onChangeAndSave: (patch: Partial<Settings>) => void;
  onApplyProfile: (id: string) => void;
  onSaveProfile: () => void;
  onDeleteProfile: () => void;
  onSaveFormat: (patch?: Partial<Settings>) => void;
  onSaveAndTest: (patch?: Partial<Settings>) => void;
  onReset: () => void;
  onSaveSettings: () => void;
  onPrintOfp: () => void;
  onUnlockOfp: () => void;
  onCheckUpdates: () => void;
  onOpenCompanion: () => void;
}

export function SetupPage(props: Props) {
  const [section, setSection] = useState<SetupSection>("network");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap gap-2">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`rounded border px-3 py-1.5 text-sm ${
              section === item.id
                ? "border-[var(--accent)] bg-[var(--surface-alt)] font-medium text-[var(--accent)]"
                : "border-[var(--border)] bg-[var(--btn)] text-[var(--muted)] hover:text-[var(--text)]"
            }`}
            onClick={() => setSection(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {section === "printer" && (
          <FormatPage
            settings={props.settings}
            printers={props.printers}
            profiles={props.profiles}
            profileId={props.profileId}
            onProfileId={props.onProfileId}
            onChange={props.onChange}
            onApplyProfile={props.onApplyProfile}
            onSaveProfile={props.onSaveProfile}
            onDeleteProfile={props.onDeleteProfile}
            onSave={props.onSaveFormat}
            onSaveAndTest={props.onSaveAndTest}
            onReset={props.onReset}
          />
        )}
        {section === "network" && (
          <NetworkPage
            settings={props.settings}
            tapConnected={props.tapConnected}
            onChange={props.onChangeAndSave}
            onSave={props.onSaveSettings}
            onOpenCompanion={props.onOpenCompanion}
          />
        )}
        {section === "print" && (
          <PrintPage
            settings={props.settings}
            onChange={props.onChangeAndSave}
            onSave={props.onSaveSettings}
          />
        )}
        {section === "flight" && (
          <SettingsPage
            settings={props.settings}
            onChange={props.onChangeAndSave}
            onSave={props.onSaveSettings}
            onPrintOfp={props.onPrintOfp}
            onUnlockOfp={props.onUnlockOfp}
            onCheckUpdates={props.onCheckUpdates}
          />
        )}
        {section === "hotkeys" && (
          <HotkeysPage
            settings={props.settings}
            onChange={props.onChangeAndSave}
            onSave={props.onSaveSettings}
          />
        )}
      </div>
    </div>
  );
}
