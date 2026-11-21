"""Publish only the website tree to gh-pages, as the verified pseudonymous owner."""

from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import subprocess
import tempfile

from check_website import check, FILES, ROOT
from check_publication import main as privacy_check

OWNER = "CosmicWalter"
EMAIL = "189211877+CosmicWalter@users.noreply.github.com"
REMOTE = "https://github.com/CosmicWalter/creator-loom.git"
TRANSPORT = ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]


def run(args, env=None, data=None, optional=False):
    result = subprocess.run(args, cwd=ROOT, env=env, input=data, capture_output=True, text=True)
    if result.returncode and not optional:
        raise ValueError("Publication command failed; inspect authentication or concurrent branch updates privately")
    return result.stdout.strip(), result.returncode


def identity():
    user, _ = run(["gh", "api", "user", "--jq", ".login"])
    if user != OWNER:
        raise ValueError("GitHub transport is not CosmicWalter; publication stopped")
    remote, _ = run(["git", "remote", "get-url", "--push", "--all", "origin"])
    if remote != REMOTE:
        raise ValueError("Unexpected push destination; publication stopped")
    _, code = run(["git", "config", "--get-regexp", r"^(http\..*extraheader|http\.extraheader|url\..*insteadof|url\..*pushinsteadof)$"], optional=True)
    if code != 1:
        raise ValueError("Transport overrides require private inspection")


def publish(live=False):
    check()
    if privacy_check():
        raise ValueError("Publication privacy guard failed")
    identity()
    if not live:
        print("Ready to publish the five allowlisted website files as CosmicWalter. Use --publish to update gh-pages.")
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S +0000")
    env = dict(os.environ, GIT_AUTHOR_NAME=OWNER, GIT_AUTHOR_EMAIL=EMAIL, GIT_COMMITTER_NAME=OWNER,
               GIT_COMMITTER_EMAIL=EMAIL, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp, GIT_TERMINAL_PROMPT="0")
    head, _ = run(TRANSPORT+["ls-remote", "origin", "refs/heads/gh-pages"], env)
    parent = None
    if head:
        run(TRANSPORT+["fetch", "--no-tags", "origin", "refs/heads/gh-pages"], env)
        parent, _ = run(["git", "rev-parse", "FETCH_HEAD"], env)
        identities, _ = run(["git", "log", parent, "--format=%an%x00%ae%x00%cn%x00%ce"], env)
        if any(line.split("\0") != [OWNER, EMAIL, OWNER, EMAIL] for line in identities.splitlines()):
            raise ValueError("Existing gh-pages history has another identity; inspect before changing it")
    with tempfile.TemporaryDirectory(prefix="loom-pages-") as temporary:
        env["GIT_INDEX_FILE"] = str(Path(temporary)/"index")
        run(["git", "read-tree", "--empty"], env)
        for filename in sorted(FILES):
            blob, _ = run(["git", "hash-object", "-w", "--no-filters", "website/"+filename], env)
            run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{filename}"], env)
        tree, _ = run(["git", "write-tree"], env)
        if parent:
            prior, _ = run(["git", "rev-parse", parent+"^{tree}"], env)
            if prior == tree:
                print("The gh-pages website already matches the reviewed source.")
                return
        args = ["git", "-c", "commit.gpgsign=false", "commit-tree", tree]
        if parent:
            args += ["-p", parent]
        commit, _ = run(args, env, "docs: publish the Creator Loom website\n")
        metadata, _ = run(["git", "show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%G?", commit], env)
        if metadata.splitlines() != [OWNER, EMAIL, OWNER, EMAIL, "N"]:
            raise ValueError("Unexpected generated commit identity or signature")
        # Verify the same gh session immediately before the actual write.
        identity()
        run(TRANSPORT+["push", "origin", commit+":refs/heads/gh-pages"], env)
        print("Published website commit "+commit+" to gh-pages without force-pushing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    try:
        publish(args.publish)
    except (OSError, ValueError) as exc:
        print(str(exc))
        raise SystemExit(1)
