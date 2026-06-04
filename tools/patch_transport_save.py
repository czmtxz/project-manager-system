#!/usr/bin/env python3
"""Register the correct api_transport_save route and remove the broken duplicate."""
from pathlib import Path

APP = Path('/opt/project_manager/project_manager/app.py')
text = APP.read_text(encoding='utf-8')
APP.with_suffix('.py.bak_transport').write_text(text, encoding='utf-8')

lines = text.splitlines(keepends=True)
correct_idx = None
for i, line in enumerate(lines):
    if line.strip() != 'def api_transport_save():':
        continue
    if i + 1 < len(lines) and '按实际表结构动态写入' in lines[i + 1]:
        correct_idx = i
        break

if correct_idx is None:
    raise SystemExit('correct api_transport_save not found')

prev = ''.join(lines[max(0, correct_idx - 4):correct_idx])
if "@app.route('/api/transport/save'" not in prev:
    lines.insert(correct_idx, '@login_required\n')
    lines.insert(correct_idx, "@app.route('/api/transport/save', methods=['POST'])\n")

seen = 0
remove_start = remove_end = None
for i, line in enumerate(lines):
    if line.strip() != 'def api_transport_save():':
        continue
    seen += 1
    if seen != 2:
        continue
    start = i
    while start > 0 and lines[start - 1].lstrip().startswith('@'):
        start -= 1
    end = i + 1
    while end < len(lines) and not lines[end].startswith("if __name__ == '__main__':"):
        end += 1
    remove_start, remove_end = start, end
    break

if remove_start is None:
    raise SystemExit('duplicate api_transport_save not found')

del lines[remove_start:remove_end]
APP.write_text(''.join(lines), encoding='utf-8')
print('patched transport save route')
