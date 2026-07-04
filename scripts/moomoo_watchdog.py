#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watch dog for moomoo OpenD SSH tunnel (via DSA stock-server container).

Runs every 5 minutes (systemd timer). Sends email to chenzhenben@gmail.com
when the tunnel transitions up<->down. State persisted on host filesystem
so docker restarts do not lose history. Implements 2-strike debounce:
a "down" alert is only sent after 2 consecutive failed checks.

Invocation: docker exec stock-server python3 /app/scripts/moomoo_watchdog.py
The /opt/dsa copy on the host is the canonical source; service uses
`docker cp` to sync it into the container before each run.
"""
from __future__ import annotations

import os
import sys
import socket
import logging
import traceback
from datetime import datetime
from pathlib import Path

# Container-internal path (the script runs inside stock-server container).
DSA_APP_DIR = "/app"

# Persistent log + state. In-container these map to bind-mounted host paths:
#   /app/logs  <->  /opt/dsa/logs  (host)
#   /app/data  <->  /opt/dsa/data  (host)
LOG_PATH = os.getenv("WATCHDOG_LOG_PATH", "/app/logs/dsa-moomoo-watchdog.log")
STATE_PATH = os.getenv("WATCHDOG_STATE_PATH", "/app/data/dsa-moomoo-watchdog.state")

SMTP_RECEIVER = "chenzhenben@gmail.com"

# Tunables
PORT_HOST = os.getenv("MOOMOO_HOST", "127.0.0.1")
PORT_NUM = int(os.getenv("MOOMOO_PORT", "11111"))
PORT_TIMEOUT_SEC = float(os.getenv("WATCHDOG_PORT_TIMEOUT", "3"))

# Send "down" alert only after this many consecutive failures.
FAIL_DEBOUNCE = int(os.getenv("WATCHDOG_FAIL_DEBOUNCE", "2"))


def _setup_logging() -> None:
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.insert(0, logging.FileHandler(LOG_PATH))
    except Exception as exc:
        print("FileHandler init failed (continuing with stdout):", exc, file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def check_port() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(PORT_TIMEOUT_SEC)
        s.connect((PORT_HOST, PORT_NUM))
        s.close()
        return True
    except Exception as exc:
        logging.debug("check_port failed: %s", exc)
        return False


def _build_fetcher():
    if DSA_APP_DIR not in sys.path:
        sys.path.insert(0, DSA_APP_DIR)
    from data_provider.moomoo_fetcher import MoomooFetcher
    return MoomooFetcher()


def check_with_fetcher(fetcher) -> tuple:
    """Run health + login probes using an existing fetcher. Returns
    (is_up, health_ok, health_detail, login_ok, login_detail)."""
    health_ok, health_detail = False, "not run"
    login_ok, login_detail = False, "skipped (health down)"
    try:
        ok = bool(fetcher.health_check())
        health_ok = ok
        health_detail = "health_check=" + str(ok)
    except Exception as exc:
        health_detail = "health_check exception: " + type(exc).__name__ + ": " + str(exc)
    if health_ok:
        try:
            ret, data = fetcher._ensure_ctx().get_market_snapshot(["US.AAPL"])
            ok = (ret == 0) and data is not None and not isinstance(data, str)
            if ok and hasattr(data, "iloc"):
                login_ok = True
                name = data.iloc[0].get("name")
                login_detail = "snapshot=ok name=" + str(name)
            else:
                login_detail = "snapshot ret=" + str(ret) + " data=" + (data if isinstance(data, str) else "empty")
        except Exception as exc:
            login_detail = "snapshot exception: " + type(exc).__name__ + ": " + str(exc)
    is_up = health_ok and login_ok
    return is_up, health_ok, health_detail, login_ok, login_detail


def load_state() -> bool:
    """Returns True if last saved state was "up", False if "down".
    State file format: "up,N" / "down,N" where N is the fail-streak counter."""
    try:
        p = Path(STATE_PATH)
        if not p.exists():
            return True
        return p.read_text().strip().split(",")[0] == "up"
    except Exception as exc:
        logging.warning("load_state failed: %s", exc)
        return True


def load_failure_count() -> int:
    try:
        p = Path(STATE_PATH)
        if not p.exists():
            return 0
        parts = p.read_text().strip().split(",")
        if len(parts) < 2:
            return 0
        return int(parts[1])
    except Exception:
        return 0


def save_state(is_up: bool, fail_count: int) -> None:
    try:
        p = Path(STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(("up" if is_up else "down") + "," + str(fail_count))
    except Exception as exc:
        logging.warning("save_state failed: %s", exc)


def send_email(subject: str, body: str) -> bool:
    try:
        if DSA_APP_DIR not in sys.path:
            sys.path.insert(0, DSA_APP_DIR)
        from src.notification import get_notification_service
        svc = get_notification_service()
        ok = svc.send_to_email(content=body, subject=subject, receivers=[SMTP_RECEIVER])
        if ok:
            logging.info("email sent: %s", subject)
        else:
            logging.error("email send returned False: %s", subject)
        return ok
    except Exception as exc:
        logging.error("send_email exception: %s", exc)
        logging.debug(traceback.format_exc())
        return False


def _body_down(failed_items, details):
    details_block = "\n".join("  - " + d for d in details)
    return (
        "[DSA-ALERT] moomoo OpenD tunnel DOWN\n"
        "\n"
        "Time: " + datetime.now().isoformat(timespec="seconds") + "\n"
        "Check items: port " + str(PORT_NUM) + " / health_check / snapshot(US.AAPL)\n"
        "Failed: " + (", ".join(failed_items) or "(unknown)") + "\n"
        "\n"
        "Detail:\n" + details_block + "\n"
        "\n"
        "Impact:\n"
        "- US/HK real-time data falls back to YFinance (~15min delay)\n"
        "- Capital distribution / capital flow temporarily unavailable\n"
        "\n"
        "Troubleshoot:\n"
        "1. Check macOS is awake + moomoo app is running\n"
        "2. Check autossh launchd: launchctl list | grep moomoo-tunnel\n"
        "3. Restart tunnel: launchctl kickstart -k gui/$(id -u)/com.dsa.moomoo-tunnel\n"
        "4. Verify: ssh root@server \"ss -tln | grep " + str(PORT_NUM) + "\"\n"
        "\n"
        "(automated email from /opt/dsa/scripts/moomoo_watchdog.py)\n"
    )


def _body_up():
    return (
        "[DSA-RECOVERED] moomoo OpenD tunnel UP\n"
        "\n"
        "Time: " + datetime.now().isoformat(timespec="seconds") + "\n"
        "Check items: port " + str(PORT_NUM) + " / health_check / snapshot(US.AAPL)\n"
        "Status: ALL OK\n"
        "\n"
        "DSA capital distribution / capital flow back to normal.\n"
        "\n"
        "(automated email from /opt/dsa/scripts/moomoo_watchdog.py)\n"
    )


def main() -> int:
    _setup_logging()
    logging.info("=== moomoo watchdog run ===")

    port_ok = check_port()
    health_ok = False
    health_detail = "skipped (port down)"
    login_ok = False
    login_detail = "skipped (health down)"
    fetcher = None
    try:
        if port_ok:
            try:
                fetcher = _build_fetcher()
                _, health_ok, health_detail, login_ok, login_detail = check_with_fetcher(fetcher)
            except Exception as exc:
                health_ok = False
                health_detail = "init failed: " + type(exc).__name__ + ": " + str(exc)
                logging.warning("MoomooFetcher init failed: %s", exc)
    finally:
        if fetcher is not None:
            try:
                fetcher.close()
            except Exception:
                pass

    is_up = port_ok and health_ok and login_ok
    was_up = load_state()
    prev_fail = load_failure_count()

    # 2-strike debounce: emit the down alert on the FAIL_DEBOUNCE-th
    # consecutive failed check. Effective state is derived from fail_streak:
    # effective_up = (fail_streak < threshold). A single blip stays "up",
    # only a sustained outage flips to "down" and triggers the email.
    if is_up:
        fail_count = 0
    else:
        fail_count = prev_fail + 1
    prev_down = prev_fail >= FAIL_DEBOUNCE
    cur_down = fail_count >= FAIL_DEBOUNCE
    state_changed = cur_down != prev_down

    logging.info(
        "check: port=%s health=%s login=%s state=%s (was %s, fail_streak=%d)",
        port_ok, health_ok, login_ok,
        "up" if is_up else "down",
        "up" if was_up else "down",
        fail_count,
    )

    if state_changed:
        if is_up:
            subject = "[DSA] moomoo OpenD 通道已恢复"
            body = _body_up()
        else:
            failed = []
            details = []
            if not port_ok:
                failed.append("port " + str(PORT_NUM))
                details.append("port " + str(PORT_NUM) + ": connect failed (tunnel likely down)")
            if port_ok and not health_ok:
                failed.append("health_check")
                details.append("health_check: " + health_detail)
            if health_ok and not login_ok:
                failed.append("snapshot (登录态)")
                details.append("snapshot: " + login_detail)
            subject = "[DSA] moomoo OpenD 通道断开"
            body = _body_down(failed, details)
        send_email(subject, body)
        logging.info("alert sent: state -> %s", "up" if is_up else "down")
    else:
        logging.info(
            "no state change (fail_streak=%d, threshold=%d)",
            fail_count, FAIL_DEBOUNCE,
        )

    save_state(is_up, fail_count)
    return 0 if is_up else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.error("watchdog crashed: %s", exc)
        logging.debug(traceback.format_exc())
        sys.exit(2)
