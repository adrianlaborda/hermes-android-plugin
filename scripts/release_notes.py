#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md as GitHub release notes.

GitHub renders every newline in release notes as a line break, so the changelog's hard-wrapped lines are joined back
into their paragraph or list item. Usage: release_notes.py VERSION [CHANGELOG]
"""
import re
import sys
from pathlib import Path

version = sys.argv[1]
changelog = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / 'CHANGELOG.md')
heading = re.compile(r'^## \[?' + re.escape(version) + r'[\] ]')
block_start = re.compile(r'^\s*(#|[-*] |\d+\. |```|>|\||$)')

lines, found = [], False
for line in changelog.read_text().splitlines():
    if heading.match(line):
        found = True
        continue
    if found and line.startswith('## '):
        break
    if found:
        lines.append(line.rstrip())
if not found:
    sys.exit(f'CHANGELOG.md has no section for {version}')

out = []
for line in lines:
    if out and out[-1] and not block_start.match(line):
        out[-1] += ' ' + line.strip()
    else:
        out.append(line)
print('\n'.join(out).strip())
