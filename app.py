import sqlite3
import os
from functools import wraps
from datetime import datetime
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, g
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "optic_pro_system_2026_key"

# Папки для фото
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'frames')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


# ==========================================
# 1. ЕДИНСТВЕННАЯ И ПРАВИЛЬНАЯ НАСТРОЙКА БАЗЫ
# ==========================================

def get_db():
    # ТАЙМАУТ 30 секунд — база будет ждать очереди, а не выдавать ошибку
    db_path = 'optics_crm.db'
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row

    # МАГИЧЕСКАЯ СТРОЧКА: Включает режим WAL (Write-Ahead Logging)
    # Это позволяет ЧИТАТЬ базу, даже когда в неё кто-то ПИШЕТ.
    # Это ГЛАВНОЕ решение ошибки "database is locked"
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn


def init_db():
    db = get_db()
    try:
        # Таблицы создаются один раз
        db.execute("""CREATE TABLE IF NOT EXISTS frames
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, buy_price INTEGER, 
                       sell_price INTEGER, stock INTEGER, photo TEXT DEFAULT 'no_image.png')""")

        db.execute("""CREATE TABLE IF NOT EXISTS lenses
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, vision TEXT, lens_type TEXT, 
                       price INTEGER, stock INTEGER)""")

        db.execute("""CREATE TABLE IF NOT EXISTS orders
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, customer_phone TEXT,
                       frame_id INTEGER, pd TEXT, total_price INTEGER, status TEXT, date TEXT, comment TEXT)""")

        db.execute("""CREATE TABLE IF NOT EXISTS finance
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, amount INTEGER, 
                       description TEXT, date TEXT)""")

        db.execute("""CREATE TABLE IF NOT EXISTS accessories
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, name TEXT, price INTEGER, stock INTEGER)""")

        db.execute("""CREATE TABLE IF NOT EXISTS activity_log
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_role TEXT, action TEXT, details TEXT, date TEXT)""")

        db.commit()
        print("✅ База данных готова и работает в режиме WAL!")
    except Exception as e:
        print(f"❌ Ошибка при инициализации базы: {e}")
    finally:
        db.close()


# Запускаем один раз при старте приложения
with app.app_context():
    init_db()


# ==========================================
# 2. ИСПРАВЛЕННЫЕ УВЕДОМЛЕНИЯ (БЕЗ УТЕЧЕК)
# ==========================================

@app.context_processor
def inject_notifications():
    db = None
    try:
        db = get_db()
        low_f = db.execute("SELECT * FROM frames WHERE stock <= 1").fetchall()
        low_l = db.execute("SELECT * FROM lenses WHERE stock <= 3").fetchall()
        count = len(low_f) + len(low_l)
        return dict(low_stock_count=count, low_frames_list=low_f, low_lenses_list=low_l)
    except:
        return dict(low_stock_count=0, low_frames_list=[], low_lenses_list=[])
    finally:
        if db:
            db.close()  # ЗАКРЫВАЕМ ВСЕГДА, ЧТОБЫ НЕ БЫЛО LOCKED


def log_action(user_role, action, details):
    db = get_db()
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO activity_log (user_role, action, details, date) VALUES (?, ?, ?, ?)",
                   (user_role, action, details, current_time))
        db.commit()
    finally:
        db.close()
# Запуск
with app.app_context():
    init_db()
def log_action(user_role, action, details):
    db = get_db()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO activity_log (user_role, action, details, date) VALUES (?, ?, ?, ?)",
               (user_role, action, details, current_time))
    db.commit()
    db.close()



@app.route("/repair_all")
def repair_all():
    db = get_db()
    results = []
    
    try:
        # 1. Создаем таблицу для брака, если её нет
        db.execute("""
            CREATE TABLE IF NOT EXISTS defective_lenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lens_id INTEGER,
                quantity INTEGER,
                reason TEXT,
                master_name TEXT,
                date TEXT
            )
        """)
        results.append("✅ Таблица defective_lenses готова")

        # 2. Добавляем payment_method в orders и finance
        for table in ['orders', 'finance']:
            cursor = db.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            if 'payment_method' not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN payment_method TEXT DEFAULT 'Наличные'")
                results.append(f"✅ В {table} добавлена колонка оплаты")
            else:
                results.append(f"ℹ️ В {table} колонки уже были")
        
        db.commit()
    except Exception as e:
        results.append(f"❌ Критическая ошибка: {str(e)}")
    finally:
        db.close()
        
    return "<br>".join(results)
# Фильтр для красивых цен (1 000 000)
@app.template_filter('format_price')
def format_price(value):
    try:
        return "{:,.0f}".format(float(value)).replace(",", " ")
    except:
        return "0"


@app.template_filter('number_format')
def number_format(value):
    return format_price(value)


# Глобальные уведомления (доступны везде)

# ==========================================
# 2. АВТОРИЗАЦИЯ
# ==========================================

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_role' not in session:
                return redirect(url_for('login'))
            if role and session.get('user_role') != role and session.get('user_role') != 'manager':
                return "Доступ запрещен", 403
            return f(*args, **kwargs)

        return decorated_function

    return decorator


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Простой вход по паролю (можно усложнить)
        username = request.form.get('username')
        password = request.form.get('password')

        users = {
            "seller": ("1234", "seller"),
            "master": ("4321", "master"),
            "manager": ("admin", "manager")
        }

        if username in users and users[username][0] == password:
            session['user_role'] = users[username][1]
            return redirect(url_for(f"{session['user_role']}_dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ==========================================
# 3. ПРОДАВЕЦ (SELLER)
# ==========================================

@app.route("/seller")
@login_required("seller")
def seller_dashboard():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    # Считаем приход за сегодня
    income = db.execute(
        "SELECT SUM(amount) FROM finance WHERE type = 'приход' AND date = ?", (today,)
    ).fetchone()[0] or 0

    # Считаем расходы за сегодня
    expense = db.execute(
        "SELECT SUM(amount) FROM finance WHERE type = 'расход' AND date = ?", (today,)
    ).fetchone()[0] or 0

    db.close()
    return render_template("seller_dashboard.html", income=income, expense=expense)


# --- СПИСОК ПРОЧИХ ТОВАРОВ ---
@app.route("/seller/other")
@login_required("seller")
def other_items():
    db = get_db()
    search = request.args.get('search', '')
    query = "SELECT * FROM accessories WHERE name LIKE ? OR category LIKE ? ORDER BY category ASC"
    items = db.execute(query, (f"%{search}%", f"%{search}%")).fetchall()
    db.close()
    return render_template("other_items.html", items=items, search_query=search)


# --- ДОБАВЛЕНИЕ ---
@app.route("/seller/other/add", methods=["POST"])
@login_required("seller")
def add_other_item():
    db = get_db()
    category = request.form.get('category')
    name = request.form.get('name')
    price = request.form.get('price')
    stock = request.form.get('stock')

    db.execute("INSERT INTO accessories (category, name, price, stock) VALUES (?, ?, ?, ?)",
               (category, name, price, stock))
    db.commit()
    db.close()
    return redirect("/seller/other")


# --- РЕДАКТИРОВАНИЕ ---
@app.route("/seller/other/edit/<int:id>", methods=["POST"])
@login_required("seller")
def edit_other_item(id):
    db = get_db()
    db.execute("""
               UPDATE accessories
               SET category=?,
                   name=?,
                   price=?,
                   stock=?
               WHERE id = ?
               """, (request.form.get('category'), request.form.get('name'),
                     request.form.get('price'), request.form.get('stock'), id))
    db.commit()
    db.close()
    return redirect("/seller/other")


@app.route("/seller/other/sell", methods=["POST"])
@login_required("seller")
def sell_other_manual():
    db = get_db()

    # Получаем данные из формы
    item_name = request.form.get('name')  # Что продали (например, "Футляр")
    price = int(request.form.get('price'))  # За сколько продали
    qty = int(request.form.get('qty'))  # Сколько штук

    total = price * qty
    today = datetime.now().strftime("%Y-%m-%d")

    # Записываем в финансы как ПРИХОД
    db.execute("""
               INSERT INTO finance (type, amount, description, date)
               VALUES ('приход', ?, ?, ?)
               """, (total, f"Прочее: {item_name} ({qty} шт.)", today))

    db.commit()
    db.close()

    # Возвращаемся на главную, где обновится карточка "Прибыль"
    return redirect(url_for('seller_dashboard'))

# --- УДАЛЕНИЕ ---
@app.route("/seller/other/delete/<int:id>")
@login_required("seller")
def delete_other_item(id):
    db = get_db()
    db.execute("DELETE FROM accessories WHERE id = ?", (id,))
    db.commit()
    db.close()
    return redirect("/seller/other")
@app.route("/seller/frames")
@login_required("seller")
def frames_list():
    db = get_db()
    # Получаем текст из поля поиска (если он есть)
    search_query = request.args.get('search', '').strip()

    if search_query:
        # Используем оператор LIKE для поиска по части названия
        # % слово % означает, что ищем совпадение в любом месте строки
        query = "SELECT * FROM frames WHERE name LIKE ? ORDER BY name ASC"
        frames = db.execute(query, (f"%{search_query}%",)).fetchall()
    else:
        # Если поиска нет, просто выводим все оправы
        frames = db.execute("SELECT * FROM frames ORDER BY id DESC").fetchall()

    db.close()
    return render_template("seller_frames.html", frames=frames, search_query=search_query)


@app.route("/seller/frames/add", methods=["GET", "POST"])
@login_required()
def inventory():
    user_role = session.get('user_role')
    if user_role not in ['seller', 'manager']:
        return "Доступ разрешен только Продавцу или Менеджеру", 403

    if request.method == "POST":
        db = get_db()
        try:
            # Сбор данных из формы
            name = request.form.get('name')
            buy_price = int(request.form.get('buy_price') or 0)
            sell_price = int(request.form.get('sell_price') or 0)
            stock = int(request.form.get('stock') or 0)

            # Логика фото
            file = request.files.get('photo')
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                # Убедись, что папка static/uploads/frames создана!
                file.save(os.path.join('static/uploads/frames', filename))
            else:
                filename = 'no_image.png'

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            total_cost = buy_price * stock

            # 1. Вставляем всё ОДНИМ запросом (убедись, что в БД есть колонка photo)
            db.execute(
                "INSERT INTO frames (name, buy_price, sell_price, stock, photo) VALUES (?,?,?,?,?)",
                (name, buy_price, sell_price, stock, filename)
            )

            # 2. Записываем расход в финансы
            if total_cost > 0:
                db.execute(
                    "INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
                    (total_cost, f"Закуп оправ: {name} ({stock} шт)", now)
                )

            db.commit()
            return redirect(url_for('inventory'))  # Или куда тебе удобнее

        except Exception as e:
            db.rollback()
            return f"Ошибка: {e}", 500
        finally:
            db.close()

    return render_template("add_frame.html")
# --- ШАГ 1: СОЗДАНИЕ ЗАКАЗА (ПРОДАВЕЦ) ---
@app.route("/seller/order/add", methods=["GET", "POST"])
@login_required()
def add_order():
    db = get_db()  # Открываем один раз в начале
    if request.method == "POST":
        try:
            customer_name = request.form.get('customer_name')
            customer_phone = request.form.get('customer_phone')
            total_price = int(request.form.get('custom_lens_price') or 0)

            is_repair = request.form.get('is_repair') == 'on'
            is_mini_repair = request.form.get('is_mini_repair') == 'on'
            is_client_frame = request.form.get('is_client_frame') == 'on'

            now_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            date_only = datetime.now().strftime("%Y-%m-%d")

            frame_id = None
            recipe = ""

            if not is_repair and not is_mini_repair:
                r_lens = request.form.get('lens_name_right')
                l_lens = request.form.get('lens_name_left')
                recipe = f"👓 R: {r_lens} | L: {l_lens} | PD: {request.form.get('pd')}"

                if r_lens: db.execute("UPDATE lenses SET stock = stock - 1 WHERE (vision || ' ' || lens_type) = ?",
                                      (r_lens,))
                if l_lens: db.execute("UPDATE lenses SET stock = stock - 1 WHERE (vision || ' ' || lens_type) = ?",
                                      (l_lens,))

                if not is_client_frame:
                    f_name = request.form.get('frame_name')
                    frame = db.execute("SELECT id FROM frames WHERE name = ?", (f_name,)).fetchone()
                    if frame:
                        frame_id = frame['id']
                        db.execute("UPDATE frames SET stock = stock - 1 WHERE id = ?", (frame_id,))
            else:
                recipe = f"🔧 Ремонт: {request.form.get('repair_comment')}"

            status = "Выполнено" if is_mini_repair else "Новый"
            db.execute("""INSERT INTO orders (customer_name, customer_phone, frame_id, total_price, status, date, comment)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (customer_name, customer_phone, frame_id, total_price, status, now_time, recipe))

            db.execute("""INSERT INTO finance (type, amount, description, date) 
                          VALUES ('приход', ?, ?, ?)""",
                       (total_price, f"Заказ: {customer_name}", date_only))

            db.commit()
            return redirect(url_for('seller_dashboard'))
        except Exception as e:
            db.rollback()
            print(f"Ошибка при сохранении: {e}")
            return f"Ошибка базы данных: {e}"
        finally:
            db.close()  # Закрываем после POST

    # ДЛЯ ОБЫЧНОГО ОТКРЫТИЯ СТРАНИЦЫ (GET)
    try:
        frames = db.execute("SELECT * FROM frames WHERE stock > 0").fetchall()
        lenses = db.execute("SELECT * FROM lenses WHERE stock > 0").fetchall()
        return render_template("add_order.html", frames=frames, lenses=lenses)
    finally:
        db.close()  # ЗАКРЫВАЕМ ОБЯЗАТЕЛЬНО И ТУТ
@app.route("/seller/orders")
@login_required("seller")
def seller_orders_list():
    db = get_db()

    # Получаем дату из ссылки (например, /seller/orders?date=2026-03-06)
    # Если даты в ссылке нет, берем сегодняшнюю по умолчанию
    selected_date = request.args.get('date')
    today = datetime.now().strftime("%Y-%m-%d")

    if selected_date:
        # Фильтруем заказы по конкретной дате
        query = """
                SELECT o.*, f.name as frame_name
                FROM orders o
                         JOIN frames f ON o.frame_id = f.id
                WHERE o.date LIKE ?
                ORDER BY o.id DESC \
                """
        orders = db.execute(query, (f"{selected_date}%",)).fetchall()
        title = f"Заказы за {selected_date}"
    else:
        # Если дата не указана, показываем вообще всё (или только сегодня - на твой выбор)
        # Давай сделаем, чтобы по умолчанию показывал только СЕГОДНЯ
        query = """
                SELECT o.*, f.name as frame_name
                FROM orders o
                         JOIN frames f ON o.frame_id = f.id
                WHERE o.date LIKE ?
                ORDER BY o.id DESC \
                """
        orders = db.execute(query, (f"{today}%",)).fetchall()
        title = "Заказы за сегодня"

    db.close()
    return render_template("seller_orders.html", orders=orders, title=title)


@app.route("/inventory/lens/delete/<int:lens_id>", methods=["POST"])
@login_required()  # Оставляем общую проверку входа
def delete_lens(lens_id):
    user_role = session.get('role')

    # Список всех, кому МОЖНО удалять (Добавляем Мастера сюда)
    allowed_roles = ['Продавец', 'Менеджер', 'admin', 'Мастер', 'master']

    if user_role not in allowed_roles:
        return f"🛑 Ошибка: Ваша роль ({user_role}) не имеет прав на удаление.", 403

    db = get_db()
    try:
        # Проверяем, существует ли линза перед удалением
        lens = db.execute("SELECT vision FROM lenses WHERE id = ?", (lens_id,)).fetchone()
        if not lens:
            return "Ошибка: Линза не найдена", 404

        db.execute("DELETE FROM lenses WHERE id = ?", (lens_id,))
        db.commit()
        print(f"✅ Линза {lens['vision']} удалена пользователем с ролью {user_role}")
    except Exception as e:
        db.rollback()
        return f"Ошибка базы данных: {e}"
    finally:
        db.close()

    return redirect(url_for('inventory'))
@app.route("/seller/history")
@login_required("seller")
def seller_history():
    db = get_db()
    # Этот запрос берет все записи из finance (и заказы, и прочее)
    # и группирует их по дням, чтобы показать общую выручку за день
    query = """
            SELECT
                date as day_date, SUM (amount) as day_total, COUNT (*) as operations_count
            FROM finance
            WHERE type = 'приход'
            GROUP BY date
            ORDER BY date DESC \
            """
    history = db.execute(query).fetchall()

    # Также берем ВСЕ детальные записи для списка ниже (если захочешь вывести всё сразу)
    all_records = db.execute("""
                             SELECT *
                             FROM finance
                             WHERE type = 'приход'
                             ORDER BY id DESC LIMIT 50
                             """).fetchall()

    db.close()
    return render_template("seller_history.html", history=history, all_records=all_records,
                           today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/seller/history/detail/<date>")
@login_required("seller")
def seller_history_detail(date):
    db = get_db()
    # Берем все операции (приходы и расходы) именно за выбранную дату
    records = db.execute("""
                         SELECT *
                         FROM finance
                         WHERE date = ?
                         ORDER BY id DESC
                         """, (date,)).fetchall()

    # Считаем итог за день для заголовка
    day_total = db.execute("SELECT SUM(amount) FROM finance WHERE date = ? AND type = 'приход'", (date,)).fetchone()[
                    0] or 0

    db.close()
    return render_template("finance_detail.html", records=records, date=date, day_total=day_total)


@app.route("/fix_history_with_phones")
def fix_history_with_phones():
    db = get_db()
    # Берем данные из заказов, включая телефон
    orders = db.execute("SELECT customer_name, customer_phone, total_price, date FROM orders").fetchall()

    for order in orders:
        desc = f"Заказ: {order['customer_name']} | Тел: {order['customer_phone']}"
        # Проверяем, нет ли уже такой записи (по имени и дате)
        exists = db.execute("SELECT id FROM finance WHERE description LIKE ?",
                            (f"Заказ: {order['customer_name']}%",)).fetchone()

        if not exists:
            db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('приход', ?, ?, ?)",
                       (order['total_price'], desc, order['date']))
        else:
            # Если запись есть, но без телефона — обновляем её
            db.execute("UPDATE finance SET description = ? WHERE id = ?", (desc, exists['id']))

    db.commit()
    db.close()
    return "История обновлена: Имена и Телефоны добавлены в финансы!"


@app.route("/fix_names")
def fix_names():
    db = get_db()
    # Берем данные из таблицы заказов
    orders = db.execute("SELECT customer_name, customer_phone, total_price, date FROM orders").fetchall()

    for order in orders:
        new_desc = f"Заказ: {order['customer_name']} | Тел: {order['customer_phone']}"
        # Ищем запись в финансах по дате и сумме, чтобы обновить описание
        db.execute("""
                   UPDATE finance
                   SET description = ?
                   WHERE date = ? AND amount = ? AND description LIKE 'Заказ:%'
                   """, (new_desc, order['date'], order['total_price']))

    db.commit()
    db.close()
    return "Имена и телефоны успешно перенесены в историю финансов!"
# ==========================================
# 4. МАСТЕР (MASTER)
# ==========================================

@app.route("/master")
@login_required("master")
def master_dashboard():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        # 1. ЗАРПЛАТА ЗА СЕГОДНЯ
        income_row = db.execute("""
                                SELECT SUM(amount)
                                FROM finance
                                WHERE type = 'расход'
                                  AND description LIKE 'ЗП Мастера%'
                                  AND date = ?
                                """, (today,)).fetchone()
        income_today = income_row[0] if income_row and income_row[0] else 0

        # 2. ИСТОРИЯ РАБОТ
        history = db.execute("""
                             SELECT amount, description
                             FROM finance
                             WHERE type = 'расход'
                               AND description LIKE 'ЗП Мастера%'
                               AND date = ?
                             ORDER BY id DESC
                             """, (today,)).fetchall()

        # 3. СПИСОК ЗАКАЗОВ ДЛЯ РАБОТЫ (ТО, ЧЕГО НЕ ХВАТАЛО)
        # Используем LEFT JOIN, чтобы видеть спецзаказы без привязки к таблице линз
        orders_list = db.execute("""
            SELECT o.*, f.name as frame_name 
            FROM orders o
            LEFT JOIN frames f ON o.frame_id = f.id
            WHERE o.status != 'Готово' 
            ORDER BY o.id DESC
        """).fetchall()

        # 4. КОЛИЧЕСТВО ЗАКАЗОВ В ОЧЕРЕДИ
        orders_count = len(orders_list)

        # 5. ДЕФИЦИТ
        low_lenses = db.execute("SELECT vision, stock FROM lenses WHERE stock <= 6").fetchall()
        low_frames = db.execute("SELECT name, stock FROM frames WHERE stock <= 2").fetchall()
        low_stock_count = len(low_lenses) + len(low_frames)

    except Exception as e:
        print(f"Ошибка в мастере: {e}")
        income_today, history, orders_list, orders_count, low_lenses, low_frames, low_stock_count = 0, [], [], 0, [], [], 0
    finally:
        db.close()

    return render_template("master_dashboard.html",
                           income_today=income_today,
                           history=history,
                           orders=orders_list, # Передаем список заказов в шаблон
                           orders_count=orders_count,
                           low_lenses=low_lenses,
                           low_frames=low_frames,
                           low_stock_count=low_stock_count)


@app.route("/master/orders")
@login_required("master")
def master_orders():
    db = get_db()
    # Используем LEFT JOIN, чтобы заказы без линз (спецзаказы) не исчезали
    query = """
        SELECT 
            o.id, 
            o.customer_name, 
            o.status, 
            o.pd,
            o.comment,
            f.name as f_name,
            lr.vision as vision_right,
            ll.vision as vision_left
        FROM orders o
        LEFT JOIN frames f ON o.frame_id = f.id
        LEFT JOIN lenses lr ON o.lens_id_right = lr.id
        LEFT JOIN lenses ll ON o.lens_id_left = ll.id
        WHERE o.status != 'Готово'
        ORDER BY o.id DESC
    """
    try:
        # 1. Получаем список заказов
        orders = db.execute(query).fetchall()

        # 2. ДОБАВЛЕНО: Получаем список всех линз для модального окна брака
        # Это нужно, чтобы мастер мог выбрать любую линзу из склада для списания
        lenses = db.execute("SELECT id, vision, lens_type, stock FROM lenses WHERE stock > 0").fetchall()

        # Закрываем базу только после всех запросов
        db.close()

        # Передаем и заказы, и линзы в HTML
        return render_template("master_orders.html", orders=orders, lenses=lenses)

    except Exception as e:
        if db:
            db.close()
        print(f"Ошибка в мастере: {e}")
        return f"Ошибка базы данных: {e}", 500

@app.route("/master/order/done/<int:order_id>", methods=["POST"])
@login_required("master")
def complete_order(order_id):
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        order = db.execute("SELECT comment FROM orders WHERE id = ?", (order_id,)).fetchone()

        # 1. Меняем статус
        db.execute("UPDATE orders SET status = 'Готово' WHERE id = ?", (order_id,))

        # 2. Логика выплаты ЗП
        salary = 20000
        if order and order['comment'] and "МИНИ-РЕМОНТ" in order['comment']:
            salary = 5000 

        db.execute("""INSERT INTO finance (type, amount, description, date) 
                      VALUES ('расход', ?, ?, ?)""",
                   (salary, f"ЗП Мастера: Заказ №{order_id}", today))

        db.commit()
    except Exception as e:
        print(f"Ошибка при завершении: {e}")
        db.rollback()
    finally:
        db.close()
    return redirect(url_for('master_dashboard'))
@app.route("/manager/lenses/add", methods=["POST"])
@login_required()  # Теперь доступ есть и у мастера
def process_lens_supply():
    db = get_db()
    vision = request.form.get('vision', '').strip()
    lens_type = request.form.get('lens_type', '').strip()

    try:
        pairs = int(request.form.get('pairs') or 0)
        price_per_pair = int(request.form.get('price_per_pair') or 0)
        total_amount = int(request.form.get('total_amount') or 0)
    except ValueError:
        return "Ошибка: Введите числа в поля количества и цены", 400

    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Проверяем, есть ли уже такая линза в базе
    existing = db.execute(
        "SELECT id FROM lenses WHERE vision = ? AND lens_type = ?",
        (vision, lens_type)
    ).fetchone()

    if existing:
        # Если нашли — прибавляем к остатку (пары * 2 = штуки)
        db.execute(
            "UPDATE lenses SET stock = stock + ? WHERE id = ?",
            (pairs * 2, existing['id'])
        )
    else:
        # Если НЕ нашли — СОЗДАЕМ новую строку (склад сразу пополнится)
        db.execute(
            "INSERT INTO lenses (vision, lens_type, stock, price) VALUES (?, ?, ?, ?)",
            (vision, lens_type, pairs * 2, 0)
        )

    # 2. ВСЕГДА записываем расход денег в финансы
    if total_amount > 0:
        db.execute(
            "INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
            (total_amount, f"Закуп линз: {vision} ({pairs} пар)", today)
        )

    db.commit()
    db.close()

    # Возвращаемся на страницу склада, где новая линза уже должна появиться
    return redirect(url_for('lenses_page'))
@app.route("/master/order/work/<int:oid>", methods=["POST"])
def master_work(oid):
    db = get_db()
    # Статус меняется + ставим метку для продавца
    db.execute("UPDATE orders SET status='В работе', is_updated=1 WHERE id=?", (oid,))
    db.commit()
    db.close()
    return redirect(url_for('master_orders'))


@app.route("/master/order/done/<int:oid>", methods=["POST"])
@login_required("master")
def master_done(oid):
    db = get_db()

    # 1. Сначала находим информацию о заказе (сумму и имя клиента)
    order = db.execute("SELECT total_price, customer_name FROM orders WHERE id=?", (oid,)).fetchone()

    if order:
        # 2. Меняем статус заказа на 'Готово' и ставим уведомление
        db.execute("UPDATE orders SET status='Готово', is_updated=1 WHERE id=?", (oid,))

        # 3. ДОБАВЛЯЕМ ДЕНЬГИ В ТАБЛИЦУ ФИНАНСОВ
        # Теперь выручка появится в отчетах!
        db.execute("""
                   INSERT INTO finance (type, amount, description, date)
                   VALUES ('приход', ?, ?, ?)
                   """, (
                       order['total_price'],
                       f"Выполнен заказ №{oid}: {order['customer_name']}",
                       datetime.now().strftime("%Y-%m-%d")
                   ))

        db.commit()
        print(f"✅ Заказ №{oid} готов, выручка {order['total_price']} записана!")

    db.close()
    return redirect(url_for('master_orders_list'))


@app.route("/master/orders")
@login_required("master")
def master_orders_list():  # имя функции может быть любым
    db = get_db()
    # Важно: JOIN-ы должны быть правильными, чтобы f_name и vision_right существовали
    query = """
            SELECT o.*, f.name as f_name, lr.vision as vision_right, ll.vision as vision_left
            FROM orders o
                     JOIN frames f ON o.frame_id = f.id
                     JOIN lenses lr ON o.lens_id_right = lr.id
                     JOIN lenses ll ON o.lens_id_left = ll.id
            WHERE o.status IN ('Новый', 'В работе')
            ORDER BY o.id DESC \
            """
    orders = db.execute(query).fetchall()
    db.close()

    # ПРОВЕРЬ ТУТ: имя переменной должно быть 'orders' (во множественном числе)
    return render_template("master_orders.html", orders=orders)
# ==========================================
# 5. МЕНЕДЖЕР (MANAGER)
# ==========================================
@app.route("/manager/dashboard")
@login_required("manager")
def manager_dashboard():
    db = get_db()
    try:
        # 1. ДОХОДЫ (Убрали payment_method, чтобы не было ошибок)
        total_income = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'приход'").fetchone()[0] or 0
        total_investments = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'вложение'").fetchone()[0] or 0
        
        # 2. РАСХОДЫ
        standard_expenses = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'расход'").fetchone()[0] or 0
        new_lens_costs = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'регистрация'").fetchone()[0] or 0

        # Сумма убытка от брака
        total_defect_sum = db.execute("SELECT SUM(amount) FROM finance WHERE description LIKE '%Брак%'").fetchone()[0] or 0

        # Список брака для таблицы
        defect_rows = db.execute("""
            SELECT date, description, amount FROM finance 
            WHERE description LIKE '%Брак%' ORDER BY id DESC LIMIT 10
        """).fetchall()

        defect_history = []
        for row in defect_rows:
            parts = row['description'].replace("Брак:", "").split("-")
            defect_history.append({
                'date': row['date'],
                'master_name': parts[0].strip() if len(parts) > 0 else "Мастер",
                'lens_name': parts[1].strip() if len(parts) > 1 else "Линза",
                'reason': parts[-1].strip() if len(parts) > 2 else "Не указана",
                'amount': row['amount']
            })

        # 3. ИТОГОВАЯ МАТЕМАТИКА
        total_expenses = standard_expenses + new_lens_costs
        net_profit = total_income - total_expenses
        cash_on_hand = (total_income + total_investments) - total_expenses

        # 4. ЖУРНАЛ И СКЛАД
        logs = db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 15").fetchall()
        
        low_f = db.execute("SELECT name, stock FROM frames WHERE stock <= 1").fetchall()
        low_l = db.execute("SELECT (vision || ' ' || lens_type) as name, stock FROM lenses WHERE stock <= 1").fetchall()
        low_stock = [dict(row) for row in low_f] + [dict(row) for row in low_l]

        active_orders_count = db.execute("SELECT COUNT(*) FROM orders WHERE status != 'Готово'").fetchone()[0]

        return render_template("manager_dashboard.html",
                               income=total_income,
                               investments=total_investments,
                               expenses=total_expenses,
                               total_defect=total_defect_sum,
                               defect_history=defect_history,
                               net_profit=net_profit,
                               cash_on_hand=cash_on_hand,
                               low_stock=low_stock,
                               active_orders_count=active_orders_count,
                               logs=logs)
    except Exception as e:
        print(f"ОШИБКА ДАШБОРДА: {e}")
        return f"Ошибка дашборда: {e}"
    finally:
        db.close()
    # ВТОРОЙ finally УДАЛЕН - ОШИБКИ БОЛЬШЕ НЕТ
    
@app.route("/manager/finance/action", methods=["POST"])
@login_required("manager")
def finance_action():
            db = get_db()
            action_type = request.form.get('action_type')  # 'расход' или 'вложение'
            description = request.form.get('description')
            amount = int(request.form.get('amount') or 0)
            today = datetime.now().strftime("%Y-%m-%d %H:%M")

            if amount > 0:
                # Записываем операцию в таблицу финансов
                db.execute("INSERT INTO finance (type, amount, description, date) VALUES (?, ?, ?, ?)",
                           (action_type, amount, description, today))

                # (Опционально) Записываем в лог активности
                try:
                    db.execute("INSERT INTO activity_log (user_role, action, details, date) VALUES (?, ?, ?, ?)",
                               ("Менеджер", action_type.capitalize(), f"{description}: {amount} сум", today))
                except:
                    pass

                db.commit()

            db.close()
            return redirect(url_for('manager_dashboard'))
@app.route("/manager/finance/action", methods=["POST"])
@login_required("manager")
def manager_finance_action():
    db = get_db()
    try:
        amount = int(request.form.get('amount'))
        description = request.form.get('description')
        action_type = request.form.get('action_type')  # 'расход' или 'вложение'
        date = datetime.now().strftime("%Y-%m-%d")

        # 1. Записываем в финансовую таблицу
        db.execute("INSERT INTO finance (type, amount, description, date) VALUES (?, ?, ?, ?)",
                   (action_type, amount, description, date))
        db.commit()

        # 🕵️‍♂️ ШПИОН: Фиксируем движение денег в журнале активности
        # Чтобы ты видел в ленте: "Менеджер | Касса: расход | Сумма: 50,000 (Аренда)"
        log_action("Менеджер", f"Касса: {action_type}", f"Сумма: {amount:,} сум. Причина: {description}")

    except Exception as e:
        print(f"Ошибка в финансах: {e}")
    finally:
        db.close()

    return redirect(url_for('manager_dashboard'))
# ФУНКЦИЯ ДОБАВЛЕНИЯ РАСХОДА МЕНЕДЖЕРОМ
@app.route("/manager/add_expense", methods=["POST"])
@login_required("manager")
def add_expense_in_dashboard():
    db = get_db()
    amount = int(request.form.get('amount'))
    description = request.form.get('description')  # Например: "Аренда за март"
    date = datetime.now().strftime("%Y-%m-%d")

    db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
               (amount, description, date))
    db.commit()
    db.close()
    return redirect(url_for('manager_dashboard'))
@app.route("/manager/stats")
@login_required("manager")
def manager_stats():
    db = get_db()
    # Считаем сумму всех приходов
    total_income = db.execute("SELECT SUM(amount) FROM finance WHERE type='приход'").fetchone()[0] or 0
    # Считаем сумму всех расходов
    total_expense = db.execute("SELECT SUM(amount) FROM finance WHERE type='расход'").fetchone()[0] or 0

    profit = total_income - total_expense

    db.close()
    return render_template("manager_stats.html", income=total_income, expense=total_expense, profit=profit)


@app.route("/master/earnings")
@login_required("master")
def master_earnings():
    db = get_db()
    # Берем текущую дату без времени для сравнения
    today = datetime.now().strftime("%Y-%m-%d")
    FIXED_RATE = 20000

    # 1. Заказы за СЕГОДНЯ (используем LIKE, чтобы найти все за это число независимо от времени)
    today_orders = db.execute("""
                              SELECT o.*, f.name as frame_name
                              FROM orders o
                                       JOIN frames f ON o.frame_id = f.id
                              WHERE o.status = 'Готово'
                                AND o.date LIKE ?
                              """, (f"{today}%",)).fetchall()

    today_count = len(today_orders)
    today_earnings = today_count * FIXED_RATE

    # 2. ИСТОРИЯ (Группируем, обрезая время)
    # SUBSTR(date, 1, 10) берет только "YYYY-MM-DD"
    history = db.execute("""
                         SELECT SUBSTR(date, 1, 10) as day_date, COUNT(id) as count
                         FROM orders
                         WHERE status = 'Готово' AND date NOT LIKE ?
                         GROUP BY day_date
                         ORDER BY day_date DESC
                         """, (f"{today}%",)).fetchall()

    db.close()
    return render_template("master_earnings.html",
                           today_orders=today_orders,
                           today_count=today_count,
                           today_earnings=today_earnings,
                           history=history,
                           rate=FIXED_RATE,
                           today=today)


@app.route("/manager/finance/expense", methods=["GET", "POST"])
@login_required()
def add_expense():
    # Только менеджер может вносить произвольные расходы
    if session.get('user_role') != 'manager':
        return "Доступ запрещен", 403

    if request.method == "POST":
        db = get_db()
        try:
            description = request.form.get('description')
            amount = int(request.form.get('amount') or 0)
            category = request.form.get('category')
            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            if amount > 0:
                # Записываем в таблицу финансов
                db.execute(
                    "INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
                    (amount, f"{category}: {description}", now)
                )

                # Логируем действие
                db.execute(
                    "INSERT INTO activity_log (user_role, action, details, date) VALUES (?, 'Ручной расход', ?, ?)",
                    ('Менеджер', f"Списание {amount} сум на {category}", now)
                )

                db.commit()

            return redirect(url_for('manager_dashboard'))

        except Exception as e:
            db.rollback()
            return f"Ошибка: {e}", 500
        finally:
            db.close()

    return render_template("add_expense.html")
@app.route("/master/earnings/day/<date_str>")
@login_required("master")
def master_earnings_day(date_str):
    db = get_db()
    FIXED_RATE = 20000

    # Используем LIKE '2026-03-06%', чтобы найти все заказы за этот день
    orders = db.execute("""
                        SELECT o.*, f.name as frame_name
                        FROM orders o
                                 JOIN frames f ON o.frame_id = f.id
                        WHERE o.status = 'Готово'
                          AND o.date LIKE ?
                        """, (f"{date_str}%",)).fetchall()

    total_day_money = len(orders) * FIXED_RATE
    db.close()

    return render_template("master_day_detail.html",
                           orders=orders,
                           date=date_str,
                           total_money=total_day_money)

# --- УДАЛЕНИЕ ЛИНЗЫ ---

# --- УДАЛЕНИЕ ОПРАВЫ ---
@app.route("/master/frame/delete/<int:id>")
@login_required("master")
def delete_frame(id):
    db = get_db()
    db.execute("DELETE FROM frames WHERE id = ?", (id,))
    db.commit()
    db.close()
    # Возвращаем на страницу склада оправ (проверь свой путь, обычно это /seller/frames)
    return redirect("/seller/frames")


# --- РЕДАКТИРОВАНИЕ ОПРАВЫ (POST запрос) ---
@app.route("/admin/frame/edit/<int:id>", methods=["GET", "POST"])  # Добавлен GET
@login_required()
def edit_frame(id):
    db = get_db()

    # 1. Сначала получаем текущие данные оправы
    frame = db.execute("SELECT * FROM frames WHERE id = ?", (id,)).fetchone()

    if not frame:
        return "Оправа не найдена", 404

    if request.method == "POST":
        try:
            name = request.form.get("name")
            buy_price = int(request.form.get("buy_price") or 0)
            sell_price = int(request.form.get("sell_price") or 0)
            new_stock = int(request.form.get("stock") or 0)

            # Расчет разницы (сравнение с данными из БД до обновления)
            diff = new_stock - frame['stock']

            if diff != 0:
                # Считаем сумму корректировки по НОВОЙ цене закупа
                amount = abs(diff) * buy_price
                date_now = datetime.now().strftime("%Y-%m-%d")

                if diff > 0:
                    # Увеличили склад — записываем как расход (закупка)
                    db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
                               (amount, f"Корректировка +: закупка {name} ({diff} шт)", date_now))
                else:
                    # Уменьшили склад — записываем как приход (возврат поставщику/отмена)
                    db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('приход', ?, ?, ?)",
                               (amount, f"Корректировка -: списание {name} ({abs(diff)} шт)", date_now))

            # 2. Обновляем саму оправу
            db.execute("UPDATE frames SET name=?, buy_price=?, sell_price=?, stock=? WHERE id=?",
                       (name, buy_price, sell_price, new_stock, id))

            db.commit()
            return redirect(url_for('seller_dashboard'))

        except Exception as e:
            db.rollback()
            print(f"Ошибка при сохранении оправы: {e}")
            return f"Ошибка: {e}", 500
        finally:
            db.close()

    # Если GET — показываем страницу с формой
    return render_template("edit_frame.html", frame=frame)
@app.route("/master/lens/edit/<int:lens_id>", methods=["POST"])
@login_required("master")
def edit_lens_master(lens_id):
    db = get_db()
    new_stock = request.form.get('stock')

    # 🕵️‍♂️ ШПИОН: Узнаем старое количество перед обновлением
    old_data = db.execute("SELECT vision, stock FROM lenses WHERE id=?", (lens_id,)).fetchone()

    if new_stock is not None:
        db.execute("UPDATE lenses SET stock = ? WHERE id = ?", (new_stock, lens_id))
        db.commit()

        # 🕵️‍♂️ ШПИОН: Записываем действие в журнал
        log_action("Мастер", "Изменение склада",
                   f"Линза {old_data['vision']}: было {old_data['stock']} шт, стало {new_stock} шт")

    db.close()
    return "Success", 200


@app.route("/manager/sales_report")
@login_required("manager")
def sales_report():
    db = get_db()

    # 1. Проверка структуры БД (на случай, если колонки нет)
    try:
        db.execute("SELECT payment_method FROM finance LIMIT 1")
    except:
        db.execute("ALTER TABLE finance ADD COLUMN payment_method TEXT DEFAULT 'Наличные'")
        db.commit()

    period = request.args.get('period', 'day')
    now = datetime.now()

    if period == 'day':
        start_date = now.strftime("%Y-%m-%d")
    elif period == 'week':
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == 'month':
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    else:
        start_date = "2000-01-01"

    try:
        # 2. Складские данные
        frames_stock = db.execute("SELECT name, stock FROM frames").fetchall()
        lenses_stock = db.execute("SELECT vision, lens_type, stock FROM lenses").fetchall()
        total_frames = sum(f['stock'] for f in frames_stock)
        total_lenses = sum(l['stock'] for l in lenses_stock)

        # 3. Общие финансовые показатели
        fin_data = db.execute("""
            SELECT 
                SUM(CASE WHEN LOWER(type)='вложение' AND LOWER(description) NOT LIKE '%брак%' THEN amount ELSE 0 END) as investments,
                SUM(CASE WHEN LOWER(type)='расход' OR LOWER(description) LIKE '%брак%' THEN amount ELSE 0 END) as costs,
                SUM(CASE WHEN LOWER(type)='приход' THEN amount ELSE 0 END) as sales_income
            FROM finance 
            WHERE date >= ?
        """, (start_date,)).fetchone()

        investments = fin_data['investments'] or 0
        costs = fin_data['costs'] or 0
        sales_income = fin_data['sales_income'] or 0

        # 4. ЛОГИКА РАСЧЕТА ОТДЕЛЬНЫХ КАСС (Нал, Карта, Click)
        # Мы считаем (Приходы + Вложения) - Расходы для каждого метода отдельно

        def calculate_balance(keywords):
            # Создаем фильтр для поиска по методу оплаты и описанию
            search_filter = " OR ".join(
                [f"LOWER(payment_method) LIKE '%{k}%' OR LOWER(description) LIKE '%{k}%'" for k in keywords])

            query = f"""
                SELECT 
                    SUM(CASE WHEN LOWER(type) IN ('приход', 'вложение') THEN amount ELSE -amount END) 
                FROM finance 
                WHERE date >= ? AND ({search_filter})
            """
            return db.execute(query, (start_date,)).fetchone()[0] or 0

        # Считаем балансы
        cash_total = calculate_balance(['налич', 'нал'])
        card_total = calculate_balance(['карт', 'пластик', 'term'])
        click_total = calculate_balance(['click', 'payme', 'клик', 'пейми'])

        # 5. Итоговые расчеты для баннера
        total_revenue = sales_income
        net_profit = total_revenue - costs
        cash_on_hand = (total_revenue + investments) - costs

        # 6. Получение истории операций
        transactions = db.execute("SELECT * FROM finance WHERE date >= ? ORDER BY id DESC", (start_date,)).fetchall()

    finally:
        db.close()

    return render_template("sales_report.html",
                           transactions=transactions,
                           frames=frames_stock,
                           lenses=lenses_stock,
                           total_frames=total_frames,
                           total_lenses=total_lenses,
                           total_revenue=total_revenue,
                           costs=costs,
                           investments=investments,
                           net_profit=net_profit,
                           cash_on_hand=cash_on_hand,
                           cash_total=cash_total,
                           card_total=card_total,
                           click_total=click_total,
                           current_period=period)
@app.route("/order/print/<int:order_id>")
@login_required("seller")  # Или "manager"
def print_receipt(order_id):
    db = get_db()
    # Собираем все данные заказа, объединяя таблицы
    order = db.execute("""
                       SELECT o.*,
                              f.name       as frame_name,
                              lr.vision    as vision_r,
                              lr.lens_type as type_r,
                              ll.vision    as vision_l,
                              ll.lens_type as type_l
                       FROM orders o
                                JOIN frames f ON o.frame_id = f.id
                                JOIN lenses lr ON o.lens_id_right = lr.id
                                JOIN lenses ll ON o.lens_id_left = ll.id
                       WHERE o.id = ?
                       """, (order_id,)).fetchone()
    db.close()

    if not order:
        return "Заказ не найден", 404

    return render_template("print_receipt.html", order=order)


@app.route("/manager/full_report")
@login_required()
def full_report():
    db = get_db()
    
    # 1. СЛУШАЕМ КНОПКИ (Получаем период из ссылки)
    period = request.args.get('period', 'month') # по умолчанию 'month'
    
    # 2. ОПРЕДЕЛЯЕМ ТОЧКУ ОТСЧЕТА (Динамический фильтр)
    now = datetime.now()
    if period == 'day':
        start_filter = now.strftime("%Y-%m-%d 00:00:00")
    elif period == 'week':
        start_filter = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    else: # month
        start_filter = now.strftime("%Y-%m-01 00:00:00")

    # 3. ИСПОЛЬЗУЕМ start_filter ВО ВСЕХ ЗАПРОСАХ
    
    # Считаем реальные продажи
    pure_sales = db.execute(
        "SELECT SUM(amount) FROM finance WHERE type = 'приход' AND date >= ?", (start_filter,)
    ).fetchone()[0] or 0

    # Считаем вложения
    my_investments = db.execute(
        "SELECT SUM(amount) FROM finance WHERE type = 'вложение' AND date >= ?", (start_filter,)
    ).fetchone()[0] or 0

    # Считаем все расходы
    all_costs = db.execute(
        "SELECT SUM(amount) FROM finance WHERE type = 'расход' AND date >= ?", (start_filter,)
    ).fetchone()[0] or 0

    # ЛОГИКА ЦИФР
    net_profit = pure_sales - all_costs
    cash_in_hand = (pure_sales + my_investments) - all_costs

    # Данные для склада (всегда полные)
    frames_stock = db.execute("SELECT name, stock FROM frames").fetchall()
    lenses_stock = db.execute("SELECT vision, lens_type, stock FROM lenses").fetchall()

    # История операций за выбранный период
    transactions = db.execute(
        "SELECT * FROM finance WHERE date >= ? ORDER BY date DESC, id DESC", 
        (start_filter,)
    ).fetchall()
    
    db.close()

    # 4. ВОЗВРАЩАЕМ current_period В HTML
    return render_template("sales_report.html",
                           current_period=period, # Важно для подсветки активной кнопки
                           frames=frames_stock,
                           lenses=lenses_stock,
                           total_frames=sum(f['stock'] for f in frames_stock),
                           total_lenses=sum(l['stock'] for l in lenses_stock),
                           total_revenue=pure_sales,
                           investments=my_investments,
                           costs=all_costs,
                           net_profit=net_profit,
                           cash_on_hand=cash_in_hand,
                           transactions=transactions)
@app.route("/master/lenses")
@login_required("master")
def master_lenses():
    db = get_db()
    search = request.args.get('search', '')

    # 1. Загружаем список линз
    query = "SELECT * FROM lenses WHERE vision LIKE ? ORDER BY vision ASC"
    lenses = db.execute(query, (f"%{search}%",)).fetchall()

    # 2. Загружаем последние 10 расходов именно по линзам
    lens_expenses = db.execute("""
        SELECT * FROM finance 
        WHERE type = 'расход' AND (description LIKE 'Закуп линз%' OR description LIKE 'Закуп:%')
        ORDER BY id DESC LIMIT 10
    """).fetchall()

    db.close()
    return render_template("master_lenses.html", lenses=lenses, lens_expenses=lens_expenses)


@app.route("/manager/lenses/add", methods=["POST"])
@login_required()  # <-- Обязательно со скобками, чтобы не было TypeError
def add_lenses_stock():
    # Проверяем, что зашел либо мастер, либо менеджер
    user_role = session.get('user_role')
    if user_role not in ['master', 'manager']:
        return "Доступ запрещен: у вас нет прав для этой операции", 403

    db = get_db()
    try:
        # Получаем данные из формы
        vision = request.form.get('vision', '').strip()
        l_type = request.form.get('lens_type', '').strip()

        # Безопасно переводим в числа
        try:
            pairs = int(request.form.get('pairs') or 0)
            price_per_pair = int(request.form.get('price_per_pair') or 0)
        except ValueError:
            return "Ошибка: введите корректные числа для количества и цены", 400

        total_cost = pairs * price_per_pair  # Общая сумма закупки
        qty_pieces = pairs * 2  # Переводим пары в штуки для склада

        # Текущая дата для базы
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 1. ОБНОВЛЯЕМ СКЛАД (lenses)
        # Проверяем, есть ли уже такая линза
        existing = db.execute(
            "SELECT id FROM lenses WHERE vision = ? AND lens_type = ?",
            (vision, l_type)
        ).fetchone()

        if existing:
            # Если есть — плюсуем количество
            db.execute(
                "UPDATE lenses SET stock = stock + ? WHERE id = ?",
                (qty_pieces, existing['id'])
            )
        else:
            # Если нет — создаем новую запись
            db.execute(
                "INSERT INTO lenses (vision, lens_type, stock, price) VALUES (?, ?, ?, 0)",
                (vision, l_type, qty_pieces)
            )

        # 2. ЗАПИСЫВАЕМ РАСХОД (finance)
        if total_cost > 0:
            description = f"Закуп линз: {vision} ({pairs} пар)"
            db.execute(
                "INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
                (total_cost, description, now)
            )

        # 3. ЛОГИРУЕМ ДЕЙСТВИЕ (activity_log)
        try:
            log_details = f"Добавлено {pairs} пар {vision} ({l_type}). Сумма: {total_cost} сум"
            db.execute(
                "INSERT INTO activity_log (user_role, action, details, date) VALUES (?, 'Закупка линз', ?, ?)",
                (user_role.capitalize(), log_details, now)
            )
        except:
            pass  # Если таблицы логов нет, просто идем дальше

        db.commit()

    except Exception as e:
        db.rollback()
        return f"Произошла ошибка базы данных: {str(e)}", 500
    finally:
        db.close()

    return redirect(url_for('master_lenses'))

@app.route("/manager/lenses/add", methods=["POST"])
@login_required()  # <--- Убери "manager", теперь доступ будет у всех
def add_lenses():

    # ... твой код закупки ...
    # 1. Получаем данные из формы (как в твоем прошлом коде)
    vision = request.form.get('vision', '').strip()
    lens_type = request.form.get('lens_type', '').strip()

    try:
        pairs = int(request.form.get('pairs') or 0)
        price_per_pair = int(request.form.get('price_per_pair') or 0)
        # Получаем сумму из скрытого поля (total_amount)
        total_amount = int(request.form.get('total_amount') or 0)
    except ValueError:
        return "Ошибка: введите числа", 400

    if pairs > 0:
        # Подключаемся к базе (убедись, что имя файла верное, например 'optical.db')
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()

        # А. Сначала записываем расход денег
        date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute(
            "INSERT INTO expenses (description, amount, date) VALUES (?, ?, ?)",
            (f"Закупка линз: {vision} ({lens_type}) - {pairs} пар", total_amount, date_now)
        )

        # Б. Проверяем, существует ли уже такая линза на складе
        cursor.execute("SELECT id, stock FROM lenses WHERE vision = ? AND lens_type = ?", (vision, lens_type))
        existing_lens = cursor.fetchone()

        if existing_lens:
            # Если нашли — прибавляем к остатку (пары * 2) и обновляем цену
            new_stock = existing_lens[1] + (pairs * 2)
            cursor.execute(
                "UPDATE lenses SET stock = ?, price = ? WHERE id = ?",
                (new_stock, price_per_pair, existing_lens[0])
            )
        else:
            # Если такой линзы нет — создаем новую запись
            cursor.execute(
                "INSERT INTO lenses (vision, lens_type, stock, price) VALUES (?, ?, ?, ?)",
                (vision, lens_type, pairs * 2, price_per_pair)
            )

        conn.commit()
        conn.close()

    return redirect(url_for('lenses_page'))


# 1. Исправленная функция отображения склада (чтобы не было BuildError)
@app.route("/master/lenses")
@login_required()
def lenses_page():
    db = get_db()
    # 1. Все линзы для таблицы
    lenses = db.execute("SELECT * FROM lenses ORDER BY vision ASC").fetchall()

    # 2. История ЗАКУПОК (расходы денег)
    lens_buys = db.execute("""
        SELECT * FROM finance 
        WHERE type = 'расход' AND (description LIKE 'Закуп%' OR description LIKE 'Расход%')
        ORDER BY id DESC LIMIT 50
    """).fetchall()

    # 3. История НОВЫХ (регистрации)
    # ВАЖНО: Ищем по типам, которые выдал твой check_db.py
    new_lens_history = db.execute("""
        SELECT * FROM finance 
        WHERE type IN ('регистрация', 'вложение')
        ORDER BY id DESC LIMIT 50
    """).fetchall()

    db.close()

    # Передаем ВСЕ ТРИ переменные в шаблон
    return render_template("lenses.html",
                           lenses=lenses,
                           lens_expenses=lens_buys,
                           new_lens_history=new_lens_history)


@app.route('/manager/lenses/add_new_only', methods=['POST'])
@login_required()
def add_new_lens_only():
    db = get_db()
    vision = request.form.get('vision', '').strip()
    lens_type = request.form.get('lens_type', '').strip()

    try:
        buy_price_pair = int(request.form.get('buy_price_pair') or 0)  # Цена за 1 пару
        sale_price_item = int(request.form.get('sale_price_item') or 0)  # Продажа за 1 шт
        pairs_count = int(request.form.get('pairs_count') or 0)

        total_expense = buy_price_pair * pairs_count  # Общая сумма закупа
        stock_items = pairs_count * 2  # Переводим пары в штуки для склада
    except (ValueError, TypeError):
        return "Ошибка в числах", 400

    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Сохраняем в таблицу линз (цена продажи за 1 шт)
    db.execute("INSERT INTO lenses (vision, lens_type, stock, price) VALUES (?, ?, ?, ?)",
               (vision, lens_type, stock_items, sale_price_item))

    # 2. Записываем подробную историю в таблицу finance
    # Добавляем цену за пару и общую сумму в описание
    detail_desc = f"✨ Новая диоптрия: {vision} {lens_type} | Закуп: {buy_price_pair:,.0f} за пару | Всего: {pairs_count} пар".replace(
        ',', ' ')

    db.execute("""
        INSERT INTO finance (type, amount, description, date) 
        VALUES ('регистрация', ?, ?, ?)
    """, (total_expense, detail_desc, today))

    db.commit()
    db.close()
    return redirect(url_for('lenses_page'))


@app.route("/master/lens/edit/<int:lens_id>", methods=["POST"])
@login_required()
def edit_lens_stock(lens_id):
    db = get_db()
    try:
        new_stock = int(request.form.get('stock') or 0)
        lens = db.execute("SELECT vision, lens_type, stock, price FROM lenses WHERE id = ?", (lens_id,)).fetchone()

        if not lens:
            return "Линза не найдена", 404

        old_stock = lens['stock']
        # Если price - это цена продажи, закуп считаем как половину
        cost_per_piece = (lens['price'] or 0) / 2
        diff = new_stock - old_stock

        if diff != 0:
            date_now = datetime.now().strftime("%Y-%m-%d")
            total_amount = abs(diff) * cost_per_piece

            if diff > 0:
                # 1. ПОПОЛНЕНИЕ: Тратим деньги на закупку
                db.execute("""INSERT INTO finance (type, amount, description, date, payment_method) 
                              VALUES ('расход', ?, ?, ?, 'Наличные')""",
                           (total_amount, f"Закупка линз: {lens['vision']} (+{diff} шт.)", date_now))
            else:
                # 2. БРАК / СПИСАНИЕ:
                # Мы НЕ пишем 'приход', потому что деньги не зашли.
                # Мы пишем 'расход', так как это чистый убыток (стоимость испорченного товара)
                db.execute("""INSERT INTO finance (type, amount, description, date, payment_method) 
                              VALUES ('расход', ?, ?, ?, 'Наличные')""",
                           (total_amount, f"СПИСАНИЕ/БРАК: {lens['vision']} (-{abs(diff)} шт.)", date_now))

            # Записываем в лог
            log_action("Мастер", "Изменение остатка",
                       f"{lens['vision']} ({lens['lens_type']}): было {old_stock}, стало {new_stock}")

        # Обновляем склад
        db.execute("UPDATE lenses SET stock = ? WHERE id = ?", (new_stock, lens_id))
        db.commit()
        return "OK", 200

    except Exception as e:
        db.rollback()
        print(f"Ошибка мастера: {e}")
        return f"Ошибка: {e}", 500
    finally:
        db.close()

@app.route("/master/report_defect", methods=["POST"])
@login_required("master")
def report_defect():
    db = get_db()
    try:
        lens_id = request.form.get('lens_id')
        qty = int(request.form.get('quantity') or 1)
        reason = request.form.get('reason')
        master_name = "Мастер" # Можно брать из сессии, если есть
        date_now = datetime.now().strftime("%Y-%m-%d")

        # 1. Списываем линзу со склада
        db.execute("UPDATE lenses SET stock = stock - ? WHERE id = ?", (qty, lens_id))
        
        # 2. Получаем инфо о линзе для описания
        lens = db.execute("SELECT vision, lens_type, price FROM lenses WHERE id = ?", (lens_id,)).fetchone()
        loss_amount = (lens['price'] or 50000) * qty # Примерная сумма убытка

        # 3. ЗАПИСЫВАЕМ В ФИНАНСЫ КАК РАСХОД (Чтобы Менеджер видел минус)
        db.execute("""INSERT INTO finance (type, amount, description, date) 
                      VALUES ('расход', ?, ?, ?)""",
                   (loss_amount, f"Брак: {master_name} - {lens['vision']} - {reason}", date_now))

        log_action('Мастер', 'Брак', f"Испорчено: {lens['vision']} ({qty} шт)")
        
        db.commit()
        return redirect(url_for('master_dashboard'))
    except Exception as e:
        db.rollback()
        return f"Ошибка при списании брака: {e}"
    finally:
        db.close()

@app.route("/master/lens/brake", methods=["POST"])
@login_required("master")
def master_lens_brake():
    db = get_db()
    try:
        lens_id = request.form.get('lens_id')
        qty = int(request.form.get('qty') or 1)

        # Получаем данные линзы
        lens = db.execute("SELECT vision, price FROM lenses WHERE id = ?", (lens_id,)).fetchone()
        if not lens:
            return "Линза не найдена", 404

        # Считаем себестоимость (если закуп 50% от цены)
        cost_per_piece = (lens['price'] or 50000) / 2
        total_loss = cost_per_piece * qty
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. УМЕНЬШАЕМ СКЛАД (Минус штуки)
        db.execute("UPDATE lenses SET stock = stock - ? WHERE id = ?", (qty, lens_id))

        # 2. ЗАПИСЫВАЕМ В ФИНАНСЫ КАК РАСХОД (Важно: тип 'расход')
        db.execute("""INSERT INTO finance (type, amount, description, date) 
                      VALUES ('расход', ?, ?, ?)""",
                   (total_loss, f"⚠️ БРАК: {lens['vision']} ({qty} шт.)", today))

        db.commit()
        log_action("Мастер", "БРАК", f"Списано {qty} шт. линзы {lens['vision']}")

        return redirect(url_for('master_dashboard'))
    except Exception as e:
        db.rollback()
        return f"Ошибка: {e}", 500
    finally:
        db.close()

        @app.route("/master/report_defect", methods=["POST"])
        @login_required("master")
        def report_defect():
            db = get_db()
            try:
                lens_id = request.form.get('lens_id')
                qty = int(request.form.get('quantity') or 1)
                reason = request.form.get('reason', 'Без причины')

                # Получаем данные о линзе (оптическую силу и цену)
                lens = db.execute("SELECT vision, price FROM lenses WHERE id = ?", (lens_id,)).fetchone()

                if not lens:
                    return "Линза не найдена", 404

                # Считаем убыток (себестоимость). Если в базе 0, берем среднюю 25000
                cost_per_piece = (lens['price'] or 50000) / 2
                total_loss = cost_per_piece * qty
                today = datetime.now().strftime("%Y-%m-%d")

                # 1. Снимаем со склада
                db.execute("UPDATE lenses SET stock = stock - ? WHERE id = ?", (qty, lens_id))

                # 2. ЗАПИСЫВАЕМ КАК РАСХОД (Чтобы в отчете это был минус)
                db.execute("""
                    INSERT INTO finance (type, amount, description, date) 
                    VALUES ('расход', ?, ?, ?)
                """, (total_loss, f"БРАК: {lens['vision']} ({qty} шт.) - {reason}", today))

                db.commit()
                log_action("Мастер", "Списание брака", f"{lens['vision']} - {qty} шт.")

            except Exception as e:
                db.rollback()
                print(f"Ошибка списания брака: {e}")
            finally:
                db.close()

            return redirect(url_for('master_orders_list'))

# ==========================================
# ЗАПУСК
# ==========================================

if __name__ == "__main__":
    with app.app_context(): # Это добавит стабильности
        init_db()           # База создастся прямо перед стартом
    app.run(debug=True, port=5000)
