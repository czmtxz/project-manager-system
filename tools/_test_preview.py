# -*- coding: utf-8 -*-
import re
import requests

s = requests.Session()
s.post('http://127.0.0.1:5002/login', data={'username': 'admin', 'password': 'admin123'})
p = r'\\DESKTOP-VMPGRAC\download\PPT\虎子   泽永(8).xlsx'
with open(p, 'rb') as f:
    r = s.post('http://127.0.0.1:5002/admin/client-company/1/excel-preview',
               files={'excel_file': ('t.xlsx', f,
                      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
               data={'split_orders': '1'}, allow_redirects=False)
print('preview status', r.status_code)
html = r.text if r.status_code == 200 else ''
print('has selection page:', '选择要导入的页签' in html)
print('sheet checkbox count:', len(re.findall(r'name="sheets"', html)))
print('has confirm action:', 'excel-import-confirm' in html)
if r.status_code != 200:
    print('redirect ->', r.headers.get('Location'))
