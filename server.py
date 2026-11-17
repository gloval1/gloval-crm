#!/usr/bin/env python3
"""
Sales CRM Server (株式会社GLOVAL 専用 SFA/CRM)
Zero-dependency Full-Stack CRM for sales teams.
Supports Password Protection, Automated Daily Backup, CSV Import/Export, REST API, and SQLite persistence.
"""
import os
import sys
import json
import sqlite3
import datetime
import hashlib
import csv
import io
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "crm.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SALT = "GLOVAL_CRM_SECURE_SALT_2026"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def compute_token(password: str) -> str:
    return hashlib.sha256((password + SALT).encode('utf-8')).hexdigest()[:32]

def get_current_password(conn) -> str:
    env_pwd = os.environ.get('CRM_PASSWORD') or os.environ.get('ADMIN_PASSWORD')
    if env_pwd and env_pwd.strip():
        return env_pwd.strip()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'password'")
    row = cur.fetchone()
    if row and row['value']:
        return row['value']
    return "gloval"

def backup_db():
    try:
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR, exist_ok=True)
        today_str = datetime.date.today().isoformat()
        backup_file = os.path.join(BACKUP_DIR, f"crm_backup_{today_str}.db")
        if os.path.exists(DB_PATH) and not os.path.exists(backup_file):
            shutil.copy2(DB_PATH, backup_file)
            print(f"[Backup] Automated daily backup created: {backup_file}")
    except Exception as e:
        print(f"[Backup Error] {e}")

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Default password: gloval
    cur.execute("SELECT value FROM settings WHERE key = 'password'")
    if not cur.fetchone():
        cur.execute("INSERT INTO settings (key, value) VALUES ('password', 'gloval')")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        role TEXT NOT NULL,
        avatar_color TEXT DEFAULT '#3b82f6',
        target_amount INTEGER DEFAULT 0
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        industry TEXT,
        contact_name TEXT,
        contact_email TEXT,
        contact_phone TEXT,
        status TEXT DEFAULT 'active',
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        customer_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        stage TEXT NOT NULL DEFAULT 'lead',
        probability INTEGER DEFAULT 10,
        expected_close_date TEXT,
        lost_reason TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        deal_id INTEGER,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        activity_date TEXT,
        summary TEXT NOT NULL,
        details TEXT,
        next_action TEXT,
        next_action_date TEXT,
        is_completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL,
        FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    try:
        cur.execute("ALTER TABLE activities ADD COLUMN activity_date TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE customers ADD COLUMN tags TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN tags TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN billing_status TEXT DEFAULT 'unbilled'")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN billing_date TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN paid_date TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN is_recurring INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN recurring_interval TEXT DEFAULT 'monthly'")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE deals ADD COLUMN recurring_day INTEGER DEFAULT 25")
    except sqlite3.OperationalError:
        pass

    cur.execute('''
    CREATE TABLE IF NOT EXISTS document_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deal_id INTEGER,
        customer_id INTEGER,
        doc_type TEXT NOT NULL,
        doc_number TEXT NOT NULL,
        doc_date TEXT NOT NULL,
        due_date TEXT,
        customer_name TEXT,
        subject TEXT,
        subtotal INTEGER DEFAULT 0,
        tax INTEGER DEFAULT 0,
        total_amount INTEGER DEFAULT 0,
        items_json TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE CASCADE,
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
    )
    ''')

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        filename TEXT,
        data_url TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)
    
    conn.commit()
    
    # Check if users empty, seed default members
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        seed_demo_data(conn)
    conn.close()

    # Daily backup
    backup_db()

def seed_demo_data(conn):
    cur = conn.cursor()
    # 株式会社GLOVAL メンバー (フラット構成 / 目標0)
    users = [
        (1, "黒川 剛", "kurokawa@gloval.com", "member", "#4f46e5", 0),
        (2, "奥中 佑亮", "okunaka@gloval.com", "member", "#06b6d4", 0),
        (3, "屋木 孝之", "yaki@gloval.com", "member", "#10b981", 0),
    ]
    cur.executemany("INSERT OR IGNORE INTO users (id, name, email, role, avatar_color, target_amount) VALUES (?, ?, ?, ?, ?, ?)", users)
    conn.commit()

def render_print_html(query_str: str) -> str:
    qs = urllib.parse.parse_qs(query_str)
    doc_type = qs.get('doc_type', ['estimate'])[0]
    customer_name = qs.get('customer_name', ['取引先企業名'])[0]
    doc_date = qs.get('date', [''])[0]
    doc_number = qs.get('number', [''])[0]
    due_date = qs.get('due_date', [''])[0]
    subject = qs.get('subject', [''])[0]
    notes = qs.get('notes', [''])[0]
    raw_items = qs.get('items', ['[]'])[0]
    try:
        items = json.loads(raw_items)
    except Exception:
        items = []

    is_estimate = (doc_type == 'estimate')
    type_title = 'QUOTATION' if is_estimate else '請 求 書'
    sub_title = '御 見 積 書' if is_estimate else '<span style="border-bottom: 2px solid #0f172a; padding-bottom: 1px;">I N V O I C E</span>'
    date_label = 'Date' if is_estimate else '発行日:'
    no_label = 'No.' if is_estimate else '請求書番号:'
    total_title = '御見積金額 (税込)' if is_estimate else 'ご請求金額 (税込)'
    total_suffix = '' if is_estimate else '-'
    terms_label = '有効期限:' if is_estimate else 'お支払い期日:'
    terms_value = due_date if due_date else ('提出後30日間' if is_estimate else '')

    subtotal = sum((int(i.get('qty', 0)) * int(i.get('unitPrice', 0))) for i in items)
    tax = int(subtotal * 0.1)
    total = subtotal + tax

    def fmt(n):
        return f"{n:,}"

    items_tr = ""
    for it in items:
        q = it.get('qty', 0)
        u = it.get('unit', '式')
        p = it.get('unitPrice', 0)
        amt = q * p
        name = it.get('name', '')
        items_tr += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 7px 8px; font-weight: bold; color: #0f172a;">{name}</td>
          <td style="padding: 7px 6px; text-align: center; font-family: monospace;">{q}</td>
          <td style="padding: 7px 6px; text-align: center; color: #475569;">{u}</td>
          <td style="padding: 7px 8px; text-align: right; font-family: monospace;">¥{fmt(p)}</td>
          <td style="padding: 7px 8px; text-align: right; font-family: monospace; font-weight: bold; color: #0f172a;">¥{fmt(amt)}</td>
        </tr>
        """

    amount_bar_style = 'background: #f8fafc; border-left: 5px solid #2563eb; padding: 10px 14px; border-radius: 8px;' if is_estimate else 'background: #f8fafc; border-top: 2px solid #0f172a; border-bottom: 2px solid #0f172a; padding: 10px 14px;'
    total_color = '#1d4ed8' if is_estimate else '#0f172a'

    template_file = os.path.join(STATIC_DIR, "print_template.html")
    with open(template_file, "r", encoding="utf-8") as f:
        tpl = f.read()

    tpl = tpl.replace("__TYPE_TITLE__", type_title)
    tpl = tpl.replace("__SUB_TITLE__", sub_title)
    tpl = tpl.replace("__DATE_LABEL__", date_label)
    tpl = tpl.replace("__NO_LABEL__", no_label)
    tpl = tpl.replace("__DOC_DATE__", doc_date)
    tpl = tpl.replace("__DOC_NUMBER__", doc_number)
    tpl = tpl.replace("__CUSTOMER_NAME__", customer_name)
    tpl = tpl.replace("__SUBJECT__", subject)
    tpl = tpl.replace("__TERMS_LABEL__", terms_label)
    tpl = tpl.replace("__TERMS_VALUE__", terms_value)
    tpl = tpl.replace("__AMOUNT_BAR_STYLE__", amount_bar_style)
    tpl = tpl.replace("__TOTAL_TITLE__", total_title)
    tpl = tpl.replace("__TOTAL_COLOR__", total_color)
    tpl = tpl.replace("__TOTAL_AMOUNT__", fmt(total))
    tpl = tpl.replace("__TOTAL_SUFFIX__", total_suffix)
    tpl = tpl.replace("__ITEMS_TR__", items_tr)
    tpl = tpl.replace("__SUBTOTAL__", fmt(subtotal))
    tpl = tpl.replace("__TAX__", fmt(tax))
    tpl = tpl.replace("__NOTES__", notes if notes else "&nbsp;")
    tpl = tpl.replace("__SEAL_BASE64__", SEAL_BASE64_DATA)

    return tpl

class CRMRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def is_authenticated(self):
        token = self.headers.get('X-Auth-Token', '')
        if not token:
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            token = q.get('token', [''])[0]
        
        conn = get_db()
        expected = compute_token(get_current_password(conn))
        conn.close()
        return token == expected

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Token')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_csv(self, filename, content):
        bom = b'\xef\xbb\xbf'
        body = bom + content.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            raw_body = self.rfile.read(content_length)
            return json.loads(raw_body.decode("utf-8"))
        return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Auth-Token')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/'):
            # Public auth check endpoint
            if path == '/api/auth/status':
                is_auth = self.is_authenticated()
                self.send_json({"authenticated": is_auth})
                return

            # Public Print/Export endpoint for A4 quotation & invoice
            if path == '/api/print/document':
                html_data = render_print_html(parsed.query).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(html_data)))
                self.end_headers()
                self.wfile.write(html_data)
                return

            # Require authentication for all other API endpoints
            if not self.is_authenticated():
                self.send_json({"error": "Unauthorized", "require_auth": True}, status=401)
                return

            conn = get_db()
            cur = conn.cursor()
            
            if path == '/api/bootstrap':
                cur.execute("SELECT * FROM users ORDER BY id")
                users = [dict(r) for r in cur.fetchall()]
                
                cur.execute("SELECT * FROM customers ORDER BY id DESC")
                customers = [dict(r) for r in cur.fetchall()]
                
                cur.execute("""
                    SELECT d.*, c.name as customer_name, u.name as user_name, u.avatar_color as user_color
                    FROM deals d
                    JOIN customers c ON d.customer_id = c.id
                    JOIN users u ON d.user_id = u.id
                    ORDER BY d.updated_at DESC
                """)
                deals = [dict(r) for r in cur.fetchall()]
                
                cur.execute("""
                    SELECT a.*, c.name as customer_name, d.title as deal_title, u.name as user_name
                    FROM activities a
                    LEFT JOIN customers c ON a.customer_id = c.id
                    LEFT JOIN deals d ON a.deal_id = d.id
                    JOIN users u ON a.user_id = u.id
                    ORDER BY a.created_at DESC
                """)
                activities = [dict(r) for r in cur.fetchall()]
                
                # Check for tunnel url
                tunnel_url = ""
                tunnel_file = os.path.join(BASE_DIR, "tunnel_url.txt")
                if os.path.exists(tunnel_file):
                    try:
                        with open(tunnel_file, 'r', encoding='utf-8') as f:
                            tunnel_url = f.read().strip()
                    except Exception:
                        pass

                self.send_json({
                    "users": users,
                    "customers": customers,
                    "deals": deals,
                    "activities": activities,
                    "tunnel_url": tunnel_url,
                    "stages": [
                        {"id": "lead", "label": "リード獲得", "prob": 10, "color": "bg-slate-100 text-slate-700 border-slate-300"},
                        {"id": "meeting", "label": "初回商談", "prob": 30, "color": "bg-blue-50 text-blue-700 border-blue-300"},
                        {"id": "proposal", "label": "提案・見積", "prob": 60, "color": "bg-amber-50 text-amber-700 border-amber-300"},
                        {"id": "negotiation", "label": "最終交渉", "prob": 80, "color": "bg-purple-50 text-purple-700 border-purple-300"},
                        {"id": "won", "label": "受注", "prob": 100, "color": "bg-emerald-50 text-emerald-700 border-emerald-300"},
                        {"id": "lost", "label": "失注", "prob": 0, "color": "bg-rose-50 text-rose-700 border-rose-300"},
                    ]
                })
                conn.close()
                return

            elif path == '/api/analytics':
                cur.execute("SELECT * FROM users")
                users = [dict(r) for r in cur.fetchall()]
                
                cur.execute("""
                    SELECT d.*, c.name as customer_name, u.name as user_name
                    FROM deals d
                    JOIN customers c ON d.customer_id = c.id
                    JOIN users u ON d.user_id = u.id
                """)
                deals = [dict(r) for r in cur.fetchall()]
                
                total_target = sum(u['target_amount'] for u in users)
                total_won = sum(d['amount'] for d in deals if d['stage'] == 'won')
                pipeline_weighted = sum(int(d['amount'] * (d['probability'] / 100.0)) for d in deals if d['stage'] not in ('won', 'lost'))
                pipeline_total = sum(d['amount'] for d in deals if d['stage'] not in ('won', 'lost'))
                expected_total = total_won + pipeline_weighted
                achievement_rate = round((expected_total / total_target * 100), 1) if total_target > 0 else 0
                
                stages_count = {}
                stages_amount = {}
                for d in deals:
                    s = d['stage']
                    stages_count[s] = stages_count.get(s, 0) + 1
                    stages_amount[s] = stages_amount.get(s, 0) + d['amount']
                    
                user_perf = []
                for u in users:
                    u_deals = [d for d in deals if d['user_id'] == u['id']]
                    u_won = sum(d['amount'] for d in u_deals if d['stage'] == 'won')
                    u_weighted = sum(int(d['amount'] * (d['probability'] / 100.0)) for d in u_deals if d['stage'] not in ('won', 'lost'))
                    user_perf.append({
                        "id": u['id'],
                        "name": u['name'],
                        "target": u['target_amount'],
                        "won": u_won,
                        "pipeline_weighted": u_weighted,
                        "expected": u_won + u_weighted,
                        "rate": round(((u_won + u_weighted) / u['target_amount'] * 100), 1) if u['target_amount'] > 0 else 0,
                        "active_count": len([d for d in u_deals if d['stage'] not in ('won', 'lost')])
                    })
                
                # Lost Reasons breakdown
                lost_deals = [d for d in deals if d['stage'] == 'lost']
                lost_reasons = {}
                for d in lost_deals:
                    r = d.get('lost_reason') or '理由未入力'
                    lost_reasons[r] = lost_reasons.get(r, 0) + 1

                conn.close()
                self.send_json({
                    "total_target": total_target,
                    "total_won": total_won,
                    "pipeline_weighted": pipeline_weighted,
                    "pipeline_total": pipeline_total,
                    "expected_total": expected_total,
                    "achievement_rate": achievement_rate,
                    "stages_count": stages_count,
                    "stages_amount": stages_amount,
                    "lost_reasons": lost_reasons,
                    "user_perf": user_perf
                })
                return

            elif path == '/api/documents/history':
                qs = urllib.parse.parse_qs(parsed.query)
                deal_id = qs.get('deal_id', [''])[0]
                customer_id = qs.get('customer_id', [''])[0]
                if deal_id:
                    cur.execute("SELECT * FROM document_history WHERE deal_id = ? ORDER BY id DESC", (int(deal_id),))
                elif customer_id:
                    cur.execute("SELECT * FROM document_history WHERE customer_id = ? ORDER BY id DESC", (int(customer_id),))
                else:
                    cur.execute("SELECT * FROM document_history ORDER BY id DESC LIMIT 50")
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                self.send_json(rows)
                return

            elif path == '/api/deals/recurring':
                cur.execute("""
                    SELECT d.*, c.name as customer_name, u.name as user_name
                    FROM deals d
                    JOIN customers c ON d.customer_id = c.id
                    JOIN users u ON d.user_id = u.id
                    WHERE d.is_recurring = 1
                    ORDER BY d.recurring_day ASC, d.id DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                self.send_json(rows)
                return

            elif path == '/api/attachments':
                qs = urllib.parse.parse_qs(parsed.query)
                target_type = qs.get('target_type', [''])[0]
                target_id = qs.get('target_id', [''])[0]
                if target_type and target_id:
                    cur.execute("SELECT id, target_type, target_id, filename, data_url, created_at FROM attachments WHERE target_type = ? AND target_id = ? ORDER BY id DESC", (target_type, int(target_id)))
                else:
                    cur.execute("SELECT id, target_type, target_id, filename, data_url, created_at FROM attachments ORDER BY id DESC LIMIT 50")
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                self.send_json(rows)
                return



            elif path == '/api/backup/download':
                conn.close()
                if os.path.exists(DB_PATH):
                    with open(DB_PATH, 'rb') as f:
                        data = f.read()
                    today_str = datetime.date.today().isoformat()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/x-sqlite3')
                    self.send_header('Content-Disposition', f'attachment; filename="gloval_crm_backup_{today_str}.db"')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                else:
                    self.send_json({"error": "Database file not found"}, status=404)
                    return

            elif path == '/api/export/customers':
                cur.execute("SELECT id, name, industry, contact_name, contact_email, contact_phone, status, notes, created_at FROM customers ORDER BY id")
                rows = cur.fetchall()
                conn.close()
                
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["ID", "企業名", "業種", "担当者名", "メールアドレス", "電話番号", "ステータス", "特記事項・備考", "登録日"])
                for r in rows:
                    writer.writerow([r['id'], r['name'], r['industry'], r['contact_name'], r['contact_email'], r['contact_phone'], r['status'], r['notes'], r['created_at']])
                
                self.send_csv(f"customers_{datetime.date.today().isoformat()}.csv", output.getvalue())
                return

            elif path == '/api/export/deals':
                cur.execute("""
                    SELECT d.id, d.title, c.name as customer_name, u.name as user_name, d.amount, d.stage, d.probability, d.expected_close_date, d.lost_reason, d.notes, d.created_at
                    FROM deals d
                    JOIN customers c ON d.customer_id = c.id
                    JOIN users u ON d.user_id = u.id
                    ORDER BY d.id
                """)
                rows = cur.fetchall()
                conn.close()
                
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["案件ID", "案件名", "顧客名", "営業担当者", "想定金額(円)", "フェーズ", "受注確度(%)", "完了予定日", "失注理由", "メモ", "作成日"])
                for r in rows:
                    writer.writerow([r['id'], r['title'], r['customer_name'], r['user_name'], r['amount'], r['stage'], r['probability'], r['expected_close_date'], r['lost_reason'], r['notes'], r['created_at']])
                
                self.send_csv(f"deals_{datetime.date.today().isoformat()}.csv", output.getvalue())
                return

                conn.close()
                self.send_json({"error": "Endpoint not found"}, status=404)
                return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/'):
            # Login endpoint (Public)
            if path == '/api/auth/login':
                body = self.read_json_body()
                pwd = body.get('password', '').strip()
                conn = get_db()
                curr_pwd = get_current_password(conn)
                conn.close()
                if pwd == curr_pwd:
                    token = compute_token(curr_pwd)
                    self.send_json({"success": True, "token": token})
                    return
                else:
                    self.send_json({"success": False, "error": "合言葉が違います"}, status=401)
                    return

            # All other POST endpoints require authentication
            if not self.is_authenticated():
                self.send_json({"error": "Unauthorized", "require_auth": True}, status=401)
                return

            conn = get_db()
            cur = conn.cursor()

            if path == '/api/auth/change-password':
                body = self.read_json_body()
                old_pwd = body.get('old_password', '').strip()
                new_pwd = body.get('new_password', '').strip()
                curr_pwd = get_current_password(conn)

                if old_pwd != curr_pwd:
                    conn.close()
                    self.send_json({"success": False, "error": "現在の合言葉が違います"}, status=400)
                    return
                if not new_pwd or len(new_pwd) < 4:
                    conn.close()
                    self.send_json({"success": False, "error": "新しい合言葉は4文字以上にしてください"}, status=400)
                    return

                cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('password', ?)", (new_pwd,))
                conn.commit()
                conn.close()
                new_token = compute_token(new_pwd)
                self.send_json({"success": True, "token": new_token})
                return

            elif path == '/api/reset-demo':
                seed_demo_data(conn)
                conn.close()
                self.send_json({"success": True, "message": "Demo data reset successfully."})
                return

            elif path == '/api/clear-demo':
                # 本番スタート用: メンバー3名は残し、サンプルデータをすべて削除
                backup_db()
                cur.execute("DELETE FROM activities")
                cur.execute("DELETE FROM deals")
                cur.execute("DELETE FROM customers")
                conn.commit()
                conn.close()
                self.send_json({"success": True, "message": "本番運用を開始しました。デモデータをクリアしました。"})
                return

            elif path == '/api/documents/history':
                body = self.read_json_body()
                cur.execute("""
                    INSERT INTO document_history (
                        deal_id, customer_id, doc_type, doc_number, doc_date, due_date,
                        customer_name, subject, subtotal, tax, total_amount, items_json, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get('deal_id'),
                    body.get('customer_id'),
                    body.get('doc_type', 'estimate'),
                    body.get('doc_number', ''),
                    body.get('doc_date', ''),
                    body.get('due_date', ''),
                    body.get('customer_name', ''),
                    body.get('subject', ''),
                    int(body.get('subtotal', 0)),
                    int(body.get('tax', 0)),
                    int(body.get('total_amount', 0)),
                    json.dumps(body.get('items', [])),
                    body.get('notes', '')
                ))
                new_id = cur.lastrowid
                conn.commit()
                conn.close()
                self.send_json({"success": True, "id": new_id})
                return

            elif path == '/api/deals/recurring/generate':
                # Batch generate this month's invoice deals from recurring master templates
                today = datetime.date.today()
                month_str = today.strftime("%Y年%m月度")
                cur.execute("SELECT * FROM deals WHERE is_recurring = 1")
                recurring_templates = [dict(r) for r in cur.fetchall()]
                created_count = 0

                for tpl in recurring_templates:
                    new_title = f"{tpl['title']} ({month_str})"
                    # Check if already generated for this month
                    cur.execute("SELECT id FROM deals WHERE title = ? AND customer_id = ?", (new_title, tpl['customer_id']))
                    if not cur.fetchone():
                        # Calculate due date based on recurring_day
                        r_day = tpl.get('recurring_day') or 25
                        try:
                            # End of current month or next month
                            due_date_obj = datetime.date(today.year, today.month, min(r_day, 28))
                        except Exception:
                            due_date_obj = today + datetime.timedelta(days=30)
                        
                        cur.execute("""
                            INSERT INTO deals (
                                title, customer_id, user_id, amount, stage, probability,
                                expected_close_date, billing_status, notes, is_recurring
                            ) VALUES (?, ?, ?, ?, 'won', 100, ?, 'unbilled', ?, 0)
                        """, (
                            new_title,
                            tpl['customer_id'],
                            tpl['user_id'],
                            tpl['amount'],
                            due_date_obj.isoformat(),
                            f"【月額定期請求自動起票】{tpl.get('notes') or ''}"
                        ))
                        created_count += 1
                
                conn.commit()
                conn.close()
                self.send_json({"success": True, "created_count": created_count, "month": month_str})
                return

            elif path == '/api/deals':
                body = self.read_json_body()
                cur.execute("""
                    INSERT INTO deals (title, customer_id, user_id, amount, stage, probability, expected_close_date, lost_reason, notes, tags, billing_status, billing_date, paid_date, is_recurring, recurring_interval, recurring_day)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get('title', '無題案件'),
                    body.get('customer_id'),
                    body.get('user_id'),
                    int(body.get('amount', 0)),
                    body.get('stage', 'lead'),
                    int(body.get('probability', 10)),
                    body.get('expected_close_date'),
                    body.get('lost_reason', ''),
                    body.get('notes', ''),
                    body.get('tags', ''),
                    body.get('billing_status', 'unbilled'),
                    body.get('billing_date', ''),
                    body.get('paid_date', ''),
                    1 if body.get('is_recurring') else 0,
                    body.get('recurring_interval', 'monthly'),
                    int(body.get('recurring_day', 25))
                ))
                deal_id = cur.lastrowid
                conn.commit()
                conn.close()
                self.send_json({"id": deal_id, "success": True})
                return

            elif path == '/api/customers':
                body = self.read_json_body()
                cur.execute("""
                    INSERT INTO customers (name, industry, contact_name, contact_email, contact_phone, status, notes, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get('name', '新規取引先'),
                    body.get('industry', ''),
                    body.get('contact_name', ''),
                    body.get('contact_email', ''),
                    body.get('contact_phone', ''),
                    body.get('status', 'active'),
                    body.get('notes', ''),
                    body.get('tags', '')
                ))
                cust_id = cur.lastrowid
                conn.commit()
                conn.close()
                self.send_json({"id": cust_id, "success": True})
                return

            elif path == '/api/attachments':
                body = self.read_json_body()
                cur.execute("""
                    INSERT INTO attachments (target_type, target_id, filename, data_url)
                    VALUES (?, ?, ?, ?)
                """, (
                    body.get('target_type', 'customer'),
                    int(body.get('target_id', 0)),
                    body.get('filename', 'photo.jpg'),
                    body.get('data_url', '')
                ))
                att_id = cur.lastrowid
                conn.commit()
                conn.close()
                self.send_json({"id": att_id, "success": True})
                return

            elif path == '/api/activities':
                body = self.read_json_body()
                act_date = body.get('activity_date') or datetime.date.today().isoformat()
                cur.execute("""
                    INSERT INTO activities (customer_id, deal_id, user_id, type, activity_date, summary, details, next_action, next_action_date, is_completed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get('customer_id'),
                    body.get('deal_id'),
                    body.get('user_id'),
                    body.get('type', 'meeting'),
                    act_date,
                    body.get('summary', '活動メモ'),
                    body.get('details', ''),
                    body.get('next_action', ''),
                    body.get('next_action_date'),
                    1 if body.get('is_completed') else 0
                ))
                act_id = cur.lastrowid
                conn.commit()
                conn.close()
                self.send_json({"id": act_id, "success": True})
                return

            elif path == '/api/import/customers':
                body = self.read_json_body()
                csv_data = body.get('csv', '')
                f = io.StringIO(csv_data)
                reader = csv.reader(f)
                headers = next(reader, None)
                imported = 0
                for row in reader:
                    if len(row) >= 1 and row[0].strip():
                        name = row[0].strip()
                        industry = row[1].strip() if len(row) > 1 else ''
                        contact_name = row[2].strip() if len(row) > 2 else ''
                        contact_email = row[3].strip() if len(row) > 3 else ''
                        contact_phone = row[4].strip() if len(row) > 4 else ''
                        notes = row[5].strip() if len(row) > 5 else ''
                        cur.execute("""
                            INSERT INTO customers (name, industry, contact_name, contact_email, contact_phone, notes)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (name, industry, contact_name, contact_email, contact_phone, notes))
                        imported += 1
                conn.commit()
                conn.close()
                self.send_json({"imported_count": imported, "success": True})
                return

                conn.close()
                self.send_json({"error": "Endpoint not found"}, status=404)
                return

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/'):
            if not self.is_authenticated():
                self.send_json({"error": "Unauthorized", "require_auth": True}, status=401)
                return

            conn = get_db()
            cur = conn.cursor()

            if path.startswith('/api/deals/') and path.endswith('/billing'):
                deal_id = int(path.split('/')[3])
                body = self.read_json_body()
                cur.execute("""
                    UPDATE deals 
                    SET billing_status = ?, billing_date = ?, paid_date = ?, updated_at = datetime('now', 'localtime')
                    WHERE id = ?
                """, (
                    body.get('billing_status', 'unbilled'),
                    body.get('billing_date', ''),
                    body.get('paid_date', ''),
                    deal_id
                ))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/deals/') and path.endswith('/stage'):
                deal_id = int(path.split('/')[3])
                body = self.read_json_body()
                new_stage = body.get('stage')
                cur.execute("""
                    UPDATE deals 
                    SET stage = ?, updated_at = datetime('now', 'localtime')
                    WHERE id = ?
                """, (new_stage, deal_id))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/deals/'):
                deal_id = int(path.split('/')[-1])
                body = self.read_json_body()
                cur.execute("""
                    UPDATE deals
                    SET title = ?, customer_id = ?, user_id = ?, amount = ?, stage = ?, probability = ?,
                        expected_close_date = ?, lost_reason = ?, notes = ?, tags = ?,
                        billing_status = coalesce(?, billing_status),
                        billing_date = coalesce(?, billing_date),
                        paid_date = coalesce(?, paid_date),
                        is_recurring = coalesce(?, is_recurring),
                        recurring_interval = coalesce(?, recurring_interval),
                        recurring_day = coalesce(?, recurring_day),
                        updated_at = datetime('now', 'localtime')
                    WHERE id = ?
                """, (
                    body.get('title'),
                    body.get('customer_id'),
                    body.get('user_id'),
                    int(body.get('amount', 0)),
                    body.get('stage'),
                    int(body.get('probability', 0)),
                    body.get('expected_close_date'),
                    body.get('lost_reason'),
                    body.get('notes'),
                    body.get('tags', ''),
                    body.get('billing_status'),
                    body.get('billing_date'),
                    body.get('paid_date'),
                    1 if body.get('is_recurring') else (0 if 'is_recurring' in body else None),
                    body.get('recurring_interval'),
                    int(body.get('recurring_day')) if body.get('recurring_day') is not None else None,
                    deal_id
                ))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/customers/'):
                cust_id = int(path.split('/')[-1])
                body = self.read_json_body()
                cur.execute("""
                    UPDATE customers
                    SET name = ?, industry = ?, contact_name = ?, contact_email = ?, contact_phone = ?, status = ?, notes = ?, tags = ?
                    WHERE id = ?
                """, (
                    body.get('name'),
                    body.get('industry'),
                    body.get('contact_name'),
                    body.get('contact_email'),
                    body.get('contact_phone'),
                    body.get('status'),
                    body.get('notes'),
                    body.get('tags', ''),
                    cust_id
                ))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/users/'):
                user_id = int(path.split('/')[-1])
                body = self.read_json_body()
                cur.execute("""
                    UPDATE users
                    SET name = ?, email = ?, avatar_color = ?, target_amount = ?
                    WHERE id = ?
                """, (
                    body.get('name'),
                    body.get('email'),
                    body.get('avatar_color'),
                    int(body.get('target_amount', 0)),
                    user_id
                ))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/activities/') and path.endswith('/toggle'):
                act_id = int(path.split('/')[3])
                cur.execute("UPDATE activities SET is_completed = CASE WHEN is_completed = 1 THEN 0 ELSE 1 END WHERE id = ?", (act_id,))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

                conn.close()
                self.send_json({"error": "Endpoint not found"}, status=404)
                return

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/'):
            if not self.is_authenticated():
                self.send_json({"error": "Unauthorized", "require_auth": True}, status=401)
                return

            conn = get_db()
            cur = conn.cursor()

            if path.startswith('/api/deals/'):
                deal_id = int(path.split('/')[-1])
                cur.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/customers/'):
                cust_id = int(path.split('/')[-1])
                cur.execute("DELETE FROM customers WHERE id = ?", (cust_id,))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/activities/'):
                act_id = int(path.split('/')[-1])
                cur.execute("DELETE FROM activities WHERE id = ?", (act_id,))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

            elif path.startswith('/api/attachments/'):
                att_id = int(path.split('/')[-1])
                cur.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
                conn.commit()
                conn.close()
                self.send_json({"success": True})
                return

                conn.close()
                self.send_json({"error": "Endpoint not found"}, status=404)
                return

def run_server(port=8088):
    init_db()
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, CRMRequestHandler)
    print(f"Sales CRM Server running at http://0.0.0.0:{port}/")
    print(f"Local Access: http://localhost:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8088))
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(port)
