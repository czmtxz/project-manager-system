# -*- coding: utf-8 -*-
"""补全模板引用但 app.py 中缺失的路由与工具函数"""

from functools import wraps


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
    permission_required = ctx.get('permission_required')
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
    recalc_investment_ratios = ctx.get('recalc_investment_ratios')
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
        from user_access import list_projects_for_user, project_id_scope_clause
        category = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        if not category:
            flash('分类不存在', 'danger')
            return redirect(url_for('reports.hub'))
        raw_pid = request.args.get('project_id', '')
        project_id = ''
        if raw_pid:
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                pid = None
            else:
                from user_access import can_access_project
                if can_access_project(
                        db, session.get('user_id'), session.get('role', ''), pid):
                    project_id = str(pid)
                else:
                    flash('无权访问该项目（未授权）', 'danger')
        sql = """SELECT t.*, p.name as project_name FROM transaction_records t
                 LEFT JOIN projects p ON t.project_id = p.id WHERE t.category_id=?"""
        scope_sql, scope_params = project_id_scope_clause(
            db, session.get('user_id'), session.get('role', ''), 't.project_id',
        )
        params = [category_id] + list(scope_params)
        sql += scope_sql
        if project_id:
            sql += " AND t.project_id=?"
            params.append(project_id)
        sql += " ORDER BY t.trans_date DESC"
        transactions = db.execute(sql, params).fetchall()
        total_income = sum(t['amount'] for t in transactions if t['trans_type'] == 'income')
        total_expense = sum(t['amount'] for t in transactions if t['trans_type'] == 'expense')
        projects = list_projects_for_user(
            db, session.get('user_id'), session.get('role', ''), 'ORDER BY name',
        )
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

    # ---------- 销售/采购发票管理 ----------
    from invoice_mgmt import (
        ensure_invoice_schema,
        parse_hub_filters,
        build_item_summary,
        list_invoices_for_direction,
        save_invoice,
        update_invoice,
        load_invoice_for_edit,
        save_invoice_from_dict,
        import_invoices_from_excel,
        direction_label,
        hub_redirect_endpoint,
        normalize_direction,
        ocr_import_endpoint,
        excel_import_endpoint,
        save_batch_invoice,
        resolve_selections_from_summary,
        batch_issue_endpoint,
    )

    @app.route('/invoice/hub')
    @login_required
    def invoice_hub():
        return render_template('invoice_hub.html')

    def _invoice_hub_ctx(db, direction):
        ensure_invoice_schema(db)
        from invoice_mgmt import _valid_group_by
        from user_access import list_projects_for_user, can_access_project
        filters = parse_hub_filters(request)
        filters['group_by'] = _valid_group_by(direction, filters.get('group_by'))
        filters['_scope_user_id'] = session.get('user_id')
        filters['_scope_role'] = session.get('role', '')
        if filters.get('project_id'):
            try:
                pid = int(filters['project_id'])
            except (TypeError, ValueError):
                pid = None
            if pid and not can_access_project(
                    db, session.get('user_id'), session.get('role', ''), pid):
                flash('无权访问该项目（未授权）', 'danger')
                filters['project_id'] = ''
        summary = build_item_summary(db, direction, filters)
        invoices = list_invoices_for_direction(db, direction, filters)
        projects = list_projects_for_user(
            db, session.get('user_id'), session.get('role', ''), 'ORDER BY name',
        )
        return {
            'direction': direction,
            'direction_label': direction_label(direction),
            'filters': filters,
            'summary': summary,
            'invoices': invoices,
            'projects': projects,
        }

    def _invoice_view_perm(f):
        from user_access import user_is_admin
        if permission_required:
            @wraps(f)
            def _wrapped(*args, **kwargs):
                if user_is_admin(session.get('role')):
                    return f(*args, **kwargs)
                return permission_required('invoice.view')(f)(*args, **kwargs)
            return _wrapped
        return f

    @app.route('/invoice/sales')
    @login_required
    @_invoice_view_perm
    def invoice_sales():
        db = get_db()
        ctx = _invoice_hub_ctx(db, 'sales')
        return render_template('invoice_direction_hub.html', **ctx)

    @app.route('/invoice/purchase')
    @login_required
    @_invoice_view_perm
    def invoice_purchase():
        db = get_db()
        ctx = _invoice_hub_ctx(db, 'purchase')
        return render_template('invoice_direction_hub.html', **ctx)

    def _invoice_prefill_from_args():
        return {
            'item_name': request.args.get('item_name', ''),
            'specification': request.args.get('specification', ''),
            'customer_name': request.args.get('customer_name', ''),
            'supplier': request.args.get('supplier', ''),
            'open_qty': request.args.get('open_qty', ''),
            'open_amt': request.args.get('open_amt', ''),
        }

    def _invoice_form_view(db, direction, invoice_id=None):
        ensure_invoice_schema(db)
        invoice = None
        lines = []
        if invoice_id:
            invoice, lines = load_invoice_for_edit(db, invoice_id)
            if not invoice:
                flash('发票不存在', 'danger')
                return redirect(url_for(hub_redirect_endpoint(direction)))
            direction = normalize_direction(
                invoice['invoice_type'],
                invoice['biz_direction'] if 'biz_direction' in invoice.keys() else None,
            )
            from user_access import can_access_project
            if not can_access_project(
                    db, session.get('user_id'), session.get('role', ''),
                    invoice['project_id']):
                flash('无权访问该发票所属项目', 'danger')
                return redirect(url_for(hub_redirect_endpoint(direction)))
        if request.method == 'POST':
            from user_access import can_access_project
            pid = request.form.get('project_id', type=int)
            if pid and not can_access_project(
                    db, session.get('user_id'), session.get('role', ''), pid):
                flash('无权操作该项目（未授权）', 'danger')
                return redirect(url_for(hub_redirect_endpoint(direction)))
            if not (request.form.get('invoice_no') or '').strip():
                flash('请填写发票号码', 'warning')
            else:
                if invoice_id:
                    update_invoice(db, invoice_id, direction, request.form)
                    add_log(
                        session.get('user_id'), session.get('username', ''),
                        f'编辑{direction_label(direction)}',
                        f'发票号: {request.form.get("invoice_no")}',
                    )
                    flash('发票已更新', 'success')
                else:
                    save_invoice(db, direction, request.form, session.get('user_id'))
                    add_log(
                        session.get('user_id'), session.get('username', ''),
                        f'新增{direction_label(direction)}',
                        f'发票号: {request.form.get("invoice_no")}',
                    )
                    flash(f'{direction_label(direction)}保存成功', 'success')
                return redirect(url_for(hub_redirect_endpoint(direction)))
        from user_access import list_projects_for_user
        projects = list_projects_for_user(
            db, session.get('user_id'), session.get('role', ''), 'ORDER BY name',
        )
        contracts = db.execute(
            'SELECT id, contract_no, contract_name, project_id FROM contracts ORDER BY contract_name'
        ).fetchall()
        prefill = _invoice_prefill_from_args() if not invoice_id else {}
        return render_template(
            'invoice_direction_form.html',
            direction=direction,
            direction_label=direction_label(direction),
            projects=projects,
            contracts=contracts,
            prefill=prefill,
            invoice=invoice,
            lines=lines,
            edit_mode=bool(invoice_id),
            now=datetime.now(),
        )

    @app.route('/invoice/sales/add', methods=['GET', 'POST'])
    @login_required
    def invoice_sales_add():
        return _invoice_form_view(get_db(), 'sales')

    @app.route('/invoice/purchase/add', methods=['GET', 'POST'])
    @login_required
    def invoice_purchase_add():
        return _invoice_form_view(get_db(), 'purchase')

    def _invoice_batch_view(db, direction):
        ensure_invoice_schema(db)
        from invoice_mgmt import _valid_group_by
        filters = parse_hub_filters(request)
        filters['_scope_user_id'] = session.get('user_id')
        filters['_scope_role'] = session.get('role', '')
        filters['group_by'] = _valid_group_by(direction, filters.get('group_by'))
        group_by = filters['group_by']
        row_keys = request.form.getlist('selected_row') or request.args.getlist('sel')
        if request.method == 'POST' and (request.form.get('invoice_no') or '').strip():
            row_keys = request.form.getlist('selected_row') or row_keys
            try:
                selections, _summary = resolve_selections_from_summary(
                    db, direction, filters, row_keys,
                )
                issue_amount = request.form.get('issue_amount', type=float)
                save_batch_invoice(
                    db, direction, group_by, selections, issue_amount,
                    request.form, session.get('user_id'),
                )
                add_log(
                    session.get('user_id'), session.get('username', ''),
                    f'汇总{direction_label(direction)}',
                    f'票号:{request.form.get("invoice_no")} 金额:{issue_amount}',
                )
                flash(
                    f'已登记发票，本次开票 {issue_amount:.2f} 元（所选未开合计已相应扣减）',
                    'success',
                )
                return redirect(url_for(hub_redirect_endpoint(direction)))
            except ValueError as e:
                flash(str(e), 'warning')
        elif request.method == 'POST':
            row_keys = request.form.getlist('selected_row') or row_keys
        selections, summary = resolve_selections_from_summary(
            db, direction, filters, row_keys,
        )
        if not selections:
            flash('请先在汇总表中勾选未开金额大于0的记录', 'warning')
            return redirect(url_for(hub_redirect_endpoint(direction)))
        total_open = sum(s['open_amt'] for s in selections)
        default_issue = request.form.get('issue_amount', type=float) if request.method == 'POST' else total_open
        if not default_issue:
            default_issue = total_open
        from user_access import list_projects_for_user
        projects = list_projects_for_user(
            db, session.get('user_id'), session.get('role', ''), 'ORDER BY name',
        )
        contracts = db.execute(
            'SELECT id, contract_no, contract_name, project_id FROM contracts ORDER BY contract_name'
        ).fetchall()
        return render_template(
            'invoice_batch_form.html',
            direction=direction,
            direction_label=direction_label(direction),
            filters=filters,
            group_by=group_by,
            selections=selections,
            summary=summary,
            total_open=total_open,
            default_issue=default_issue,
            projects=projects,
            contracts=contracts,
            now=datetime.now(),
        )

    @app.route('/invoice/sales/batch', methods=['GET', 'POST'])
    @login_required
    def invoice_sales_batch():
        return _invoice_batch_view(get_db(), 'sales')

    @app.route('/invoice/purchase/batch', methods=['GET', 'POST'])
    @login_required
    def invoice_purchase_batch():
        return _invoice_batch_view(get_db(), 'purchase')

    @app.route('/invoice/sales/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def invoice_sales_edit(id):
        return _invoice_form_view(get_db(), 'sales', invoice_id=id)

    @app.route('/invoice/purchase/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def invoice_purchase_edit(id):
        return _invoice_form_view(get_db(), 'purchase', invoice_id=id)

    def _invoice_ocr_view(db, direction):
        ensure_invoice_schema(db)
        from user_access import list_projects_for_user, can_access_project
        projects = list_projects_for_user(
            db, session.get('user_id'), session.get('role', ''), 'ORDER BY name',
        )
        project_id = request.form.get('project_id', type=int) or request.args.get('project_id', type=int)
        if project_id and not can_access_project(
                db, session.get('user_id'), session.get('role', ''), project_id):
            flash('无权操作该项目（未授权）', 'danger')
            project_id = None
        results = []
        if request.method == 'POST':
            ok = 0
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
                    invoice_no = (data.get('invoice_no') or '').strip()
                    result = {**data, 'filename': f.filename, 'saved': False, 'attachment': filename}
                    if invoice_no and amount > 0:
                        dup = db.execute(
                            'SELECT id FROM invoices WHERE invoice_no=?', (invoice_no,)
                        ).fetchone()
                        if dup:
                            result['error'] = f'发票号 {invoice_no} 已存在'
                        else:
                            payload = {
                                'project_id': project_id,
                                'invoice_no': invoice_no,
                                'amount': amount,
                                'tax_rate': float(data.get('tax_rate') or 0),
                                'tax_amount': float(data.get('tax_amount') or 0),
                                'invoice_date': data.get('invoice_date') or None,
                                'attachment': filename,
                                'remark': 'OCR识别导入',
                                'customer_name': data.get('buyer') if direction == 'sales' else None,
                                'supplier': data.get('seller') if direction == 'purchase' else None,
                            }
                            save_invoice_from_dict(
                                db, direction, payload, session.get('user_id'),
                            )
                            result['saved'] = True
                            ok += 1
                    else:
                        result['error'] = result.get('error') or '未识别到发票号码或金额'
                    results.append(result)
                except Exception as e:
                    results.append({'filename': f.filename, 'error': str(e), 'saved': False})
            if results:
                ok = sum(1 for r in results if r.get('saved'))
                flash(f'OCR 处理 {len(results)} 张，成功导入 {ok} 张', 'success' if ok else 'warning')
            else:
                flash('请先选择发票图片', 'warning')
            if ok:
                return redirect(url_for(hub_redirect_endpoint(direction)))
        return render_template(
            'invoice_direction_ocr.html',
            direction=direction,
            direction_label=direction_label(direction),
            projects=projects,
            project_id=project_id,
            results=results,
        )

    @app.route('/invoice/sales/ocr-import', methods=['GET', 'POST'])
    @login_required
    def invoice_sales_ocr_import():
        return _invoice_ocr_view(get_db(), 'sales')

    @app.route('/invoice/purchase/ocr-import', methods=['GET', 'POST'])
    @login_required
    def invoice_purchase_ocr_import():
        return _invoice_ocr_view(get_db(), 'purchase')

    def _invoice_excel_view(db, direction):
        ensure_invoice_schema(db)
        from user_access import list_projects_for_user, can_access_project
        projects = list_projects_for_user(
            db, session.get('user_id'), session.get('role', ''), 'ORDER BY name',
        )
        errors = []
        if request.method == 'POST':
            f = request.files.get('file')
            if not f or not f.filename:
                flash('请选择 Excel 文件', 'warning')
            else:
                pid = request.form.get('project_id', type=int)
                if pid and not can_access_project(
                        db, session.get('user_id'), session.get('role', ''), pid):
                    flash('无权操作该项目（未授权）', 'danger')
                    pid = None
                saved, skipped, errors = import_invoices_from_excel(f, db, direction, pid)
                flash(f'导入完成：成功 {saved} 条，跳过 {skipped} 条', 'success' if saved else 'warning')
                if saved:
                    return redirect(url_for(hub_redirect_endpoint(direction)))
        return render_template(
            'invoice_direction_import.html',
            direction=direction,
            direction_label=direction_label(direction),
            projects=projects,
            errors=errors,
        )

    @app.route('/invoice/sales/import', methods=['GET', 'POST'])
    @login_required
    def invoice_sales_import():
        return _invoice_excel_view(get_db(), 'sales')

    @app.route('/invoice/purchase/import', methods=['GET', 'POST'])
    @login_required
    def invoice_purchase_import():
        return _invoice_excel_view(get_db(), 'purchase')

    # ---------- 发票扩展（兼容旧链接） ----------
    @app.route('/invoice/import', methods=['GET', 'POST'])
    @login_required
    def invoice_import():
        direction = request.args.get('direction', 'purchase')
        if direction not in ('sales', 'purchase'):
            direction = 'purchase'
        return redirect(url_for(excel_import_endpoint(direction)))

    @app.route('/invoice/ocr-import', methods=['GET', 'POST'])
    @login_required
    def invoice_ocr_import():
        direction = request.args.get('direction', 'purchase')
        if direction not in ('sales', 'purchase'):
            direction = 'purchase'
        return redirect(url_for(ocr_import_endpoint(direction)))

    @app.route('/invoice/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def invoice_edit(id):
        db = get_db()
        invoice, _lines = load_invoice_for_edit(db, id)
        if not invoice:
            flash('发票不存在', 'danger')
            return redirect(url_for('invoice_hub'))
        direction = normalize_direction(
            invoice['invoice_type'],
            invoice['biz_direction'] if 'biz_direction' in invoice.keys() else None,
        )
        if direction == 'sales':
            return redirect(url_for('invoice_sales_edit', id=id))
        return redirect(url_for('invoice_purchase_edit', id=id))

    @app.route('/invoice/<int:id>/approve', methods=['GET', 'POST'])
    @login_required
    def invoice_approve(id):
        db = get_db()
        inv = db.execute('SELECT invoice_type, biz_direction FROM invoices WHERE id=?', (id,)).fetchone()
        back = hub_redirect_endpoint(normalize_direction(
            inv['invoice_type'] if inv else None,
            inv['biz_direction'] if inv and 'biz_direction' in inv.keys() else None,
        )) if inv else 'invoice_hub'
        db.execute("UPDATE invoices SET status='verified' WHERE id=?", (id,))
        db.commit()
        flash('发票已审核', 'success')
        return redirect(url_for(back))

    @app.route('/invoice/<int:id>/delete', methods=['POST'])
    @login_required
    def invoice_delete(id):
        db = get_db()
        row = db.execute(
            'SELECT invoice_no, invoice_type, biz_direction FROM invoices WHERE id=?', (id,)
        ).fetchone()
        if not row:
            flash('发票不存在', 'danger')
            return redirect(url_for('invoice_hub'))
        back = hub_redirect_endpoint(normalize_direction(
            row['invoice_type'], row['biz_direction'] if 'biz_direction' in row.keys() else None
        ))
        db.execute('DELETE FROM invoice_summary_allocations WHERE invoice_id=?', (id,))
        db.execute('DELETE FROM invoice_lines WHERE invoice_id=?', (id,))
        db.execute('DELETE FROM invoices WHERE id=?', (id,))
        db.commit()
        add_log(session.get('user_id'), session.get('username', ''), '删除发票', f'发票号: {row["invoice_no"] or id}')
        flash('发票已删除', 'success')
        return redirect(url_for(back))

    # ---------- 采购扩展 ----------
    @app.route('/purchase/<int:id>/submit')
    @login_required
    def purchase_submit(id):
        db = get_db()
        purchase = db.execute(
            'SELECT id, purchase_no, status FROM purchase_orders WHERE id=?', (id,)
        ).fetchone()
        if not purchase:
            flash('采购单不存在', 'danger')
            return redirect(url_for('purchase_list'))
        status = (purchase['status'] or '').strip()
        if status not in ('draft', '草稿'):
            flash('该采购单已提交或不可重复提交', 'warning')
            return redirect(url_for('purchase_detail', id=id))
        items = db.execute(
            'SELECT COUNT(*) as cnt FROM purchase_items WHERE purchase_id=?', (id,)
        ).fetchone()
        if not items or items['cnt'] == 0:
            flash('请先添加采购明细后再提交', 'warning')
            return redirect(url_for('purchase_detail', id=id))
        db.execute("UPDATE purchase_orders SET status='已提交' WHERE id=?", (id,))
        db.commit()
        add_log(session.get('user_id'), session.get('username', ''), '提交采购单', f'采购单号: {purchase["purchase_no"]}')
        flash('采购单已提交', 'success')
        return redirect(url_for('purchase_detail', id=id))

    # ---------- 对账扩展 ----------
    @app.route('/reconciliation/create/<int:purchase_id>')
    @login_required
    def reconciliation_create(purchase_id):
        db = get_db()
        from project_display import fetch_purchase_by_id
        purchase = fetch_purchase_by_id(db, purchase_id, with_contract=False)
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
    def payment_edit_ext(id):
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
        # 投资比例按实际投资金额自动计算，这里只允许调整分红比例（及角色）
        try:
            dividend_ratio = float(request.form.get('dividend_ratio', 0) or 0)
        except (TypeError, ValueError):
            flash('分红比例必须为数字', 'warning')
            return redirect(url_for('project_detail', pid=pid))
        project_role = request.form.get('project_role')
        if project_role:
            db.execute(
                """UPDATE project_participants
                   SET dividend_ratio=?, project_role=?
                   WHERE project_id=? AND participant_id=?""",
                (dividend_ratio, project_role, pid, participant_id)
            )
        else:
            db.execute(
                """UPDATE project_participants
                   SET dividend_ratio=?
                   WHERE project_id=? AND participant_id=?""",
                (dividend_ratio, pid, participant_id)
            )
        db.commit()
        flash('分红比例已更新', 'success')
        return redirect(url_for('project_detail', pid=pid))

    @app.route('/project/<int:pid>/investment/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def investment_edit_ext(pid, id):
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
            if recalc_investment_ratios:
                recalc_investment_ratios(db, pid)
            flash('投资记录已更新', 'success')
            return redirect(url_for('project_detail', pid=pid))
        project = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return render_template('investment_form_edit.html', investment=inv,
                               participants=participants, project=project)

    @app.route('/project/<int:pid>/investment/<int:id>/delete', methods=['POST'])
    @login_required
    def investment_delete_ext(pid, id):
        db = get_db()
        db.execute("DELETE FROM investments WHERE id=? AND project_id=?", (id, pid))
        db.commit()
        if recalc_investment_ratios:
            recalc_investment_ratios(db, pid)
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
    def payment_delete_ext(pid, id):
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
    from auth_utils import module_required, MODULE_CLIENT_PORTAL, collab_authorize_required
    from client_portal_utils import CLIENT_STATUS_APPROVED, CLIENT_STATUS_DISABLED

    @app.route('/admin/client-accounts/<int:id>/enable', methods=['POST'])
    @login_required
    @module_required(MODULE_CLIENT_PORTAL)
    @collab_authorize_required
    def admin_client_account_enable(id):
        db = get_db()
        from client_collab_scope import assert_client_account_access
        denied = assert_client_account_access(
            db, session.get('user_id'), session.get('role'), id)
        if denied:
            return denied
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
    @collab_authorize_required
    def admin_client_account_disable(id):
        db = get_db()
        from client_collab_scope import assert_client_account_access
        denied = assert_client_account_access(
            db, session.get('user_id'), session.get('role'), id)
        if denied:
            return denied
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            "UPDATE client_accounts SET status=?, updated_at=? WHERE id=?",
            (CLIENT_STATUS_DISABLED, now, id),
        )
        db.commit()
        flash('账户已禁用', 'success')
        return redirect(url_for('admin_client_accounts'))
