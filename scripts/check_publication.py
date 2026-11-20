"""Small publication guard, not a complete secret or privacy audit."""

from pathlib import Path
import re
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    problems = []
    patterns = [
        ("personal filesystem path", re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/")),
        ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
        ("GitHub credential", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
        ("credential-like literal", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}")),
    ]
    allowed_email = "189211877+CosmicWalter@users.noreply.github.com"
    for name in filter(None, tracked):
        p = root / name
        if name.startswith(("data/", "outputs/", ".venv/")) or name.endswith((".sqlite3", ".pem", ".key")) or name == "config.local.json" or p.name.startswith(".env"):
            problems.append((name, "private/runtime file tracked"))
            continue
        if p.is_symlink():
            problems.append((name, "symlink needs manual review"))
            continue
        if not p.exists():
            continue
        raw = p.read_bytes()
        if b"\0" in raw:
            problems.append((name, "binary artifact needs manual review"))
            continue
        text = raw.decode("utf-8", errors="replace")
        for label, pattern in patterns:
            if pattern.search(text):
                problems.append((name, label))
        for email in re.findall(r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
            if email != allowed_email:
                problems.append((name, "unapproved email-like identity"))
    # Check all outgoing history in this standalone pseudonymous repository.
    history = subprocess.run(["git", "log", "--all", "--format=%an%x00%ae%x00%cn%x00%ce"], cwd=root, capture_output=True, text=True)
    if history.returncode == 0:
        for line in history.stdout.splitlines():
            if line.split("\0") != ["CosmicWalter", allowed_email, "CosmicWalter", allowed_email]:
                problems.append(("history", "unapproved author/committer"))
    if problems:
        for name, label in problems:
            print(f"{name}: {label}", file=sys.stderr)
        return 1
    print(f"Publication guard passed for {len(list(filter(None, tracked)))} tracked text files; manual review still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
