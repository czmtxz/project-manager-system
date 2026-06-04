from app import app
rules = sorted(r.rule + ' ' + ','.join(sorted(r.methods - {'HEAD', 'OPTIONS'}))
               for r in app.url_map.iter_rules() if 'transport' in r.rule)
for r in rules:
    print(r)
