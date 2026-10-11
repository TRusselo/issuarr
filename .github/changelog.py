#!/usr/bin/env python3
"""Draft CHANGELOG.md lines for commits that aren't in it yet.

    python3 .github/changelog.py [base] [head]

Lists the commits in head (default: HEAD) that aren't in base (default:
origin/main) and aren't already mentioned in CHANGELOG.md, one bullet each,
with the commit id linked. Rewrite each bullet in plain English, merge
related ones, and add them under "Unreleased (on dev)".
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_URL = 'https://github.com/issuarr/issuarr'
ROOT = Path(__file__).resolve().parent.parent


def link(sha):
    return '[`%s`](%s/commit/%s)' % (sha, REPO_URL, sha)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'origin/main'
    head = sys.argv[2] if len(sys.argv) > 2 else 'HEAD'
    log = subprocess.run(['git', 'log', '--reverse', '--no-merges', '--abbrev=7', '--format=%h %s', '%s..%s' % (base, head)],
                         cwd=ROOT, check=True, capture_output=True, text=True).stdout
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    listed = set(re.findall(r'\b[0-9a-f]{7}\b', changelog))
    for line in log.splitlines():
        sha, subject = line.split(' ', 1)
        if sha[:7] in listed:
            continue
        subject = re.sub(r'^\w+(\([^)]*\))?!?:\s*', '', subject)  # drop the Conventional Commits prefix
        print('- %s%s. (%s)' % (subject[:1].upper(), subject[1:].rstrip('.'), link(sha)))


if __name__ == '__main__':
    main()
