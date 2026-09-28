"""PA-Copilot Gateway — reach TM1 servers inside your network from PA-Copilot.

Install once per network, on any always-on machine that can reach your TM1
servers (often the TM1 server itself). It connects OUT to PA-Copilot over
HTTPS and asks for work; nothing connects in, so no firewall port is
opened. It forwards requests only to the TM1 servers you allow.

    pa-gateway setup --server https://pa-copilot-api.vercel.app \
                     --key pagw_... --allow tm1host:8010
    pa-gateway test              check each allowed TM1 server answers
    pa-gateway run               run in this window (Ctrl+C to stop)
    pa-gateway install           start automatically with Windows (admin)
    pa-gateway uninstall         stop starting automatically

The key comes from PA-Copilot: Connections > Gateways > Add gateway.
"""

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import requests
import urllib3

VERSION = "1.0.0"
TASK_NAME = "PA-Copilot Gateway"
WORKERS = 4
POLL_WAIT = 45
PART_BYTES = 512 * 1024
# Response headers that describe the connection to TM1, not the answer.
DROP_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "content-encoding",
    "content-length", "set-cookie", "proxy-authenticate", "upgrade",
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ----------------------------------------------------------------- config


def config_path() -> Path:
    """%PROGRAMDATA% on Windows (readable by the startup task), else ~/.
    PA_GATEWAY_CONFIG overrides it (several gateways on one machine, tests)."""
    if os.environ.get("PA_GATEWAY_CONFIG"):
        return Path(os.environ["PA_GATEWAY_CONFIG"])
    if os.name == "nt" and os.environ.get("PROGRAMDATA"):
        return Path(os.environ["PROGRAMDATA"]) / "PA-Copilot Gateway" / "gateway.json"
    return Path.home() / ".pa-copilot-gateway.json"


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        sys.exit(f"Not set up yet. Run: pa-gateway setup --server ... --key ... --allow host:port\n({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    if os.name == "nt":
        # The key is a credential: readable by administrators, SYSTEM (the
        # startup task) and the person who ran setup — nobody else.
        grants = ["*S-1-5-32-544:F", "*S-1-5-18:F"]
        if os.environ.get("USERNAME"):
            domain = os.environ.get("USERDOMAIN", ".")
            grants.append(domain + "\\" + os.environ["USERNAME"] + ":F")
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", *grants],
            capture_output=True, check=False,
        )
    else:
        path.chmod(0o600)
    return path


def normalise_target(value: str) -> str:
    value = value.strip().lower()
    if "://" in value:
        parts = urlsplit(value)
        value = f"{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}"
    if ":" not in value:
        sys.exit(f"'{value}' needs a port, e.g. {value}:8010 (TM1's HTTPPortNumber).")
    return value


# ---------------------------------------------------------------- relay


def encode(data: bytes) -> str:
    return base64.b64encode(zlib.compress(data)).decode("ascii")


def decode(text: str) -> bytes:
    return zlib.decompress(base64.b64decode(text))


def split_answer(request_id: str, answer: dict, body: bytes) -> list[dict]:
    """Same format as the backend's src/tm1/gateway/relay.split_answer."""
    data = encode(body)
    chunk = PART_BYTES * 4 // 3
    pieces = [data[i:i + chunk] for i in range(0, len(data), chunk)] or [""]
    parts = []
    for index, piece in enumerate(pieces):
        part = {"id": request_id, "index": index, "parts": len(pieces), "data": piece}
        if index == 0:
            part.update(answer)
        parts.append(part)
    return parts


class Gateway:
    def __init__(self, cfg: dict) -> None:
        self.server = cfg["server"].rstrip("/")
        self.key = cfg["key"]
        self.allow = {normalise_target(t) for t in cfg.get("allow", [])}
        self.verify_tls = bool(cfg.get("verify_tls", False))
        self.hostname = socket.gethostname()
        self._stop = threading.Event()

    # --- one TM1 request ---------------------------------------------------

    def forward(self, message: dict, tm1: requests.Session) -> tuple[dict, bytes]:
        url = message["url"]
        parts = urlsplit(url)
        target = f"{(parts.hostname or '').lower()}:{parts.port or (443 if parts.scheme == 'https' else 80)}"
        if target not in self.allow:
            return {"error": (
                f"{target} is not on this gateway's allow-list. On the gateway "
                f"machine run: pa-gateway setup --allow {target}"
            )}, b""

        headers = {k: v for k, v in (message.get("headers") or {}).items()
                   if k.lower() not in ("host", "content-length")}
        body = decode(message["body"]) if message.get("body") else None
        try:
            response = tm1.request(
                message["method"], url, headers=headers, data=body,
                verify=self.verify_tls, timeout=float(message.get("timeout") or 60),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            return {"error": f"Could not reach TM1 at {target}: {type(exc).__name__}: {exc}"[:1900]}, b""
        finally:
            # Never carry one PA-Copilot session's TM1 cookie into the next
            # request: PA-Copilot keeps each session's cookies itself.
            tm1.cookies.clear()

        return {
            "status": response.status_code,
            "reason": response.reason or "",
            "headers": {k: v for k, v in response.headers.items() if k.lower() not in DROP_HEADERS},
            "cookies": response.cookies.get_dict(),
        }, response.content

    # --- the loop -----------------------------------------------------------

    def worker(self, number: int) -> None:
        api = requests.Session()
        api.headers["Authorization"] = f"Bearer {self.key}"
        tm1 = requests.Session()
        backoff = 2
        while not self._stop.is_set():
            try:
                reply = api.post(
                    f"{self.server}/gateway/poll",
                    json={"version": VERSION, "hostname": self.hostname, "wait": POLL_WAIT},
                    timeout=POLL_WAIT + 20,
                )
                if reply.status_code == 204:
                    backoff = 2
                    continue
                if reply.status_code in (401, 403):
                    print("PA-Copilot rejected the gateway key. Create a new key in "
                          "Connections > Gateways and run setup again.", flush=True)
                    time.sleep(60)
                    continue
                reply.raise_for_status()
                message = reply.json()["request"]
                started = time.monotonic()
                answer, body = self.forward(message, tm1)
                for part in split_answer(message["id"], answer, body):
                    api.post(f"{self.server}/gateway/answer", json=part, timeout=60).raise_for_status()
                print(f"[{number}] {message['method']} {urlsplit(message['url']).path} "
                      f"-> {answer.get('status', 'error')} ({int((time.monotonic() - started) * 1000)} ms)",
                      flush=True)
                backoff = 2
            except requests.RequestException as exc:
                print(f"[{number}] PA-Copilot not reachable ({type(exc).__name__}); retrying in {backoff}s",
                      flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def run(self) -> None:
        print(f"PA-Copilot Gateway {VERSION} on {self.hostname}")
        print(f"  server : {self.server}")
        print(f"  allowed: {', '.join(sorted(self.allow)) or '(none - add with setup --allow)'}")
        threads = [threading.Thread(target=self.worker, args=(n + 1,), daemon=True) for n in range(WORKERS)]
        for thread in threads:
            thread.start()
        print("Running. Leave this window open, or run 'pa-gateway install'. Ctrl+C to stop.", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            self._stop.set()


# ---------------------------------------------------------------- commands


def cmd_setup(args) -> None:
    path = config_path()
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if args.server:
        cfg["server"] = args.server.rstrip("/")
    if args.key:
        cfg["key"] = args.key.strip()
    allow = set(cfg.get("allow", []))
    allow.update(normalise_target(t) for t in args.allow or [])
    allow.difference_update(normalise_target(t) for t in args.remove or [])
    cfg["allow"] = sorted(allow)
    if args.verify_tls is not None:
        cfg["verify_tls"] = args.verify_tls
    for field in ("server", "key"):
        if not cfg.get(field):
            sys.exit(f"--{field} is required the first time.")
    print(f"Saved {save_config(cfg)}")
    print(f"Allowed TM1 servers: {', '.join(cfg['allow']) or '(none)'}")


def cmd_test(args) -> None:
    cfg = load_config()
    gateway = Gateway(cfg)
    ok = True
    try:
        reply = requests.post(
            f"{gateway.server}/gateway/poll",
            headers={"Authorization": f"Bearer {gateway.key}"},
            json={"version": VERSION, "hostname": gateway.hostname, "wait": 1}, timeout=30,
        )
        print(f"PA-Copilot: {'key accepted' if reply.status_code in (200, 204) else f'HTTP {reply.status_code}'}")
        ok &= reply.status_code in (200, 204)
    except requests.RequestException as exc:
        print(f"PA-Copilot: not reachable ({exc})")
        ok = False
    for target in sorted(gateway.allow):
        for scheme in ("https", "http"):
            try:
                r = requests.get(f"{scheme}://{target}/api/v1/Configuration/ProductVersion",
                                 verify=gateway.verify_tls, timeout=10)
                print(f"TM1 {target}: REST API answers over {scheme} (HTTP {r.status_code})")
                break
            except requests.RequestException:
                continue
        else:
            print(f"TM1 {target}: no answer - check HTTPPortNumber in tm1s.cfg and the TM1 service")
            ok = False
    sys.exit(0 if ok else 1)


def _self_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" run'
    return f'"{sys.executable}" "{Path(__file__).resolve()}" run'


def cmd_install(args) -> None:
    if os.name != "nt":
        sys.exit("On Linux, run 'pa-gateway run' from systemd or your service manager.")
    result = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", _self_command(),
         "/SC", "ONSTART", "/RU", "SYSTEM", "/RL", "HIGHEST", "/F"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        sys.exit(f"Could not install (run this window as Administrator): {result.stderr.strip()}")
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, check=False)
    print("Installed: the gateway now starts with Windows, and is running.")


def cmd_uninstall(args) -> None:
    subprocess.run(["schtasks", "/End", "/TN", TASK_NAME], capture_output=True, check=False)
    result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True, check=False)
    print("Removed." if result.returncode == 0 else result.stderr.strip())


def main() -> None:
    parser = argparse.ArgumentParser(prog="pa-gateway", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="save the server, key and allowed TM1 servers")
    setup.add_argument("--server")
    setup.add_argument("--key")
    setup.add_argument("--allow", action="append", metavar="HOST:PORT")
    setup.add_argument("--remove", action="append", metavar="HOST:PORT")
    setup.add_argument("--verify-tls", dest="verify_tls", action="store_true", default=None)
    setup.add_argument("--no-verify-tls", dest="verify_tls", action="store_false")
    sub.add_parser("test", help="check PA-Copilot and each allowed TM1 server")
    sub.add_parser("run", help="run in this window")
    sub.add_parser("install", help="start automatically with Windows (Administrator)")
    sub.add_parser("uninstall", help="stop starting automatically")
    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "run":
        Gateway(load_config()).run()
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)


if __name__ == "__main__":
    main()
