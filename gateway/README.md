# PA-Copilot Gateway

Reach TM1 servers inside a company network from PA-Copilot, without opening
a firewall port.

A TM1 server on a private network (192.168.x.x, or a name only that network
knows) cannot be reached from the cloud. The gateway runs inside that network
and connects **out** to PA-Copilot over HTTPS; PA-Copilot's TM1 requests
travel through it. Install it **once per network**, on any always-on machine
that can reach the TM1 servers — often the TM1 server itself.

## Install (Windows)

1. In PA-Copilot: **Connections → Gateways → Add gateway**. Copy the commands
   it shows — the key is displayed only once.
2. On the gateway machine, download `pa-copilot-gateway.zip` (linked there), extract it,
   open a Command Prompt **as Administrator** in the download folder, and run:

   ```
   pa-copilot-gateway.exe setup --server <PA-Copilot API URL> --key <key> --allow <tm1-host>:<HTTPPortNumber>
   pa-copilot-gateway.exe test
   pa-copilot-gateway.exe install
   ```

   `test` checks that PA-Copilot accepts the key and that each allowed TM1
   server's REST API answers. `install` starts the gateway with Windows.
3. In PA-Copilot, create a **Native** connection with the TM1 address *as the
   gateway machine sees it*, and choose the gateway under **Reached through**.

TM1 must have its REST API on: `HTTPPortNumber=8010` (for example) in
`tm1s.cfg`, then restart the TM1 service.

## Safety

- It forwards only to the TM1 servers on its allow-list
  (`setup --allow host:port`, `setup --remove host:port`).
- Its key is stored in `%PROGRAMDATA%\PA-Copilot Gateway\gateway.json`,
  readable by administrators, SYSTEM and whoever ran setup. A lost or leaked
  key is replaced with **New key** in PA-Copilot; the old one stops working.
- TM1 credentials stay encrypted in PA-Copilot and pass through the gateway
  only inside the requests, as they would to TM1 directly.
- Self-signed TM1 certificates are accepted by default (the usual on-premises
  setup); `setup --verify-tls` requires a trusted certificate.

## Other commands

    pa-copilot-gateway.exe run         run in the current window (Ctrl+C stops)
    pa-copilot-gateway.exe uninstall   stop starting with Windows

On Linux or macOS: `pip install requests`, then `python pa_gateway.py …` with
the same commands, run from your service manager.

## Building

`powershell -ExecutionPolicy Bypass -File .\gateway\build.ps1` builds the
single-file exe with PyInstaller and copies it to
`frontend/public/downloads/`, where the Gateways page links it.
