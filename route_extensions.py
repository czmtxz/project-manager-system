# -*- coding: utf-8 -*-
"""补全模板引用但 app.py 中缺失的路由与工具函数"""


def get_category_usage_map(db):
    rows = db.execute("""
        SELECT category_id, COUNT(*) as cnt
        FROM transaction_records
        WHERE category_id IS NOT NULL
        GROUP BY category_id
    """).fetchall()
    return {r['category_id']: r['cnt'] for r in rows}


def _enrich_category_nodes(nodes, usage_map):
    for n in nodes:
        n['usage_count'] = usage_map.get(n['id'], 0)
        n['is_leaf'] = len(n['children']) == 0
        if n['children']:
            _enrich_category_nodes(n['children'], usage_map)


def build_category_manage_trees(db):
    """费用分类标准库：按 parent_id 构建收入/支出三级树"""
    cats = db.execute(
        "SELECT id, code, name, type, level, parent_id, sort_order, description "
        "FROM categories ORDER BY COALESCE(sort_order, 0), code, id"
    ).fetchall()
    usage_map = get_category_usage_map(db)
    nodes = {}
    all_categories = []
    for c in cats:
        desc = ''
        if 'description' in c.keys() and c['description']:
            desc = c['description']
        row = {
            'id': c['id'],
            'code': c['code'] or '',
            'name': c['name'],
            'type': c['type'],
            'level': c['level'] or 1,
            'parent_id': c['parent_id'],
            'sort_order': c['sort_order'] or 0,
            'description': desc,
            'children': [],
        }
        nodes[c['id']] = row
        all_categories.append({
            'id': c['id'],
            'code': c['code'] or '',
            'name': c['name'],
            'type': c['type'],
            'level': c['level'] or 1,
            'parent_id': c['parent_id'],
        })

    expense_tree, income_tree = [], []
    for n in nodes.values():
        pid = n['parent_id']
        if pid and pid in nodes:
            nodes[pid]['children'].append(n)
        elif n['type'] == 'income':
            income_tree.append(n)
        else:
            expense_tree.append(n)
    _enrich_category_nodes(expense_tree, usage_map)
    _enrich_category_nodes(income_tree, usage_map)
    return expense_tree, income_tree, all_categories, usage_map


def build_category_tree(db, project_id=None, date_from=None, date_to=None):
    """构建三级分类树（报表页使用）"""
    q = """SELECT category_id, COALESCE(SUM(amount),0) as total, COUNT(*) as count
           FROM transaction_records WHERE category_id IS NOT NULL"""
    params = []
    if project_id:
        q += " AND project_id=?"
        params.append(project_id)
    if date_from:
        q += " AND trans_date>=?"
        params.append(date_from)
    if date_to:
        q += " AND trans_date<=?"
        params.append(date_to)
    q += " GROUP BY category_id"
    stats = {r['category_id']: {'total': r['total'], 'count': r['count']}
             for r in db.execute(q, params).fetchall()}

    cats = db.execute(
        "SELECT * FROM categories ORDER BY COALESCE(sort_order,0), id"
    ).fetchall()
    nodes = {}
    for c in cats:
        st = stats.get(c['id'], {'total': 0, 'count': 0})
        nodes[c['id']] = {
            'id': c['id'], 'name': c['name'], 'type': c['type'],
            'parent_id': c['parent_id'] if 'parent_id' in c.keys() else None,
            'total': st['total'], 'count': st['count'], 'children': []
        }

    roots_expense, roots_income = [], []
    for n in nodes.values():
        pid = n['parent_id']
        if pid and pid in nodes:
            nodes[pid]['children'].append(n)
        elif n['type'] == 'income':
            roots_income.append(n)
        else:
            roots_expense.append(n)

    def rollup(node):
        for ch in node['children']:
            rollup(ch)
            node['total'] += ch['total']
            node['count'] += ch['count']

    for r in roots_expense + roots_income:
        rollup(r)
    return {'expense': roots_expense, 'income': roots_income}


def register_missing_routes(app, ctx):
    login_required = ctx['login_required']
    admin_required = ctx['admin_required']
    get_db = ctx['get_db']
    add_log = ctx['add_log']
    datetime = ctx['datetime']
    redirect = ctx['redirect']
    url_for = ctx['url_for']
    render_template = ctx['render_template']
    request = ctx['request']
    session = ctx['session']
    flash = ctx['flash']
    send_from_directory = ctx['send_from_directory']
    os = ctx['os']
    uuid = ctx['uuid']
    app_config = app.config

    # ---------- 参与人 ----------
    @app.route('/participant/<int:pid>')
    @login_required
    def participant_detail(pid):
        db = get_db()
        p = db.execute("SELECT p.*, u.username as linked_username FROM participants p "
                       "LEFT JOIN users u ON p.user_id = u.id WHERE p.id=?", (pid,)).fetchone()
        if not p:
            flash('参与人不存在', 'danger')
            return redirect(url_for('participant_list'))
        projects = db.execute("""
            SELECT pp.*, pr.name as project_name, pr.status as project_status
            FROM project_participants pp
            JOIN projects pr ON pp.project_id = pr.id
            WHERE pp.participant_id=? ORDER BY pr.name
        """, (pid,)).fetchall()
        transactions = db.execute("""
            SELECT t.*, pr.name as project_name FROM transaction_records t
            LEFT JOIN projects pr ON t.project_id = pr.id
            WHERE t.participant_id=? ORDER BY t.trans_date DESC LIMIT 20
        """, (pid,)).fetchall()
        stats = {
            'project_count': len(projects),
            'total_investment': db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM investments WHERE participant_id=?", (pid,)
            ).fetchone()[0],
            'total_expense': db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transaction_records "
                "WHERE participant_id=? AND trans_type='expense'", (pid,)
            ).fetchone()[0],
            'total_income': db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transaction_records "
                "WHERE participant_id=? AND trans_type='income'", (pid,)
            ).fetchone()[0],
        }
        all_projects = db.execute(
            "SELECT id, name FROM projects ORDER BY name"
        ).fetchall()
        return render_template('participant_detail.html', participant=p, projects=projects,
                               transactions=transactions, stats=stats, all_projects=all_projects)

    @app.route('/participant/<int:pid>/edit', methods=['GET', 'POST'])
    @login_required
    def participant_edit(pid):
        db = get_db()
        p = db.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
        if not p:
            flash('参与人不存在', 'danger')
            return redirect(url_for('participant_list'))
        if request.method == 'POST':
            db.execute("UPDATE participants SET name=?, phone=?, role=?, remark=? WHERE id=?",
                       (request.form.get('name', '').strip(), request.form.get('phone', ''),
                        request.form.get('role', 'member'), request.form.get('remark', ''), pid))
            db.commit()
            flash('参与人已更新', 'success')
            return redirect(url_for('participant_detail', pid=pid))
        return render_template('participant_form.html', participant=p, edit_mode=True)

    @app.route('/participant/<int:pid>/delete')
    @login_required
    def participant_delete(pid):
        db = get_db()
        db.execute("DELETE FROM project_participants WHERE participant_id=?", (pid,))
        db.execute("DELETE FROM participants WHERE id=?", (pid,))
        db.commit()
        flash('参与人已删除', 'success')
        return redirect(url_for('participant_list'))

    # ---------- 分类 ----------
    @app.route('/category/<int:category_id>/transactions')
    @login_required
    def category_transactions(category_id):
        db = get_db()
        category = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        if not category:
            flash('分类不存在', 'danger')
            return redirect(url_for('reports.hub'))
        project_id = request.args.get('project_id', '')
        sql = """SELECT t.*, p.name as project_name FROM transaction_records t
                 LEFT JOIN projects p ON t.project_id = p.id WHERE t.category_id=?"""
        params = [category_id]
        if project_id:
            sql += " AND t.project_id=?"
            params.append(project_id)
        sql += " ORDER BY t.trans_date DESC"
        transactions = db.execute(sql, params).fetchall()
        total_income = sum(t['amount'] for t in transactions if t['trans_type'] == 'income')
        total_expense = sum(t['amount'] for t in transactions if t['trans_type'] == 'expense')
        projects = db.execute("SELECT id, name FROM projects ORDER BY name").fetchall()
        return render_template('category_transactions.html', category=category,
                               transactions=transactions, total_income=total_income,
                               total_expense=total_expense, project_id=project_id,
                               projects=projects)

    @app.route('/category/delete/<int:id>')
    @login_required
    def category_delete(id):
        db = get_db()
        cat = db.execute("SELECT * FROM categories WHERE id=?", (id,)).fetchone()
        if not cat:
            flash('科目不存在', 'danger')
            return redirect(url_for('category_list'))
        child = db.execute(
            "SELECT 1 FROM categories WHERE parent_id=? LIMIT 1", (id,)
        ).fetchone()
        if child:
            flash('该科目下有下级科目，请先删除或移动子科目', 'warning')
            return redirect(url_for('category_list'))
        usage = db.execute(
            "SELECT COUNT(*) FROM transaction_records WHERE category_id=?", (id,)
        ).fetchone()[0]
        if usage > 0:
            flash(f'该科目已被 {usage} 笔费用引用，无法删除', 'warning')
            return redirect(url_for('category_list'))
        db.execute("DELETE FROM project_categories WHERE category_id=?", (id,))
        db.execute("DELETE FROM categories WHERE id=?", (id,))
        db.commit()
        flash('费用分类已删除', 'success')
        return redirect(url_for('category_list'))

    # ---------- 合同扩展 ----------
    @app.route('/contract/import', methods=['GET', 'POST'])
    @login_required
    def contract_import():
        if request.method == 'POST':
            flash('合同导入功能开发中，请手动新增', 'info')
            return redirect(url_for('contract_list'))
        return render_template('contract_import.html')

    @app.route('/contract/<int:id>/submit')
    @login_required
    def contract_submit(id):
        db = get_db()
        db.execute("UPDATE contracts SET status='审批中', approval_status='pending' WHERE id=?", (id,))
        db.commit()
        flash('合同已提交审批', 'success')
        return redirect(url_for('contract_list'))

    @app.route('/contract/<int:id>/complete')
    @login_required
    def contract_complete(id):
        db = get_db()
        db.execute("UPDATE contracts SET status='已完成' WHERE id=?", (id,))
        db.commit()
        flash('合同已标记完成', 'success')
        return redirect(url_for('contract_list'))

    @app.route('/contract/<int:id>/terminate')
    @login_required
    def contract_terminate(id):
        db = get_db()
        db.execute("UPDATE contracts SET status='已终止' WHERE id=?", (id,))
        db.commit()
        flash('合同已终止', 'success')
        return redirect(url_for('contract_list'))

    @app.route('/contract/docx/import', methods=['GET', 'POST'])
    @login_required
    def contract_docx_import():
        if request.method == 'POST':
            flash('Word导入功能开发中', 'info')
        return render_template('contract_docx_import.html')

    @app.route('/contract/docx/save', methods=['POST'])
    @login_required
    def contract_docx_save():
        flash('保存成功', 'success')
        return redirect(url_for('contract_list'))

    # ---------- 发票扩展 ----------
    @app.route('/invoice/import', methods=['GET', 'POST'])
    @login_required
    def invoice_import():
        if request.method == 'POST':
            flash('发票导入功能开发中，请手动新增', 'info')
            return redirect(url_for('invoice_list'))
        return render_template('invoice_import.html')

    @app.route('/invoice/ocr-import', methods=['GET', 'POST'])
    @login_required
    def invoice_ocr_import():
        db = get_db()
        projects = db.execute("SELECT id, name FROM projects ORDER BY name").fetchall()
        project_id = request.form.get('project_id', type=int) or request.args.get('project_id', type=int)
        results = []
        if request.method == 'POST':
            files = request.files.getlist('ocr_image')
            upload_dir = os.path.join(app_config['UPLOAD_FOLDER'], 'invoices')
            os.makedirs(upload_dir, exist_ok=True)
            for f in files:
                if not f or not f.filename:
                    continue
                ext = os.path.splitext(f.filename)[1]
                filename = f'invoice_{uuid.uuid4().hex[:8]}{ext}'
                saved_path = os.path.join(upload_dir, filename)
                f.save(saved_path)
                try:
                    from ocr_utils import recognize_invoice
                    data = recognize_invoice(saved_path)
                    amount = float(data.get('total_amount') or data.get('amount') or 0)
                    invoice_no = data.get('invoice_no') or ''
                    result = {
                        **data,
                        'filename': f.filename,
                        'saved': False,
                        'attachment': filename,
                    }
                    if invoice_no and amount > 0:
                        db.execute("""
                            INSERT INTO invoices (
                                project_id, invoice_no, invoice_type, amount, tax_rate,
                                tax_amount, invoice_date, status, attachment, remark,
                                created_by, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'received', ?, ?, ?, ?)
                        """, (
                            project_id,
                            invoice_no,
                            data.get('invoice_type') or 'cost',
                            amount,
                            float(data.get('tax_rate') or 0),
                            float(data.get('tax_amount') or 0),
                            data.get('invoice_date') or None,
                            filename,
                            'OCR识别导入',
                            session.get('user_id'),
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        ))
                        db.commit()
                        result['saved'] = True
                    results.append(result)
                except Exception as e:
                    results.append({'filename': f.filename, 'error': str(e), 'saved': False})
            if results:
                flash(f'已处理 {len(results)} 张发票图片', 'success')
            else:
                flash('请先选择发票图片', 'warning')
        return render_template(
            'invoice_ocr_import.html',
            projects=projects,
            project_id=project_id,
            results=results,
        )

    @app.route('/invoice/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def invoice_edit(id):
        db = get_db()
        invoice = db.execute("SELECT * FROM invoices WHERE id=?", (id,)).fetchone()
        if not invoice:
            flash('发票不存在', 'danger')
            return redirect(url_for('invoice_list'))
        if request.method == 'POST':
            db.execute("""UPDATE invoices SET project_id=?, contract_id=?, invoice_no=?,
                          invoice_type=?, amount=?, tax_rate=?, tax_amount=?, remark=? WHERE id=?""",
                       (request.form.get('project_id', type=int),
                        request.form.get('contract_id', type=int) or None,
                        request.form.get('invoice_no', ''),
                        request.form.get('invoice_type', ''),
                        request.form.get('amount', type=float) or 0,
                        request.form.get('tax_rate', type=float) or 0,
                        request.form.get('tax_amount', type=float) or 0,
                        request.form.get('remark', ''), id))
            db.commit()
            flash('发票已更新', 'success')
            return redirect(url_for('invoice_list'))
        projects = db.execute("SELECT id, name FROM projects ORDER BY name").fetchall()
        contracts = db.execute("SELECT id, contract_name FROM contracts ORDER BY contract_name").fetchall()
        return render_template('invoice_form.html', invoice=invoice, projects=projects,
                               contracts=contracts, edit_mode=True)

    @app.route('/invoice/<int:id>/approve', methods=['GET', 'POST'])
    @login_required
    def invoice_approve(id):
        db = get_db()
        db.execute("UPDATE invoices SET status='verified' WHERE id=?", (id,))
        db.commit()
        flash('发票已审核', 'success')
        return redirect(url_for('invoice_list'))

    @app.route('/invoice/<int:id>/delete', methods=['POST'])
    @login_required
    def invoice_delete(id):
        db = get_db()
        row = db.execute("SELECT invoice_no FROM invoices WHERE id=?", (id,)).fetchone()
        if not row:
            flash('发票不存在', 'danger')
            return redirect(url_for('invoice_list'))
        db.execute("DELETE FROM invoices WHERE id=?", (id,))
        db.commit()
        add_log(session.get('user_id'), session.get('username', ''), '删除发票', f'发票号: {row["invoice_no"] or id}')
        flash('发票已删除', 'success')
        return redirect(url_for('invoice_list'))

    # ---------- 采购扩展 ----------
    @app.route('/purchase/<int:id>/submit')
    @login_required
    def purchase_submit(id):
        db = get_db()
        db.execute("UPDATE purchase_orders SET status='已提交' WHERE id=?", (id,))
        db.commit()
        flash('采购单已提交', 'success')
        return redirect(url_for('purchase_detail', id=id))

    # ---------- 对账扩展 ----------
    @app.route('/reconciliation/create/<int:purchase_id>')
    @login_required
    def reconciliation_create(purchase_id):
        db = get_db()
        purchase = db.execute('SELECT * FROM purchase_orders WHERE id=?', (purchase_id,)).fetchone()
        if not purchase:
            flash('采购单不存在', 'danger')
            return redirect(url_for('reconciliation_list'))

        existing = db.execute(
            'SELECT id FROM reconciliations WHERE purchase_id=?', (purchase_id,)
        ).fetchone()
        if existing:
            flash('该采购单已有对账记录', 'info')
            return redirect(url_for('reconciliation_detail', id=existing['id']))

        items = db.execute(
            'SELECT * FROM purchase_items WHERE purchase_id=?', (purchase_id,)
        ).fetchall()
        total_purchase_qty = sum(float(i['quantity'] or 0) for i in items)

        tr_cols = {r[1] for r in db.execute('PRAGMA table_info(transport_records)').fetchall()}
        if 'purchase_id' in tr_cols:
            transports = db.execute(
                'SELECT * FROM transport_records WHERE purchase_id=?', (purchase_id,)
            ).fetchall()
        else:
            transports = db.execute("""
                SELECT DISTINCT tr.*
                FROM transport_records tr
                JOIN transport_purchase_items tpi ON tr.id = tpi.transport_id
                JOIN purchase_items pi ON tpi.purchase_item_id = pi.id
                WHERE pi.purchase_id = ?
            """, (purchase_id,)).fetchall()

        if not transports:
            flash('请先录入运输记录后再对账', 'warning')
            return redirect(url_for('purchase_detail', id=purchase_id))

        total_transport_qty = sum(float(t['quantity'] or 0) for t in transports)
        total_freight = sum(float(t['freight_amount'] or 0) for t in transports)

        invoice_ids = [t['invoice_id'] for t in transports if t['invoice_id']]
        total_invoice_amount = 0.0
        if invoice_ids:
            ph = ','.join('?' * len(invoice_ids))
            inv_row = db.execute(
                f'SELECT COALESCE(SUM(amount), 0) as s FROM invoices WHERE id IN ({ph})',
                invoice_ids,
            ).fetchone()
            total_invoice_amount = float(inv_row['s'] or 0)

        qty_diff = total_transport_qty - total_purchase_qty
        qty_diff_rate = (qty_diff / total_purchase_qty * 100) if total_purchase_qty > 0 else 0
        freight_diff = total_freight - total_invoice_amount
        po_keys = set(purchase.keys()) if hasattr(purchase, 'keys') else set()
        allowed_loss_rate = float(purchase['loss_rate']) if 'loss_rate' in po_keys and purchase['loss_rate'] is not None else 0.5

        if abs(qty_diff_rate) <= allowed_loss_rate and abs(freight_diff) < 0.01:
            status = 'matched'
        elif abs(qty_diff_rate) > allowed_loss_rate:
            status = 'discrepancy'
        else:
            status = 'pending'

        count = db.execute('SELECT COUNT(*) as c FROM reconciliations').fetchone()['c']
        recon_no = f'RC{datetime.now().strftime("%Y%m%d")}{str(count + 1).zfill(4)}'
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute("""
            INSERT INTO reconciliations (
                purchase_id, reconciliation_no, reconciliation_date,
                purchase_quantity, total_transport_qty, qty_diff, qty_diff_rate,
                allowed_loss_rate, total_freight, total_invoice_amount, freight_diff,
                status, reconciler_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            purchase_id, recon_no, datetime.now().strftime('%Y-%m-%d'),
            total_purchase_qty, total_transport_qty, qty_diff, qty_diff_rate,
            allowed_loss_rate, total_freight, total_invoice_amount, freight_diff,
            status, session.get('user_id'), now,
        ))
        db.commit()
        recon_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        flash('对账单已生成', 'success')
        return redirect(url_for('reconciliation_detail', id=recon_id))

    @app.route('/reconciliation/<int:id>/confirm', methods=['POST'])
    @login_required
    def reconciliation_confirm(id):
        db = get_db()
        db.execute(
            """UPDATE reconciliations
               SET status='confirmed', confirmed_by=?, confirmed_at=?
               WHERE id=?""",
            (session.get('user_id'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), id),
        )
        db.commit()
        flash('对账已确认', 'success')
        return redirect(url_for('reconciliation_detail', id=id))

    @app.route('/reconciliation/<int:id>/unconfirm', methods=['POST'])
    @login_required
    @admin_required
    def reconciliation_unconfirm(id):
        db = get_db()
        recon = db.execute("SELECT * FROM reconciliations WHERE id=?", (id,)).fetchone()
        if not recon:
            flash('对账单不存在', 'danger')
            return redirect(url_for('reconciliation_list'))
        if recon['status'] != 'confirmed':
            flash('该对账单不是已确认状态，无需反确认', 'warning')
            return redirect(url_for('reconciliation_detail', id=id))

        # 反确认后按差异重新判定状态
        recon_keys = recon.keys()
        qty_diff_rate = abs(float(recon['qty_diff_rate'] or 0)) if 'qty_diff_rate' in recon_keys else 0
        allowed = float(recon['allowed_loss_rate'] or 0) if 'allowed_loss_rate' in recon_keys else 0
        freight_diff = abs(float(recon['freight_diff'] or 0)) if 'freight_diff' in recon_keys else 0
        if qty_diff_rate > allowed:
            new_status = 'discrepancy'
        elif freight_diff >= 0.01:
            new_status = 'pending'
        else:
            new_status = 'matched'

        sets = ["status=?"]
        params = [new_status]
        if 'confirmed_by' in recon_keys:
            sets.append("confirmed_by=NULL")
        if 'confirmed_at' in recon_keys:
            sets.append("confirmed_at=NULL")
        db.execute(
            f"UPDATE reconciliations SET {', '.join(sets)} WHERE id=?",
            params + [id],
        )
        db.commit()
        add_log(session.get('user_id'), session.get('username', ''), '对账反确认',
                f"对账单ID: {id}", request.remote_addr)
        flash('已反确认，对账单回到未确认状态', 'success')
        return redirect(url_for('reconciliation_detail', id=id))

    # ---------- 付款类型 ----------
    @app.route('/payment_type/add', methods=['POST'])
    @login_required
    def payment_type_add():
        db = get_db()
        name = request.form.get('name', '').strip()
        desc = request.form.get('description', '')
        if name:
            db.execute("INSERT INTO payment_types (name, description, created_at) VALUES (?,?,?)",
                       (name, desc, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            db.commit()
            flash('付款类型已添加', 'success')
        return redirect(url_for('payment_type_list'))

    @app.route('/payment_type/edit', methods=['POST'])
    @login_required
    def payment_type_edit():
        db = get_db()
        pt_id = request.form.get('id', type=int)
        if not pt_id:
            flash('无效的付款类型', 'danger')
            return redirect(url_for('payment_type_list'))
        db.execute("UPDATE payment_types SET name=?, description=? WHERE id=?",
                   (request.form.get('name', '').strip(),
                    request.form.get('description', ''), pt_id))
        db.commit()
        flash('付款类型已更新', 'success')
        return redirect(url_for('payment_type_list'))

    @app.route('/payment_type/delete', methods=['POST'])
    @login_required
    def payment_type_delete():
        db = get_db()
        pt_id = request.form.get('id', type=int)
        if pt_id:
            db.execute("DELETE FROM payment_types WHERE id=?", (pt_id,))
            db.commit()
            flash('付款类型已删除', 'success')
        return redirect(url_for('payment_type_list'))

    # ---------- 账号管理扩展 ----------
    @app.route('/account/<int:uid>/approve', methods=['POST'])
    @login_required
    @admin_required
    def account_approve(uid):
        db = get_db()
        action = request.form.get('action', 'approve')
        if action == 'approve':
            db.execute("UPDATE users SET status='active', approved_by=?, approved_at=? WHERE id=?",
                       (session.get('user_id'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), uid))
            flash('用户已通过审批', 'success')
        else:
            db.execute("DELETE FROM users WHERE id=? AND status='pending'", (uid,))
            flash('已拒绝该注册申请', 'warning')
        db.commit()
        return redirect(url_for('account_manage'))

    @app.route('/account/<int:uid>/role', methods=['POST'])
    @login_required
    @admin_required
    def account_change_role(uid):
        db = get_db()
        role = request.form.get('role', 'user')
        allowed = {'admin', 'client_collab', 'finance', 'manager', 'user'}
        if role not in allowed:
            role = 'user'
        if uid == session.get('user_id'):
            flash('不能变更当前登录账号角色', 'danger')
            return redirect(url_for('account_manage'))
        target = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if target and target['role'] == 'admin' and role != 'admin':
            admin_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND COALESCE(status, 'active')='active'"
            ).fetchone()[0]
            if admin_count <= 1:
                flash('至少保留一个可用管理员账号', 'danger')
                return redirect(url_for('account_manage'))
        db.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        db.commit()
        flash('角色已更新', 'success')
        return redirect(url_for('account_manage'))

    @app.route('/account/<int:uid>/toggle', methods=['POST'])
    @login_required
    @admin_required
    def account_toggle(uid):
        db = get_db()
        if uid == session.get('user_id'):
            flash('不能禁用当前登录账号', 'danger')
            return redirect(url_for('account_manage'))
        u = db.execute("SELECT role, status FROM users WHERE id=?", (uid,)).fetchone()
        new_status = 'disabled' if u and u['status'] == 'active' else 'active'
        if u and u['role'] == 'admin' and new_status == 'disabled':
            admin_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND COALESCE(status, 'active')='active'"
            ).fetchone()[0]
            if admin_count <= 1:
                flash('至少保留一个可用管理员账号', 'danger')
                return redirect(url_for('account_manage'))
        db.execute("UPDATE users SET status=? WHERE id=?", (new_status, uid))
        db.commit()
        flash('账号状态已更新', 'success')
        return redirect(url_for('account_manage'))

    # ---------- 文件服务 ----------
    @app.route('/uploads/<folder>/<filename>')
    @login_required
    def serve_upload_file(folder, filename):
        path = os.path.join(app_config['UPLOAD_FOLDER'], folder)
        return send_from_directory(path, filename)

    @app.route('/ocr/image/<filename>')
    @login_required
    def serve_ocr_image(filename):
        path = os.path.join(app_config['UPLOAD_FOLDER'], 'ocr')
        return send_from_directory(path, filename)

    # ---------- 交易编辑 ----------
    @app.route('/transaction/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def transaction_edit(id):
        from project_category_utils import validate_project_category, ensure_project_categories_table
        import os
        import uuid

        db = get_db()
        t = db.execute("SELECT * FROM transaction_records WHERE id=?", (id,)).fetchone()
        if not t:
            flash('记录不存在', 'danger')
            return redirect(url_for('transaction_records'))

        projects = db.execute("SELECT * FROM projects ORDER BY name").fetchall()
        participants = db.execute("SELECT * FROM participants ORDER BY name").fetchall()
        categories = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()
        category_code = ''
        if t['category_id']:
            cat = db.execute(
                "SELECT code FROM categories WHERE id=?", (t['category_id'],)
            ).fetchone()
            if cat and cat['code']:
                category_code = cat['code']

        if request.method == 'POST':
            project_id = request.form.get('project_id', type=int)
            category_id = request.form.get('category_id', type=int)
            ensure_project_categories_table(db)
            if project_id and category_id and not validate_project_category(
                    db, project_id, category_id):
                flash('所选费用分类未在本项目启用', 'danger')
                return redirect(url_for('transaction_edit', id=id))

            participant_id = request.form.get('participant_id') or None
            trans_date = request.form.get('trans_date', '')
            amount = float(request.form.get('amount', 0) or 0)
            trans_type = request.form.get('trans_type', 'expense')
            description = request.form.get('description', '')
            merchant = request.form.get('merchant', '')
            payment_method = request.form.get('payment_method', '')
            cost_pool = request.form.get('cost_pool', 'project')
            invoice_id = request.form.get('invoice_id') or None
            purchase_id = request.form.get('purchase_id') or None
            transport_quantity = request.form.get('transport_quantity', type=float)

            attachment = t['attachment']
            if 'attachment' in request.files:
                file = request.files['attachment']
                if file and file.filename:
                    filename = f"trans_{uuid.uuid4().hex[:8]}_{file.filename}"
                    filepath = os.path.join(app_config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    attachment = filename

            db.execute("""UPDATE transaction_records SET
                project_id=?, participant_id=?, category_id=?, trans_date=?, amount=?,
                trans_type=?, description=?, merchant=?, payment_method=?, cost_pool=?,
                invoice_id=?, purchase_id=?, transport_quantity=?, attachment=?
                WHERE id=?""",
                       (project_id, participant_id, category_id, trans_date, amount,
                        trans_type, description, merchant, payment_method, cost_pool,
                        invoice_id, purchase_id, transport_quantity, attachment, id))
            db.commit()
            add_log(session.get('user_id'), session.get('username', ''), '编辑交易',
                    f'记录ID {id} 金额 {amount}', request.remote_addr)
            flash('交易记录已更新', 'success')
            return redirect(url_for('transaction_records'))

        return render_template(
            'transaction_form.html',
            trans=t,
            projects=projects,
            participants=participants,
            categories=categories,
            now=datetime.now(),
            category_code=category_code,
        )

    @app.route('/payment/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def payment_edit(id):
        flash('请从项目详情页管理付款记录', 'info')
        return redirect(url_for('transaction_records'))

    # ---------- 项目详情：参与人/投资/分红 CRUD ----------
    @app.route('/project/<int:pid>/participant/<int:participant_id>/remove', methods=['POST'])
    @login_required
    def project_participant_remove(pid, participant_id):
        db = get_db()
        db.execute(
            "DELETE FROM project_participants WHERE project_id=? AND participant_id=?",
            (pid, participant_id)
        )
        db.commit()
        flash('已从项目移除该参与人', 'success')
        return redirect(url_for('project_detail', pid=pid))

    @app.route('/project/<int:pid>/participant/<int:participant_id>/update', methods=['POST'])
    @login_required
    def project_participant_update(pid, participant_id):
        db = get_db()
        try:
            investment_ratio = float(request.form.get('investment_ratio', 0) or 0)
            dividend_ratio = float(request.form.get('dividend_ratio', 0) or 0)
        except (TypeError, ValueError):
            flash('比例必须为数字', 'warning')
            return redirect(url_for('project_detail', pid=pid))
        project_role = request.form.get('project_role')
        if project_role:
            db.execute(
                """UPDATE project_participants
                   SET investment_ratio=?, dividend_ratio=?, project_role=?
                   WHERE project_id=? AND participant_id=?""",
                (investment_ratio, dividend_ratio, project_role, pid, participant_id)
            )
        else:
            db.execute(
                """UPDATE project_participants
                   SET investment_ratio=?, dividend_ratio=?
                   WHERE project_id=? AND participant_id=?""",
                (investment_ratio, dividend_ratio, pid, participant_id)
            )
        db.commit()
        flash('参与人比例已更新', 'success')
        return redirect(url_for('project_detail', pid=pid))

    @app.route('/project/<int:pid>/investment/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def investment_edit(pid, id):
        db = get_db()
        inv = db.execute(
            "SELECT * FROM investments WHERE id=? AND project_id=?", (id, pid)
        ).fetchone()
        if not inv:
            flash('投资记录不存在', 'danger')
            return redirect(url_for('project_detail', pid=pid))
        participants = db.execute("""
            SELECT p.* FROM participants p
            JOIN project_participants pp ON p.id = pp.participant_id
            WHERE pp.project_id=? ORDER BY p.name
        """, (pid,)).fetchall()
        if request.method == 'POST':
            db.execute("""UPDATE investments SET participant_id=?, invest_date=?, amount=?,
                          invest_type=?, payment_method=?, remark=? WHERE id=?""",
                       (request.form.get('participant_id'), request.form.get('invest_date'),
                        float(request.form.get('amount', 0) or 0),
                        request.form.get('invest_type', ''),
                        request.form.get('payment_method', ''),
                        request.form.get('remark', ''), id))
            db.commit()
            flash('投资记录已更新', 'success')
            return redirect(url_for('project_detail', pid=pid))
        project = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return render_template('investment_form_edit.html', investment=inv,
                               participants=participants, project=project)

    @app.route('/project/<int:pid>/investment/<int:id>/delete', methods=['POST'])
    @login_required
    def investment_delete(pid, id):
        db = get_db()
        db.execute("DELETE FROM investments WHERE id=? AND project_id=?", (id, pid))
        db.commit()
        flash('投资记录已删除', 'success')
        return redirect(url_for('project_detail', pid=pid))

    @app.route('/project/<int:pid>/dividend/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def dividend_edit(pid, id):
        db = get_db()
        div = db.execute(
            "SELECT * FROM dividends WHERE id=? AND project_id=?", (id, pid)
        ).fetchone()
        if not div:
            flash('分红记录不存在', 'danger')
            return redirect(url_for('project_detail', pid=pid))
        participants = db.execute("""
            SELECT p.* FROM participants p
            JOIN project_participants pp ON p.id = pp.participant_id
            WHERE pp.project_id=? ORDER BY p.name
        """, (pid,)).fetchall()
        if request.method == 'POST':
            db.execute("""UPDATE dividends SET participant_id=?, dividend_date=?, amount=?,
                          period=?, payment_method=?, remark=? WHERE id=?""",
                       (request.form.get('participant_id'), request.form.get('dividend_date'),
                        float(request.form.get('amount', 0) or 0),
                        request.form.get('period', ''),
                        request.form.get('payment_method', ''),
                        request.form.get('remark', ''), id))
            db.commit()
            flash('分红记录已更新', 'success')
            return redirect(url_for('project_detail', pid=pid))
        project = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return render_template('dividend_form_edit.html', dividend=div,
                               participants=participants, project=project)

    @app.route('/project/<int:pid>/dividend/<int:id>/delete', methods=['POST'])
    @login_required
    def dividend_delete(pid, id):
        db = get_db()
        db.execute("DELETE FROM dividends WHERE id=? AND project_id=?", (id, pid))
        db.commit()
        flash('分红记录已删除', 'success')
        return redirect(url_for('project_detail', pid=pid))

    @app.route('/transaction/<int:id>/delete', methods=['POST'])
    @login_required
    def transaction_delete(id):
        db = get_db()
        row = db.execute("SELECT project_id FROM transaction_records WHERE id=?", (id,)).fetchone()
        db.execute("DELETE FROM transaction_records WHERE id=?", (id,))
        db.commit()
        flash('收支记录已删除', 'success')
        pid = row['project_id'] if row else None
        if pid:
            return redirect(url_for('project_detail', pid=pid))
        return redirect(url_for('transaction_records'))

    @app.route('/project/<int:pid>/payment/<int:id>/delete', methods=['POST'])
    @login_required
    def payment_delete(pid, id):
        db = get_db()
        db.execute("DELETE FROM payments WHERE id=? AND project_id=?", (id, pid))
        db.commit()
        flash('付款记录已删除', 'success')
        return redirect(url_for('project_detail', pid=pid))

    @app.route('/project/<int:pid>/fund/<int:id>/delete', methods=['POST'])
    @login_required
    def fund_transaction_delete(pid, id):
        db = get_db()
        db.execute("DELETE FROM transactions WHERE id=? AND project_id=?", (id, pid))
        db.commit()
        flash('往来款记录已删除', 'success')
        return redirect(url_for('project_detail', pid=pid))

    # ---------- 投资 ----------
    @app.route('/investments')
    @login_required
    def investment_list():
        return redirect(url_for('participant_list'))

    @app.route('/investment/add', methods=['GET', 'POST'])
    @login_required
    def investment_record_add():
        return redirect(url_for('excel_import') + '?type=investment')

    # ---------- 分红（占位） ----------
    @app.route('/dividend/batches')
    @login_required
    def dividend_batches():
        flash('分红批次功能开发中', 'info')
        return redirect(url_for('dashboard'))

    @app.route('/dividend/batch/<int:id>')
    @login_required
    def dividend_batch_detail(id):
        return redirect(url_for('dashboard'))

    @app.route('/dividend/reports')
    @login_required
    def dividend_reports():
        q = request.query_string.decode('utf-8')
        target = url_for('reports.view', slug='investment-dividend')
        if q:
            target += '?' + q
        return redirect(target)

    @app.route('/dividend/rules')
    @login_required
    def dividend_rules():
        return redirect(url_for('dashboard'))

    @app.route('/approval/list')
    @login_required
    def approval_process():
        return redirect(url_for('contract_list'))

    # ---------- 客户协同扩展 ----------
    from auth_utils import module_required, MODULE_CLIENT_PORTAL
    from client_portal_utils import CLIENT_STATUS_APPROVED, CLIENT_STATUS_DISABLED

    @app.route('/admin/client-accounts/<int:id>/enable', methods=['POST'])
    @login_required
    @module_required(MODULE_CLIENT_PORTAL)
    def admin_client_account_enable(id):
        db = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            "UPDATE client_accounts SET status=?, updated_at=? WHERE id=?",
            (CLIENT_STATUS_APPROVED, now, id),
        )
        db.commit()
        flash('账户已启用', 'success')
        return redirect(url_for('admin_client_accounts'))

    @app.route('/admin/client-accounts/<int:id>/disable', methods=['POST'])
    @login_required
    @module_required(MODULE_CLIENT_PORTAL)
    def admin_client_account_disable(id):
        db = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            "UPDATE client_accounts SET status=?, updated_at=? WHERE id=?",
            (CLIENT_STATUS_DISABLED, now, id),
        )
        db.commit()
        flash('账户已禁用', 'success')
        return redirect(url_for('admin_client_accounts'))
