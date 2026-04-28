import re, os

for fn in sorted(os.listdir('app/templates')):
    if not fn.endswith('.html'):
        continue
    path = os.path.join('app/templates', fn)
    with open(path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if re.search(r'[\uAC00-\uD7AF]', line):
                # Extract just the Korean parts
                korean_parts = re.findall(r'[\uAC00-\uD7AF\s\w.,!?:;(){}=\-_\'\"]+', line)
                with open('korean_results.txt', 'a', encoding='utf-8') as out:
                    out.write(f"{fn}:{i}: {line.rstrip()}\n")
