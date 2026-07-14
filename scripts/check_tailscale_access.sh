#!/usr/bin/env bash
set -u

PORT="${1:-8000}"

if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Usage: $0 [port]" >&2
  echo "Error: port must be an integer from 1 to 65535." >&2
  exit 2
fi

echo "Tailscale remote access check"
echo "Port: $PORT"
echo

if command -v tailscale >/dev/null 2>&1; then
  echo "tailscale command: $(command -v tailscale)"
  echo

  echo "Tailscale IPs:"
  if ! tailscale ip 2>/dev/null; then
    echo "  Unable to read Tailscale IPs. Tailscale may not be running or authenticated."
  fi
  echo

  echo "Tailscale status:"
  if ! tailscale status 2>/dev/null; then
    echo "  Unable to read Tailscale status. Try signing in or starting Tailscale with your normal workflow."
  fi
else
  echo "tailscale command: not found"
  echo "Install and authenticate Tailscale using your normal device setup before remote tailnet access will work."
fi

echo
TAILSCALE_IPS=""
if command -v tailscale >/dev/null 2>&1; then
  TAILSCALE_IPS="$(tailscale ip -4 2>/dev/null || true)"
fi

LAN_IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | grep -v '^127\.' | grep -v '^100\.' || true)"
HOSTNAME_VALUE="$(hostname 2>/dev/null || printf 'this-machine')"

echo "Likely URLs to try from your phone while connected to Tailscale:"
if [[ -n "$TAILSCALE_IPS" ]]; then
  while IFS= read -r ip; do
    [[ -n "$ip" ]] && echo "  http://$ip:$PORT"
  done <<< "$TAILSCALE_IPS"
else
  echo "  No Tailscale IPv4 address detected."
fi

echo
echo "Possible MagicDNS URLs, if MagicDNS is enabled:"
echo "  http://$HOSTNAME_VALUE:$PORT"
echo "  http://$HOSTNAME_VALUE.<tailnet-name>.ts.net:$PORT"

echo
echo "Possible LAN URLs, useful only when the phone is on the same LAN/VPN route:"
if [[ -n "$LAN_IPS" ]]; then
  while IFS= read -r ip; do
    [[ -n "$ip" ]] && echo "  http://$ip:$PORT"
  done <<< "$LAN_IPS"
else
  echo "  No non-loopback LAN IPv4 address detected."
fi

echo
cat <<NEXT_STEPS
Next steps:
  1. Start the dashboard on port $PORT.
  2. Prefer binding to the Tailscale IP if the app supports it; otherwise use 127.0.0.1 with Tailscale Serve, or 0.0.0.0 only when you understand the exposure.
  3. Confirm any firewall allows port $PORT on the Tailscale interface only, when possible.
  4. Open the Tailscale URL above from the phone browser.

This script is read-only: it does not install packages or change network settings.
NEXT_STEPS
