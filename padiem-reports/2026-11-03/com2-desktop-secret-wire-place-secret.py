#!/usr/bin/env python3
"""Place one shared desktop secret in the Chat and P01 env files (2026-11-03).

Prints only length, last four characters, modes and booleans. Never prints the
secret or an env line value.
"""
import os
import secrets
import shutil
import stat
import string
import sys

CHAT_ENV = "/opt/padiem/chat-com2/.env"
P01_ENV = "/opt/padiem/p01/env/p01.env"
CHAT_BAK = CHAT_ENV + ".bak-20261103-desktop-secret"
P01_BAK = P01_ENV + ".bak-20261103-desktop-secret"
SECURE_DIR = "/root/padiem-secure"
SECURE_FILE = SECURE_DIR + "/claw-engine-desktop-secret-20261103.txt"
SECRET_NAME = "CLAW_ENGINE_DESKTOP_SECRET"
CHAT_ORIGIN_NAME = "PADIEM_ENGINE_LOCAL_CHAT_ORIGIN"
CHAT_ORIGIN = "http://127.0.0.1:8798"


def fail(reason):
    print("PLACE_ABORT=" + reason)
    sys.exit(2)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def set_line(text, name, value):
    kept = []
    replaced = False
    for line in text.splitlines(keepends=True):
        if line.startswith(name + "="):
            if replaced:
                fail("duplicate_" + name)
            ended = "\n" if line.endswith("\n") else ""
            kept.append(name + "=" + value + ended)
            replaced = True
        else:
            kept.append(line)
    if not replaced:
        if kept and not kept[-1].endswith("\n"):
            kept.append("\n")
        kept.append(name + "=" + value + "\n")
    return "".join(kept)


def has_line(text, name):
    return any(line.startswith(name + "=") for line in text.splitlines())


def owner(path):
    info = os.stat(path)
    return info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)


def backup(path, target):
    if os.path.exists(target):
        fail("backup_exists_" + os.path.basename(target))
    shutil.copy2(path, target)
    return True


def main():
    for path in (CHAT_ENV, P01_ENV):
        if not os.path.isfile(path):
            fail("missing_" + path)
    chat_text = read(CHAT_ENV)
    p01_text = read(P01_ENV)
    for text, name in ((chat_text, SECRET_NAME), (p01_text, SECRET_NAME),
                       (p01_text, CHAT_ORIGIN_NAME)):
        if has_line(text, name):
            fail("already_present_" + name)
    if os.path.exists(SECURE_FILE):
        fail("secure_file_exists")

    alphabet = string.ascii_letters + string.digits
    secret = "".join(secrets.choice(alphabet) for _ in range(48))
    if len(secret.encode("utf-8")) != 48:
        fail("secret_shape")

    chat_before = owner(CHAT_ENV)
    p01_before = owner(P01_ENV)
    backup(CHAT_ENV, CHAT_BAK)
    backup(P01_ENV, P01_BAK)

    chat_new = set_line(chat_text, SECRET_NAME, secret)
    p01_new = set_line(p01_text, SECRET_NAME, secret)
    p01_new = set_line(p01_new, CHAT_ORIGIN_NAME, CHAT_ORIGIN)

    with open(CHAT_ENV, "w", encoding="utf-8") as handle:
        handle.write(chat_new)
    with open(P01_ENV, "w", encoding="utf-8") as handle:
        handle.write(p01_new)

    if not os.path.isdir(SECURE_DIR):
        os.makedirs(SECURE_DIR, mode=0o700)
    os.chmod(SECURE_DIR, 0o700)
    fd = os.open(SECURE_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(secret + "\n")
    os.chmod(SECURE_FILE, 0o600)

    chat_final = read(CHAT_ENV)
    p01_final = read(P01_ENV)
    chat_value = next(line.split("=", 1)[1] for line in chat_final.splitlines()
                      if line.startswith(SECRET_NAME + "="))
    p01_value = next(line.split("=", 1)[1] for line in p01_final.splitlines()
                     if line.startswith(SECRET_NAME + "="))
    stored = read(SECURE_FILE).strip()
    if not (chat_value == p01_value == stored == secret):
        fail("value_mismatch")
    if len(chat_final.splitlines()) != len(chat_text.splitlines()) + 1:
        fail("chat_line_count")
    if len(p01_final.splitlines()) != len(p01_text.splitlines()) + 2:
        fail("p01_line_count")

    chat_after = owner(CHAT_ENV)
    p01_after = owner(P01_ENV)
    sec_dir = stat.S_IMODE(os.stat(SECURE_DIR).st_mode)
    sec_file = stat.S_IMODE(os.stat(SECURE_FILE).st_mode)
    print("SECRET_LEN=%d SECRET_LAST4=%s" % (len(secret), secret[-4:]))
    print("CHAT_LINES=%d P01_LINES=%d" % (len(chat_final.splitlines()),
                                          len(p01_final.splitlines())))
    print("CHAT_MODE_BEFORE=%o CHAT_MODE_AFTER=%o OWNER_SAME=%s"
          % (chat_before[2], chat_after[2], chat_before == chat_after))
    print("P01_MODE_BEFORE=%o P01_MODE_AFTER=%o OWNER_SAME=%s"
          % (p01_before[2], p01_after[2], p01_before == p01_after))
    print("BACKUP_CHAT=%s BACKUP_P01=%s" % (os.path.isfile(CHAT_BAK),
                                            os.path.isfile(P01_BAK)))
    print("SECURE_DIR_MODE=%o SECURE_FILE_MODE=%o STORE_MATCH=%s"
          % (sec_dir, sec_file, stored == secret))


if __name__ == "__main__":
    main()
