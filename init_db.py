import sqlite3


def init_db():
    conn = sqlite3.connect('optics.db')
    c = conn.cursor()

    # Пользователи
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (
                     username
                     TEXT
                     PRIMARY
                     KEY,
                     password
                     TEXT,
                     role
                     TEXT
                 )''')

    # Оправы
    c.execute('''CREATE TABLE IF NOT EXISTS frames
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     name
                     TEXT,
                     buy_price
                     INTEGER,
                     sell_price
                     INTEGER,
                     stock
                     INTEGER
                 )''')

    # Линзы
    c.execute('''CREATE TABLE IF NOT EXISTS lenses
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     lens_type
                     TEXT,
                     vision
                     TEXT,
                     price
                     INTEGER,
                     stock
                     INTEGER
                 )''')

    # Заказы
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     frame_name
                     TEXT,
                     lens_type
                     TEXT,
                     vision
                     TEXT,
                     dpp
                     TEXT,
                     total_price
                     INTEGER,
                     status
                     TEXT,
                     date
                     TEXT
                 )''')

    # Финансы
    c.execute('''CREATE TABLE IF NOT EXISTS finance
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     type
                     TEXT,
                     amount
                     INTEGER,
                     description
                     TEXT,
                     date
                     TEXT
                 )''')

    conn.commit()
    conn.close()
    print("База данных создана успешно!")


if __name__ == "__main__":
    init_db()