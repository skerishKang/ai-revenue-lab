"""Deliver the COM1 recovery alert using the existing Hermes Telegram config.

Only bounded reason codes are printed; token, chat ID, response bodies and
exception strings are never logged. The message travels via a file or --test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
from urllib import error, request


class NotifyFailure(Exception):
    pass


def read_config(home: Path, environ: dict[str, str]) -> tuple[str, str]:
    dotenv = {}
    try:
        for line in (home / ".env").read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            dotenv[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    token = environ.get("TELEGRAM_BOT_TOKEN") or dotenv.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise NotifyFailure("TELEGRAM_TOKEN_MISSING")
    try:
        import yaml
    except ImportError:
        raise NotifyFailure("TELEGRAM_YAML_UNAVAILABLE") from None
    try:
        cfg = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, yaml.YAMLError):
        raise NotifyFailure("TELEGRAM_CONFIG_UNREADABLE") from None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("telegram"), dict):
        raise NotifyFailure("TELEGRAM_CONFIG_MISSING")
    chat = cfg["telegram"].get("home_channel")
    if not isinstance(chat, (str, int)) or isinstance(chat, bool) or not str(chat).strip():
        raise NotifyFailure("TELEGRAM_CHAT_MISSING")
    return str(token).strip(), str(chat).strip()


def send_message(token: str, chat: str, text: str) -> None:
    body = json.dumps({"chat_id": chat, "text": text}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "padiem-com1-recovery/1.0"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            status = resp.status
            data = json.loads(resp.read(65537))
    except error.HTTPError as exc:
        raise NotifyFailure("TELEGRAM_HTTP_" + str(exc.code)) from None
    except (error.URLError, TimeoutError, socket.timeout, OSError):
        raise NotifyFailure("TELEGRAM_NETWORK_ERROR") from None
    except (ValueError, UnicodeError):
        raise NotifyFailure("TELEGRAM_RESPONSE_INVALID") from None
    if status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
        raise NotifyFailure("TELEGRAM_API_REJECTED")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path)
    group.add_argument("--test", action="store_true")
    args = parser.parse_args()
    try:
        if args.test:
            text = "PADIEM \ucef41 \uc54c\ub9bc \uc2dc\ud5d8"
        else:
            try:
                text = args.file.read_text(encoding="utf-8-sig").strip()
            except OSError:
                raise NotifyFailure("TELEGRAM_MESSAGE_UNREADABLE") from None
        if not text:
            raise NotifyFailure("TELEGRAM_MESSAGE_EMPTY")
        home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
        token, chat = read_config(home, os.environ)
        send_message(token, chat, text)
    except NotifyFailure as exc:
        print(str(exc))
        return 1
    except Exception:
        print("TELEGRAM_INTERNAL_ERROR")
        return 1
    print("TELEGRAM_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
