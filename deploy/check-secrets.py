from pathlib import Path
import re
import sys

# Focused guard: reports paths only, never matched credential values.
pattern = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
bad = []
for root in [Path('src'), Path('public')]:
    if root.exists():
        for path in root.rglob('*'):
            if path.suffix in {'.vue', '.js', '.ts', '.json', '.html'} and path.is_file():
                if pattern.search(path.read_text(errors='ignore')):
                    bad.append(str(path))
if bad:
    print('Embedded provider credential found in: ' + ', '.join(bad), file=sys.stderr)
    sys.exit(1)
