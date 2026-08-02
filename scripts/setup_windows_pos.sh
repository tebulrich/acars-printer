#!/usr/bin/env bash
# Configure CUPS POS80 → Windows USB share and send a raw test page.
set -euo pipefail

HOST="${POS_HOST:-192.168.1.55}"
SHARE="${POS_SHARE:-POS-80}"
USER_NAME="${POS_USER:-DESKTOP\\tebin}"
QUEUE="${POS_QUEUE:-POS80}"

uri_encode() {
  python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

echo "Target: //${HOST}/${SHARE} as ${USER_NAME}"
echo "CUPS queue: ${QUEUE}"
read -r -s -p "Windows password for ${USER_NAME}: " PASS
echo
if [[ -z "${PASS}" ]]; then
  echo "Password is empty — aborting."
  exit 1
fi

TEST_FILE="$(mktemp /tmp/pos80-test.XXXXXX)"
printf 'ACARS POS TEST\n%s\n\n\n\n' "$(date -u +%Y-%m-%dT%H:%MZ)" >"${TEST_FILE}"

echo "Testing printer share with smbclient print (not ls — printer shares have no directory)…"
set +e
SMB_OUT="$(smbclient "//${HOST}/${SHARE}" -U "${USER_NAME}%${PASS}" -c "print ${TEST_FILE}" 2>&1)"
SMB_RC=$?
set -e
echo "${SMB_OUT}"
if [[ "${SMB_RC}" -ne 0 ]]; then
  echo
  echo "smbclient print failed (exit ${SMB_RC})."
  echo "Trying alternate user form tebin@${HOST}…"
  set +e
  SMB_OUT="$(smbclient "//${HOST}/${SHARE}" -U "tebin%${PASS}" -c "print ${TEST_FILE}" 2>&1)"
  SMB_RC=$?
  set -e
  echo "${SMB_OUT}"
  if [[ "${SMB_RC}" -ne 0 ]]; then
    rm -f "${TEST_FILE}"
    cat <<'EOF'

Windows is denying remote print on the POS share (NT_STATUS_ACCESS_DENIED).
SMB printer sharing + ESC/POS is unreliable here.

Use the raw TCP bridge instead:

  1) Copy scripts/windows_pos_raw_bridge.ps1 to the Windows PC
  2) On Windows (PowerShell):
       powershell -ExecutionPolicy Bypass -File windows_pos_raw_bridge.ps1 -PrinterName "POS-80"
  3) Allow TCP 9100 inbound on Private networks (firewall)
  4) On Ubuntu / ACARS Print Bridge:
       Printer destination: tcp://192.168.1.55:9100
       (or Settings dropdown if you add it as custom / keep typed tcp URI)

EOF
    exit 1
  fi
  USER_NAME="tebin"
fi

echo "Share print OK — if the POS-80 stayed silent, Windows spooler/USB is the next place to check."

USER_ENC="$(uri_encode "${USER_NAME}")"
PASS_ENC="$(uri_encode "${PASS}")"
URI="smb://${USER_ENC}:${PASS_ENC}@${HOST}/${SHARE}"

echo "Updating CUPS queue ${QUEUE}…"
lpadmin -p "${QUEUE}" -v "${URI}" -E -m raw
lpoptions -p "${QUEUE}" -o auth-info-required=none 2>/dev/null || true
cancel -a "${QUEUE}" 2>/dev/null || true

echo "Sending CUPS raw test page…"
lp -d "${QUEUE}" -o raw -t 'ACARS POS TEST' "${TEST_FILE}"
sleep 3
echo "--- lpstat -p ---"
lpstat -p "${QUEUE}" -l || true
echo "--- queue ---"
lpstat -o "${QUEUE}" || true
rm -f "${TEST_FILE}"

echo
echo "In ACARS Print Bridge: Settings → Printer → ${QUEUE} · POS ESC/POS → Test print"
