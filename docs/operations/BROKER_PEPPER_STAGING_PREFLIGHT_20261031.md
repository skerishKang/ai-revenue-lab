# Broker pepper staging preflight

Run only during the approved COM2 staging startup, by the designated COM2 operator.
Read metadata only; never print file contents, environment values, credentials, or secrets.

1. Inspect the configured pepper file path from the service environment privately; verify it is an absolute non-symlink regular file, outside the database and backup directories. Do not publish the path if the deployment treats it as private.
2. On the host, use `stat -c '%a %U %G %F' -- "$pepper_file"` and verify a regular file owned by the intended service owner with mode 0600; verify each parent path is trusted and is not a symlink. Bind `pepper_file` locally without echoing its value.
3. Verify the actual service account can read it using `sudo -u padiem-broker test -r "$pepper_file"`; record only the exit status. Do not change permissions or generate secrets.
4. Confirm backup paths exclude the pepper file and its containing directory. Record PASS/FAIL only, without secret values; fail closed on missing file, wrong mode, inaccessible file, symlink, or overlap.

This is a future staging check, not evidence that COM2 has been inspected.
