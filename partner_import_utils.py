# -*- coding: utf-8 -*-
"""客户/供应商：图片识别与 Excel 批量导入"""

import os
import re
from datetime import datetime


# Excel 列名映射（中英文别名）
COLUMN_ALIASES = {
    'name': ('名称', 'name', '供应商名称', '客户名称', '单位名称', '公司名称', '企业名称'),
    'contact': ('联系人', 'contact', '联系人姓名'),
    'phone': ('电话', 'phone', '手机', '联系电话', '手机号'),
    'email': ('邮箱', 'email', '电子邮件'),
    'address': ('地址', 'address', '单位地址', '注册地址'),
    'delivery_address': ('送货地址', 'delivery_address', '收货地址'),
    'bank_name': ('开户银行', 'bank_name', '银行', '开户行'),
    'bank_account': ('银行账号', 'bank_account', '账号', '帐户', '账户'),
    'bank_code': ('联行号', 'bank_code', '行号'),
    'tax_no': ('税号', 'tax_no', '纳税人识别号', '统一社会信用代码', '信用代码'),
    'invoice_title': ('发票抬头', 'invoice_title', '抬头'),
    'invoice_addr_phone': ('发票地址电话', 'invoice_addr_phone'),
    'invoice_bank_account': ('发票开户行账号', 'invoice_bank_account'),
    'tax_rate': ('税率', 'tax_rate'),
    'remark': ('备注', 'remark'),
}


def _ocr_lines(image_path):
    """OCR 识别为行文本，优先 rapidocr，回退 easyocr / paddle"""
    try:
        from ocr_utils import ocr_image_to_lines
        return ocr_image_to_lines(image_path)
    except Exception:
        pass
    try:
        import easyocr
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
        result = reader.readtext(image_path, detail=1)
        sorted_result = sorted(result, key=lambda x: (round(x[0][0][1] / 20) * 20, x[0][0][0]))
        return [item[1] for item in sorted_result if item[2] > 0.3]
    except Exception:
        pass
    return []


def recognize_company_info(image_path, role='supplier'):
    """
    从名片、营业执照、增值税发票等识别企业信息
    role: supplier 时优先取销方；customer 时优先取购方
    """
    lines = _ocr_lines(image_path)
    full_text = '\n'.join(lines) if lines else ''

    if not full_text.strip():
        return {'error': '未能识别到文字，请换更清晰的图片或安装 OCR 组件'}

    info = {
        'name': '',
        'contact': '',
        'phone': '',
        'email': '',
        'address': '',
        'delivery_address': '',
        'bank_name': '',
        'bank_account': '',
        'bank_code': '',
        'tax_no': '',
        'invoice_title': '',
        'invoice_addr_phone': '',
        'invoice_bank_account': '',
        'tax_rate': 0,
        'remark': '',
        'raw_text': full_text,
    }

    # 税号 / 统一社会信用代码
    for pat in [
        r'(?:统一社会信用代码|纳税人识别号|税\s*号)[：:\s]*([0-9A-Z]{15,20})',
        r'([0-9A-Z]{18})',
    ]:
        m = re.search(pat, full_text)
        if m:
            info['tax_no'] = m.group(1).strip()
            break

    # 企业名称
    for pat in [
        r'(?:名\s*称|企业名称|公司名称|单位名称)[：:\s]*([^\n]{2,60})',
        r'(?:名\s*称)[：:\s]*([^\n]+有限公司[^\n]*)',
    ]:
        m = re.search(pat, full_text)
        if m:
            name = m.group(1).strip()
            if len(name) >= 2 and '发票' not in name:
                info['name'] = name
                info['invoice_title'] = name
                break

    # 电话
    phones = re.findall(r'1[3-9]\d{9}|0\d{2,3}-?\d{7,8}', full_text)
    if phones:
        info['phone'] = phones[0]

    # 邮箱
    em = re.search(r'[\w.\-]+@[\w.\-]+\.\w+', full_text)
    if em:
        info['email'] = em.group(0)

    # 地址
    for pat in [
        r'(?:地\s*址|住所|注册地址)[：:\s]*([^\n]{6,80})',
    ]:
        m = re.search(pat, full_text)
        if m:
            info['address'] = m.group(1).strip()[:120]
            break

    # 开户行 / 账号
    bank_m = re.search(r'(?:开户银行|开户行|银行名称)[：:\s]*([^\n]{4,40})', full_text)
    if bank_m:
        info['bank_name'] = bank_m.group(1).strip()
    acc_m = re.search(r'(?:银行账号|账\s*号)[：:\s]*([0-9\s]{8,30})', full_text)
    if acc_m:
        info['bank_account'] = re.sub(r'\s', '', acc_m.group(1))

    # 联系人
    contact_m = re.search(r'(?:联系人|联\s*系\s*人)[：:\s]*([^\s\n]{2,10})', full_text)
    if contact_m:
        info['contact'] = contact_m.group(1).strip()

    # 增值税发票补充
    try:
        from ocr_utils import recognize_invoice
        inv = recognize_invoice(image_path)
        party = inv.get('seller') if role == 'supplier' else inv.get('buyer')
        if not party and role == 'customer':
            party = inv.get('buyer')
        if not party and role == 'supplier':
            party = inv.get('seller')
        if party and len(party) >= 2:
            info['name'] = info['name'] or party.strip()
            info['invoice_title'] = info['invoice_title'] or party.strip()
        if inv.get('tax_rate'):
            info['tax_rate'] = inv['tax_rate']
    except Exception:
        pass

    if not info['name']:
        # 尝试匹配“XX有限公司”
        m = re.search(r'([\u4e00-\u9fa5（）()]{2,40}(?:有限公司|有限责任公司|股份公司|集团公司))', full_text)
        if m:
            info['name'] = m.group(1).strip()
            info['invoice_title'] = info['name']

    if not info['name']:
        return {'error': '未识别到单位名称，请确认图片包含发票抬头或营业执照', 'raw_text': full_text[:500]}

    return info


def normalize_excel_row(row):
    """将 Excel 一行 dict 转为标准字段"""
    if not isinstance(row, dict):
        return None
    # 统一 key 去空格
    normalized_keys = {}
    for k, v in row.items():
        if k is None:
            continue
        key = str(k).strip()
        normalized_keys[key] = v

    out = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized_keys:
                val = normalized_keys[alias]
                if val is not None and str(val).strip() not in ('', 'nan', 'None'):
                    out[field] = str(val).strip() if field != 'tax_rate' else val
                break
    if 'name' not in out or not str(out.get('name', '')).strip():
        return None
    if 'tax_rate' in out:
        try:
            out['tax_rate'] = float(out['tax_rate'])
        except (TypeError, ValueError):
            out['tax_rate'] = 0
    else:
        out['tax_rate'] = 0
    return out


def parse_partner_excel(file_path):
    """解析 Excel，返回标准记录列表"""
    try:
        import pandas as pd
        df = pd.read_excel(file_path)
        df = df.where(pd.notnull(df), None)
        records = []
        for row in df.to_dict('records'):
            parsed = normalize_excel_row(row)
            if parsed:
                records.append(parsed)
        return records, None
    except Exception as e:
        return [], str(e)


def save_partner_record(db, table, data, update_existing=False):
    """
    保存一条客户或供应商
    table: 'suppliers' | 'customers'
    返回: created | updated | skipped
    """
    name = data.get('name', '').strip()
    if not name:
        return 'skipped'

    existing = db.execute(f"SELECT * FROM {table} WHERE name=? AND is_active=1", (name,)).fetchone()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    fields = (
        'name', 'contact', 'phone', 'email', 'address', 'delivery_address',
        'bank_name', 'bank_account', 'bank_code', 'tax_no', 'invoice_title',
        'invoice_addr_phone', 'invoice_bank_account', 'tax_rate', 'remark'
    )

    if existing:
        if not update_existing:
            return 'skipped'
        sets = []
        vals = []
        for f in fields:
            if f == 'name':
                continue
            val = data.get(f)
            if val is not None and str(val).strip() != '':
                sets.append(f"{f}=?")
                vals.append(float(val or 0) if f == 'tax_rate' else val)
        if not sets:
            return 'skipped'
        vals.append(existing['id'])
        db.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
        return 'updated'

    vals = []
    for f in fields:
        if f == 'tax_rate':
            vals.append(float(data.get('tax_rate') or 0))
        else:
            vals.append(data.get(f, '') or '')
    vals.extend([now, 1])
    placeholders = ','.join(['?'] * len(vals))
    cols = ','.join(fields) + ',created_at,is_active'
    db.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
        vals
    )
    return 'created'
