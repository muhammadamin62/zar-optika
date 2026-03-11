import sqlite3
import os
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, g
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates')
app.secret_key = "optic_pro_system_2026_key"
# Путь к папке с фото
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'frames')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Проверка и создание папок (рекурсивно)
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# ==========================================
# 1. НАСТРОЙКА БАЗЫ ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Создаем таблицу линз
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vision TEXT NOT NULL,
            lens_type TEXT NOT NULL,
            stock INTEGER DEFAULT 0,
            price INTEGER DEFAULT 0
        )
    ''')

    # Создаем таблицу расходов (для истории закупок)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            amount INTEGER NOT NULL,
            date TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()

def get_db():
    # Создаем соединение с основной базой проекта
    conn = sqlite3.connect('optics_crm.db')
    conn.row_factory = sqlite3.Row # Позволяет обращаться к данным по именам (как к словарю)
    return conn
# Запускаем создание таблиц
def init_db():
    db = get_db()

    # 1. Таблица Оправ
    db.execute("""CREATE TABLE IF NOT EXISTS frames
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, buy_price INTEGER, 
                   sell_price INTEGER, stock INTEGER)""")

    # 2. Таблица Линз
    db.execute("""CREATE TABLE IF NOT EXISTS lenses
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, vision TEXT, lens_type TEXT, 
                   price INTEGER, stock INTEGER)""")

    # 3. Таблица Заказов
    db.execute("""CREATE TABLE IF NOT EXISTS orders
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, customer_phone TEXT,
                   frame_id INTEGER, lens_id_right INTEGER, lens_id_left INTEGER, pd TEXT,
                   total_price INTEGER, status TEXT, date TEXT, is_updated INTEGER DEFAULT 0)""")

    # Попытка добавить колонку, если её нет
    try:
        db.execute("ALTER TABLE orders ADD COLUMN is_updated INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # 4. Таблица Финансов
    db.execute("""CREATE TABLE IF NOT EXISTS finance
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, amount INTEGER, 
                   description TEXT, date TEXT)""")

    # 5. ТАБЛИЦА АКСЕССУАРОВ (Прочие товары) - ТЕПЕРЬ ОНА ТОЧНО СОЗДАСТСЯ
    db.execute("""CREATE TABLE IF NOT EXISTS accessories
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                   category TEXT NOT NULL, 
                   name TEXT NOT NULL, 
                   price INTEGER NOT NULL, 
                   stock INTEGER NOT NULL)""")

    # 6. Журнал активности сотрудников
    db.execute("""CREATE TABLE IF NOT EXISTS activity_log
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      user_role
                      TEXT,
                      action
                      TEXT,
                      details
                      TEXT,
                      date
                      TEXT
                  )""")

    db.commit()
    db.close()
    print("✅ База данных успешно инициализирована!")

# ОБЯЗАТЕЛЬНО ВЫЗЫВАЕМ ЭТУ ФУНКЦИЮ ПОСЛЕ ОПРЕДЕЛЕНИЯ
init_db()

def log_action(user_role, action, details):
    db = get_db()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO activity_log (user_role, action, details, date) VALUES (?, ?, ?, ?)",
               (user_role, action, details, current_time))
    db.commit()
    db.close()

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
@app.context_processor
def inject_notifications():
    try:
        db = get_db()
        low_f = db.execute("SELECT * FROM frames WHERE stock <= 1").fetchall()
        low_l = db.execute("SELECT * FROM lenses WHERE stock <= 3").fetchall()
        count = len(low_f) + len(low_l)
        db.close()
        return dict(low_stock_count=count, low_frames_list=low_f, low_lenses_list=low_l)
    except:
        return dict(low_stock_count=0, low_frames_list=[], low_lenses_list=[])


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
    db = get_db()
    if request.method == "POST":
        try:
            # 1. Базовые данные клиента
            customer_name = request.form.get('customer_name')
            customer_phone = request.form.get('customer_phone')

            # Флаги типов заказа
            is_repair = request.form.get('is_repair') == 'on'
            is_mini_repair = request.form.get('is_mini_repair') == 'on'
            is_client_frame = request.form.get('is_client_frame') == 'on'
            is_special = request.form.get('is_special') == 'true'

            now_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            date_only = datetime.now().strftime("%Y-%m-%d")

            total_income = 0
            recipe = ""
            frame_id = None
            f_name = "Не указана"
            l_price = 0  # Цена линз (для расхода)

            # --- СЦЕНАРИЙ 1: МИНИ-РЕМОНТ ---
            if is_mini_repair:
                total_income = int(request.form.get('mini_repair_price') or 0)
                recipe = f"🛠 МИНИ-РЕМОНТ: {request.form.get('repair_comment')}"
                status = "Выполнено"

            # --- СЦЕНАРИЙ 2: ОБЫЧНЫЙ ЗАКАЗ ИЛИ СЛОЖНЫЙ РЕМОНТ ---
            else:
                status = "Новый"
                work_fee = int(request.form.get('work_price') or 30000)

                # Логика линз
                if not is_repair:
                    l_price = int(request.form.get('custom_lens_price') or 0)
                    pd = request.form.get('pd')
                    if is_special:
                        recipe = f"🌟 СПЕЦ | R:{request.form.get('sph_r')} | L:{request.form.get('sph_l')} | PD:{pd}"
                    else:
                        lens_r = request.form.get('lens_name_right')
                        lens_l = request.form.get('lens_name_left')
                        recipe = f"👓 ОБЫЧНЫЙ | R:{lens_r} | L:{lens_l} | PD:{pd}"
                else:
                    recipe = f"🔧 РЕМОНТ: {request.form.get('repair_comment')}"

                # Логика оправы
                if is_client_frame:
                    f_name = "Оправа клиента"
                    frame_sell_price = 0
                else:
                    f_name = request.form.get('frame_name')
                    frame = db.execute("SELECT id, sell_price, stock FROM frames WHERE name = ?", (f_name,)).fetchone()

                    if not frame:
                        return "Ошибка: Оправа не выбрана", 400
                    if frame['stock'] <= 0:
                        return f"Ошибка: Оправы {f_name} нет в наличии", 400

                    frame_id = frame['id']
                    frame_sell_price = frame['sell_price']
                    db.execute("UPDATE frames SET stock = stock - 1 WHERE id = ?", (frame_id,))

                total_income = frame_sell_price + l_price + work_fee

                # Списание линз из базы (если не спецзаказ и не ремонт)
                if not is_repair and not is_special:
                    for side in ['lens_name_right', 'lens_name_left']:
                        l_name = request.form.get(side)
                        if l_name:
                            db.execute("UPDATE lenses SET stock = stock - 1 WHERE (vision || ' ' || lens_type) = ?",
                                       (l_name,))

            # --- 3. ФИНАНСОВЫЕ ОПЕРАЦИИ ---

            # Запись Заказа
            db.execute("""INSERT INTO orders (customer_name, customer_phone, frame_id, total_price, status, date, comment)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (customer_name, customer_phone, frame_id, total_income, status, now_time, recipe))

            # Запись Прихода (Общая сумма)
            db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('приход', ?, ?, ?)",
                       (total_income, f"Заказ/Услуга: {customer_name} ({f_name})", date_only))

            # Запись Расхода на линзы (50% от их цены продажи, если это был не ремонт)
            if l_price > 0:
                lens_cost = l_price / 2
                db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
                           (lens_cost, f"Закуп линз для {customer_name}", date_only))

            db.commit()
            return redirect(url_for('seller_dashboard'))

        except Exception as e:
            db.rollback()
            return f"Ошибка при создании: {e}"
        finally:
            db.close()

    frames = db.execute("SELECT * FROM frames WHERE stock > 0").fetchall()
    lenses = db.execute("SELECT * FROM lenses WHERE stock > 0").fetchall()
    return render_template("add_order.html", frames=frames, lenses=lenses)
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
        orders = db.execute(query).fetchall()
        db.close()
        return render_template("master_orders.html", orders=orders)
    except Exception as e:
        db.close()
        print(f"Ошибка в мастере: {e}")
        return f"Ошибка базы данных: {e}", 500


@app.route("/master/order/done/<int:order_id>", methods=["POST"])
@login_required("master")
def complete_order(order_id):
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        # Получаем инфо о заказе перед закрытием
        order = db.execute("SELECT comment FROM orders WHERE id = ?", (order_id,)).fetchone()

        # 1. Меняем статус
        db.execute("UPDATE orders SET status = 'Готово' WHERE id = ?", (order_id,))

        # 2. Логика выплаты: если в комментарии есть "МИНИ-РЕМОНТ",
        # можно платить меньше (например, 5000) или оставить 20000
        salary = 20000
        if order and "МИНИ-РЕМОНТ" in order['comment']:
            salary = 5000  # Пример для мелких работ

        db.execute("""INSERT INTO finance (type, amount, description, date) 
                      VALUES ('расход', ?, ?, ?)""",
                   (salary, f"ЗП Мастера: Заказ №{order_id}", today))

        db.commit()
    except Exception as e:
        print(f"Ошибка при завершении: {e}")
        db.rollback()
    finally:
        db.close()
    return redirect(url_for('master_dashboard'))  # Возвращаем на главную мастера
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
        # 1. СБОР ВСЕХ ДЕНЕЖНЫХ ПОТОКОВ
        # Приходы
        total_income = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'приход'").fetchone()[0] or 0
        total_investments = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'вложение'").fetchone()[0] or 0

        # Расходы (Обычные + Регистрация новых линз)
        standard_expenses = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'расход'").fetchone()[0] or 0
        new_lens_costs = db.execute("SELECT SUM(amount) FROM finance WHERE type = 'регистрация'").fetchone()[0] or 0

        # СУММАРНЫЙ РАСХОД (теперь деньги за новые линзы УЧТЕНЫ)
        total_expenses = standard_expenses + new_lens_costs

        # 2. МАТЕМАТИКА ДЛЯ ДАШБОРДА
        net_profit = total_income - total_expenses
        cash_on_hand = (total_income + total_investments) - total_expenses
        active_orders_count = db.execute("SELECT COUNT(*) FROM orders WHERE status != 'Готово'").fetchone()[0]

        # 3. СПИСКИ ДЛЯ ТАБЛИЦ (ИСТОРИЯ)
        # Обычные закупки (где тип 'расход')
        lens_expenses = db.execute("""
            SELECT * FROM finance 
            WHERE type = 'расход' AND (description LIKE 'Закуп%' OR description LIKE 'Линзы%') 
            ORDER BY id DESC LIMIT 5
        """).fetchall()

        # История новых линз (где тип 'регистрация')
        new_lens_history = db.execute("""
            SELECT * FROM finance 
            WHERE type = 'регистрация'
            ORDER BY id DESC LIMIT 10
        """).fetchall()

        # 4. СКЛАД И ТОПЫ
        low_f = db.execute("SELECT name, stock FROM frames WHERE stock <= 1").fetchall()
        low_l = db.execute("SELECT (vision || ' ' || lens_type) as name, stock FROM lenses WHERE stock <= 1").fetchall()
        low_stock = list(low_f) + list(low_l)

        top_frames = db.execute("""
            SELECT f.name, COUNT(o.id) as sales_count
            FROM orders o
            JOIN frames f ON o.frame_id = f.id
            GROUP BY o.frame_id
            ORDER BY sales_count DESC LIMIT 5
        """).fetchall()

        top_others = db.execute("""
            SELECT description, COUNT(*) as sales_count
            FROM finance
            WHERE type = 'приход' AND description LIKE 'Прочее:%'
            GROUP BY description
            ORDER BY sales_count DESC LIMIT 5
        """).fetchall()

        try:
            logs = db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 10").fetchall()
        except:
            logs = []

        return render_template("manager_dashboard.html",
                               income=total_income,
                               investments=total_investments,
                               expenses=total_expenses,
                               net_profit=net_profit,
                               cash_on_hand=cash_on_hand,
                               low_stock=low_stock,
                               active_orders_count=active_orders_count,
                               logs=logs,
                               lens_expenses=lens_expenses,
                               new_lens_history=new_lens_history,  # Отправляем в HTML
                               top_frames=top_frames,
                               top_others=top_others)
    finally:
        db.close()
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
@app.route("/seller/frames/edit/<int:id>", methods=["POST"])
@login_required("seller")
def edit_frame(id):
    db = get_db()
    # Получаем новые данные из полей модального окна
    name = request.form.get('name')
    price = request.form.get('price')
    stock = request.form.get('stock')

    # Обновляем базу данных
    db.execute("""
               UPDATE frames
               SET name       = ?,
                   sell_price = ?,
                   stock      = ?
               WHERE id = ?
               """, (name, price, stock, id))

    db.commit()
    db.close()

    # Возвращаемся обратно на склад по прямому адресу
    return redirect("/seller/frames")


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
        frames_stock = db.execute("SELECT name, stock FROM frames").fetchall()
        lenses_stock = db.execute("SELECT vision, lens_type, stock FROM lenses").fetchall()

        # Запрос с учетом цены линз.
        # Если у тебя в таблице orders нет отдельной колонки lens_price,
        # мы высчитываем её как (Общая цена - Цена оправы - Работа 30к)
        sales = db.execute("""
            SELECT o.id, 
                   o.customer_name, 
                   o.total_price as sell_price, 
                   o.date, 
                   f.name as frame_name, 
                   f.buy_price as frame_cost,
                   f.sell_price as frame_sell,
                   (o.total_price - f.sell_price - 30000) as lens_sell_price,
                   (o.total_price - IFNULL(f.buy_price, 0) - 20000) as net_profit
            FROM orders o
            LEFT JOIN frames f ON o.frame_id = f.id
            WHERE o.date >= ?
            ORDER BY o.date DESC
        """, (start_date,)).fetchall()

        total_revenue = sum(s['sell_price'] for s in sales) if sales else 0
        total_frame_costs = sum(s['frame_cost'] or 0 for s in sales) if sales else 0
        # Считаем общую выручку только за линзы
        total_lens_revenue = sum(max(0, s['lens_sell_price']) for s in sales) if sales else 0
        total_master_fees = len(sales) * 20000
        total_net = total_revenue - total_frame_costs - total_master_fees

    finally:
        db.close()

    return render_template("sales_report.html",
                           sales=sales,
                           frames=frames_stock,
                           lenses=lenses_stock,
                           total_revenue=total_revenue,
                           total_costs=total_frame_costs,
                           total_lens_revenue=total_lens_revenue,  # Передаем в HTML
                           total_master_fees=total_master_fees,
                           total_net=total_net,
                           net_profit=total_net,
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
    month_start = datetime.now().strftime("%Y-%m-01")

    # 1. Считаем реальные продажи (доход от клиентов)
    pure_sales = \
    db.execute("SELECT SUM(amount) FROM finance WHERE type = 'приход' AND date >= ?", (month_start,)).fetchone()[0] or 0

    # 2. Считаем твои личные вложения (пополнение из кармана)
    my_investments = \
    db.execute("SELECT SUM(amount) FROM finance WHERE type = 'вложение' AND date >= ?", (month_start,)).fetchone()[
        0] or 0

    # 3. Считаем все расходы (закуп товара, аренда и т.д.)
    all_costs = \
    db.execute("SELECT SUM(amount) FROM finance WHERE type = 'расход' AND date >= ?", (month_start,)).fetchone()[0] or 0

    # ЛОГИКА ЦИФР:
    # Чистая прибыль = Продажи - Расходы (Вложения тут не считаются доходом!)
    net_profit = pure_sales - all_costs

    # Сейф (Остаток денег на руках) = (Продажи + Вложения) - Расходы
    cash_in_hand = (pure_sales + my_investments) - all_costs

    # Данные для склада
    frames_stock = db.execute("SELECT name, stock FROM frames").fetchall()
    lenses_stock = db.execute("SELECT vision, lens_type, stock FROM lenses").fetchall()

    transactions = db.execute("SELECT * FROM finance WHERE date >= ? ORDER BY date DESC, id DESC",
                              (month_start,)).fetchall()
    db.close()

    return render_template("sales_report.html",
                           frames=frames_stock,
                           lenses=lenses_stock,
                           total_frames=sum(f['stock'] for f in frames_stock),
                           total_lenses=sum(l['stock'] for l in lenses_stock),
                           sales=pure_sales,  # Показываем только продажи
                           investments=my_investments,  # Показываем вложения отдельно
                           costs=all_costs,  # Показываем расходы
                           net_profit=net_profit,  # Реальный плюс/минус бизнеса
                           cash_on_hand=cash_in_hand,  # Сколько физически денег в кассе
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
@login_required("master")
def edit_lens_stock(lens_id):
    db = get_db()
    try:
        new_stock = int(request.form.get('stock') or 0)
        lens = db.execute("SELECT vision, lens_type, stock, price FROM lenses WHERE id = ?", (lens_id,)).fetchone()

        if not lens: return "Error", 404

        old_stock = lens['stock']
        unit_price = lens['price'] if lens['price'] else 0
        cost_per_piece = unit_price / 2

        if new_stock > old_stock:
            added_count = new_stock - old_stock
            total_expense = added_count * cost_per_piece
            if total_expense > 0:
                db.execute("INSERT INTO finance (type, amount, description, date) VALUES ('расход', ?, ?, ?)",
                           (total_expense, f"Пополнение: {lens['vision']} (+{added_count} шт.)",
                            datetime.now().strftime("%Y-%m-%d")))

        db.execute("UPDATE lenses SET stock = ? WHERE id = ?", (new_stock, lens_id))
        db.commit()
        return "OK", 200
    finally:
        db.close()



# ==========================================
# ЗАПУСК
# ==========================================

if __name__ == "__main__":
    with app.app_context(): # Это добавит стабильности
        init_db()           # База создастся прямо перед стартом

    app.run(debug=True, port=5000)
