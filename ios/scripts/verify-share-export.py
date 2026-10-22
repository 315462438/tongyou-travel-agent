#!/usr/bin/env python3
"""Verify the actual PNGs produced by --share-export-test (requires Pillow)."""
import argparse
import json
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
metrics = json.loads((args.directory / 'metrics.json').read_text())
assert sum(m['name'] == 'short' for m in metrics) == 1, 'Two-day plan should fit one card'
assert sum(m['name'] == 'long' for m in metrics) > 1, 'Long plan must paginate'
results = []
for item in metrics:
    path = args.directory / f"{item['name']}-{item['page']}.png"
    with Image.open(path).convert('RGB') as original:
        assert original.width == item['width'] == 1120
        assert original.height == item['height'] and 1000 < original.height < 4200
        sample = original.copy()
        sample.thumbnail((280, 1000))
        ink = sum(r < 160 and g < 170 and b < 185 for r, g, b in sample.getdata())
        fraction = ink / (sample.width * sample.height)
        assert fraction > .008, f'{path.name}: blank or missing text'
        results.append(dict(file=path.name, width=original.width, height=original.height, ink_fraction=round(fraction, 4)))
assert (args.directory / 'full.pdf').read_bytes().startswith(b'%PDF-'), 'Full PDF missing'
report = dict(passed=len(results), images=results, pdf=True)
text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
print(text)
