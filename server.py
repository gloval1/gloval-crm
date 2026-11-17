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
    cur.execute("DELETE FROM activities")
    cur.execute("DELETE FROM deals")
    cur.execute("DELETE FROM customers")
    cur.execute("DELETE FROM users")
    
    # 株式会社GLOVAL メンバー (フラット構成 / 目標0)
    users = [
        (1, "黒川 剛", "kurokawa@gloval.com", "member", "#4f46e5", 0),
        (2, "奥中 佑亮", "okunaka@gloval.com", "member", "#06b6d4", 0),
        (3, "屋木 孝之", "yaki@gloval.com", "member", "#10b981", 0),
    ]
    cur.executemany("INSERT INTO users (id, name, email, role, avatar_color, target_amount) VALUES (?, ?, ?, ?, ?, ?)", users)
    
    # Customers
    customers = [
        (1, "株式会社サイバーフロント", "IT・通信", "伊藤 部長", "ito@cyberfront.example.jp", "03-1234-5678", "active", "来期のDX推進予算あり。決裁権限あり。"),
        (2, "大和ロジスティクス株式会社", "運輸・倉庫", "高橋 課長", "takahashi@yamato-logi.example.jp", "06-9876-5432", "active", "全国15拠点の配送管理システム刷新を検討中。"),
        (3, "メディカルネットソリューションズ", "医療・ヘルスケア", "木村 理事", "kimura@medicalnet.example.jp", "03-5555-0101", "active", "オンライン診療対応のクラウド連携を急務としている。"),
        (4, "株式会社トランスグローバル", "商社・貿易", "小林 マネージャー", "kobayashi@transglobal.example.jp", "03-4444-2222", "lead", "Web問い合わせ経由。多言語対応機能に関心。"),
        (5, "フューチャーエデュケーション株式会社", "教育・EdTech", "中村 代表", "nakamura@future-edu.example.jp", "03-3333-7777", "active", "自社オンラインスクール受講生管理ツールの乗り換え検討。"),
        (6, "桜商事株式会社", "卸売・小売", "渡辺 室長", "watanabe@sakura-shoji.example.jp", "03-8888-9999", "lead", "既存ツールの操作性が悪く営業部から不満が出ている。"),
        (7, "エコパワーエンジニアリング", "製造・エネルギー", "松田 工場長", "matsuda@ecopower.example.jp", "052-111-2222", "active", "設備稼働状況の可視化ダッシュボードの構築支援。"),
    ]
    cur.executemany("INSERT INTO customers (id, name, industry, contact_name, contact_email, contact_phone, status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", customers)
    
    today = datetime.date.today()
    next_week = (today + datetime.timedelta(days=7)).isoformat()
    two_weeks = (today + datetime.timedelta(days=14)).isoformat()
    next_month = (today + datetime.timedelta(days=30)).isoformat()
    past_week = (today - datetime.timedelta(days=5)).isoformat()
    
    # Deals (担当: 1=黒川 剛, 2=奥中 佑亮, 3=屋木 孝之)
    deals = [
        (1, "海外拠点向けCRM多言語展開", 4, 3, 4800000, "lead", 10, next_month, None, "初回問い合わせへのヒアリングシート送付済み"),
        (2, "全社AIチャットボット導入プロジェクト", 1, 3, 2400000, "meeting", 30, two_weeks, None, "情シス担当者と技術要件の確認中"),
        (3, "基幹システム刷新に伴う営業管理SaaS導入", 1, 2, 3500000, "proposal", 60, next_week, None, "役員プレゼン向け見積書・提案書提出済み"),
        (4, "太陽光モニタリングデータ連携支援", 7, 3, 6500000, "proposal", 60, next_month, None, "技術検証（PoC）の仕様合意待ち"),
        (5, "配送ドライバー向け端末連携アプリ構築", 2, 2, 5200000, "negotiation", 80, next_week, None, "基本合意完了。契約書面の法務チェックフェーズ"),
        (6, "オンライン診療プラットフォーム導入支援", 3, 1, 8000000, "won", 100, past_week, None, "大型受注確定！来月より要件定義キックオフ"),
        (7, "店舗向け在庫管理タブレット導入", 6, 2, 1800000, "lost", 0, past_week, "競合他社の安価なパッケージ製品に決定", "次回リプレイス期（1年後）に再アプローチ"),
    ]
    cur.executemany("INSERT INTO deals (id, title, customer_id, user_id, amount, stage, probability, expected_close_date, lost_reason, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", deals)
    
    # Activities
    activities = [
        (1, 1, 3, 2, "meeting", today.isoformat(), "役員提案プレゼン実施", "役員3名出席。費用対効果に関する質疑あり。追加の比較試算表を提出予定。", "試算表作成と送付", (today + datetime.timedelta(days=2)).isoformat(), 0),
        (2, 3, 6, 1, "visit", past_week, "最終条件合意・受注調印", "契約締結完了。来期予算にて正式発注書受領済み。", "キックオフ準備", (today + datetime.timedelta(days=5)).isoformat(), 1),
        (3, 4, 1, 3, "email", (today - datetime.timedelta(days=2)).isoformat(), "初回ヒアリングシート送信", "担当窓口宛にヒアリング項目と事例集を送付。", "回答内容の確認電話", (today + datetime.timedelta(days=3)).isoformat(), 0),
        (4, 2, 5, 2, "call", (today - datetime.timedelta(days=1)).isoformat(), "法務チェック進捗確認", "法務部門よりNDA追記事項の要望あり。修正版を再送する。", "修正版契約書ドラフトの送付", (today + datetime.timedelta(days=1)).isoformat(), 0),
        (5, 7, 4, 3, "meeting", today.isoformat(), "技術PoC打合せ", "工場内ネットワーク環境とのインターフェース仕様を検討。", "仕様書のFIX", (today + datetime.timedelta(days=4)).isoformat(), 0),
    ]
    cur.executemany("INSERT INTO activities (id, customer_id, deal_id, user_id, type, activity_date, summary, details, next_action, next_action_date, is_completed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", activities)
    conn.commit()



SEAL_BASE64_DATA = "data:image/png;base64,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"

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
