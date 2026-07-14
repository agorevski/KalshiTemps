# Remote dashboard access over Tailscale

This guide shows how to view a dashboard running on this machine from a phone that is signed in to the same Tailscale tailnet. It does not require opening the app to the public internet.

## 1. Verify Tailscale is installed and authenticated

On the dashboard machine:

```bash
command -v tailscale
tailscale status
tailscale ip -4
```

Expected results:

- `command -v tailscale` prints a path such as `/usr/bin/tailscale`.
- `tailscale status` lists this device and other tailnet devices. If it says the machine is stopped or unauthenticated, sign in with your normal Tailscale workflow before continuing.
- `tailscale ip -4` prints a `100.x.y.z` tailnet IPv4 address.

To find the tailnet machine name, use one of:

```bash
tailscale status --self
tailscale status
```

The name may also be available through MagicDNS as `machine-name.tailnet-name.ts.net` if MagicDNS is enabled.

## 2. Choose a safe bind address for the app

Run the dashboard on a local port, for example `8000`. Prefer the narrowest bind address that supports your access needs:

| Bind address | Meaning | When to use |
| --- | --- | --- |
| `127.0.0.1` | Localhost only. Other devices cannot connect directly. | Safest default for local-only use or when using `tailscale serve` as a controlled proxy. |
| Tailscale IP, for example `100.x.y.z` | Listens only on the Tailscale interface. | Best direct remote option if the app/framework supports binding to this exact IP. |
| `0.0.0.0` | Listens on all interfaces, including LAN and possibly public interfaces. | Use only when necessary, with firewall rules and trusted networks in mind. |

Examples:

```bash
# Localhost only
python -m http.server 8000 --bind 127.0.0.1

# Bind to the Tailscale IP when supported
python -m http.server 8000 --bind 100.x.y.z

# Broad bind; use carefully
python -m http.server 8000 --bind 0.0.0.0
```

Replace these examples with the actual dashboard start command for this project.

## 3. Check firewall and network access

For direct phone access, the app must be reachable on the chosen port through the Tailscale interface. If you bind to the Tailscale IP but cannot connect:

- Confirm the phone is connected to Tailscale and is in the same tailnet.
- Confirm the app is running and listening on the expected port.
- Check local firewall rules. Allow the port only on the Tailscale interface when possible.
- Avoid opening the port on public or untrusted interfaces unless that is intentional.

## 4. Phone access URL

From the phone browser, while connected to Tailscale, try:

```text
http://100.x.y.z:8000
```

If MagicDNS is enabled, you may also try:

```text
http://machine-name:8000
http://machine-name.tailnet-name.ts.net:8000
```

Use `https://` only if the app or a proxy is configured for TLS.

## 5. Optional: Tailscale Serve vs Funnel

Tailscale has two related features with different exposure levels:

- **Tailscale Serve** publishes a local service to devices in your tailnet. This can be useful when the app binds safely to `127.0.0.1` and Tailscale proxies access for tailnet users.
- **Tailscale Funnel** can expose a service publicly on the internet through Tailscale.

Safety note: do not enable Funnel or any public exposure unless you explicitly intend the dashboard to be reachable outside your tailnet and have reviewed authentication, authorization, and sensitive data risks.

## Helper script

Run the helper to print the machine's likely Tailscale and LAN URLs for a port:

```bash
scripts/check_tailscale_access.sh        # defaults to port 8000
scripts/check_tailscale_access.sh 3000   # custom port
```

The helper only inspects local commands and network addresses. It does not install software or change network settings.
