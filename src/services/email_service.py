"""EmailService — SMTP sender for autonomous agent check-ins.

Reads SMTP credentials from the age-encrypted secret store on the
`templedb` project under profile 'default'. Decryption is
non-interactive: it uses whichever age identity file it can find on
disk without any TTY prompt. If no key file is available, sending
fails with a clear error and the notification row is marked
send_error='no age key file'.

Expected secrets (all under project=templedb, profile=default):

    SMTP_HOST         e.g. smtp.gmail.com
    SMTP_PORT         e.g. 587
    SMTP_USER         SMTP AUTH username
    SMTP_PASSWORD     SMTP AUTH password / app password
    SMTP_FROM         From: header (defaults to SMTP_USER)
    NOTIFY_TO_EMAIL   Recipient inbox for agent check-ins

Set them with:

    templedb env secret set templedb SMTP_HOST      --value smtp.gmail.com
    templedb env secret set templedb SMTP_PORT      --value 587
    templedb env secret set templedb SMTP_USER      --value you@gmail.com
    templedb env secret set templedb SMTP_PASSWORD  --value <app-password>
    templedb env secret set templedb NOTIFY_TO_EMAIL --value you@gmail.com
"""
import os
import smtplib
import subprocess
from email.message import EmailMessage
from typing import Optional

from db_utils import query_one
from services.base import BaseService


REQUIRED_KEYS = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_TO_EMAIL")
DEFAULT_PROJECT_SLUG = "templedb"
DEFAULT_PROFILE = "default"


class EmailConfigError(RuntimeError):
    """Raised when SMTP config can't be read or decrypted."""


def _age_key_file() -> Optional[str]:
    """Return the first existing age identity file, or None.

    Non-interactive: no prompts, no fallback to yubikey/passphrase —
    those need a human. The scheduler / drain worker never has one.
    """
    candidates = [
        os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
        os.environ.get("SOPS_AGE_KEY_FILE"),
        os.path.expanduser("~/.config/sops/age/keys.txt"),
        os.path.expanduser("~/.age/key.txt"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _age_decrypt_noninteractive(encrypted: bytes) -> bytes:
    key_file = _age_key_file()
    if not key_file:
        raise EmailConfigError(
            "no age key file found — set TEMPLEDB_AGE_KEY_FILE or place "
            "an identity at ~/.config/sops/age/keys.txt so the drain "
            "worker can decrypt SMTP secrets without a prompt"
        )
    try:
        proc = subprocess.run(
            ["age", "-d", "-i", key_file],
            input=encrypted,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        raise EmailConfigError("`age` binary not on PATH")
    except subprocess.CalledProcessError as e:
        raise EmailConfigError(
            f"age decryption failed: {e.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


class EmailService(BaseService):
    """Send agent check-in emails via SMTP.

    Credentials live in the age-encrypted secret store; see module
    docstring for the expected key set.
    """

    def __init__(self,
                 project_slug: str = DEFAULT_PROJECT_SLUG,
                 profile: str = DEFAULT_PROFILE):
        super().__init__()
        self.project_slug = project_slug
        self.profile = profile
        self._config_cache: Optional[dict] = None

    def load_config(self) -> dict:
        """Return decrypted SMTP config dict. Cached per instance.

        Raises EmailConfigError if the project doesn't exist, required
        keys are missing, or decryption fails.
        """
        if self._config_cache is not None:
            return self._config_cache

        project = query_one(
            "SELECT id FROM projects WHERE slug = ?", (self.project_slug,)
        )
        if not project:
            raise EmailConfigError(
                f"project '{self.project_slug}' not found — "
                f"import it or override project_slug"
            )

        rows = self.query_all_secrets(project["id"], self.profile)
        missing = [k for k in REQUIRED_KEYS if k not in rows]
        if missing:
            raise EmailConfigError(
                f"missing SMTP secrets on {self.project_slug}/{self.profile}: "
                f"{', '.join(missing)}. See src/services/email_service.py "
                f"module docstring for the setup commands."
            )

        rows.setdefault("SMTP_PORT", "587")
        rows.setdefault("SMTP_FROM", rows["SMTP_USER"])
        self._config_cache = rows
        return rows

    def query_all_secrets(self, project_id: int, profile: str) -> dict:
        """Decrypt all text secrets for a project+profile."""
        from db_utils import query_all
        rows = query_all(
            """SELECT sb.secret_name, sb.secret_blob
                 FROM project_secret_blobs psb
                 JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
                WHERE psb.project_id = ? AND psb.profile = ?
                  AND sb.content_type = 'application/text'""",
            (project_id, profile),
        )
        out = {}
        for row in rows:
            try:
                out[row["secret_name"]] = _age_decrypt_noninteractive(
                    row["secret_blob"]
                ).decode("utf-8").rstrip("\n")
            except EmailConfigError:
                raise
        return out

    def send(self, subject: str, body_md: str,
             to: Optional[str] = None) -> None:
        """Synchronously send one email. Raises on failure."""
        cfg = self.load_config()
        recipient = to or cfg["NOTIFY_TO_EMAIL"]

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg["SMTP_FROM"]
        msg["To"] = recipient
        msg.set_content(body_md or "")

        port = int(cfg["SMTP_PORT"])
        host = cfg["SMTP_HOST"]

        # 465 = implicit TLS; anything else uses STARTTLS.
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
                s.send_message(msg)

        self.logger.info(f"sent email id={msg['Message-ID']!r} to={recipient}")

    def drain(self, limit: int = 50) -> dict:
        """Send all unsent rows. Returns {'sent': N, 'failed': M, 'errors': [...]}.

        Does not raise on individual send failures — records them on the
        row via mark_notification_send_failed and continues. Raises only
        on config errors that block everything (no key file, missing
        secrets), so a broken config surfaces on the first tick.
        """
        from agent import store as _store

        # Fail fast on config so the caller sees why nothing sent.
        self.load_config()

        rows = _store.list_notifications_to_send(limit=limit)
        sent = 0
        failed = 0
        errors = []
        for row in rows:
            try:
                self.send(row["subject"], row["body_md"])
                _store.mark_notification_sent(row["id"])
                sent += 1
            except Exception as e:
                _store.mark_notification_send_failed(row["id"], e)
                failed += 1
                errors.append({"id": row["id"], "error": str(e)})
                self.logger.error(f"email send failed id={row['id']}: {e}")
        return {"sent": sent, "failed": failed, "errors": errors}
