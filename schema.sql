-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT -- 'seller', 'master', 'manager'
);

-- Склад оправ
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    buy_price INTEGER,
    sell_price INTEGER,
    stock INTEGER DEFAULT 0
);

-- Склад линз
CREATE TABLE IF NOT EXISTS lenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lens_type TEXT, -- 'BlueBlock', 'Photochromic' и т.д.
    vision TEXT,    -- '+2.00', '-1.50'
    price INTEGER,
    stock INTEGER DEFAULT 0
);

-- Заказы
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_name TEXT,
    lens_info TEXT,
    customer_vision TEXT,
    total_price INTEGER,
    status TEXT DEFAULT 'Новый', -- 'Новый', 'В работе', 'Готово'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE orders ADD COLUMN comment TEXT;

-- Финансы (касса)
CREATE TABLE IF NOT EXISTS finance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT, -- 'приход', 'расход'
    amount INTEGER,
    description TEXT,
    date DATE DEFAULT (DATE('now'))
);
CREATE TABLE IF NOT EXISTS accessories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    stock INTEGER NOT NULL
);
ALTER TABLE lenses ADD COLUMN buy_price INTEGER DEFAULT 0;
-- Добавляем колонку для фото в таблицу оправ
ALTER TABLE frames ADD COLUMN photo TEXT DEFAULT 'no_image.png';

-- Добавляем метку "Оправа клиента" в таблицу заказов
ALTER TABLE orders ADD COLUMN is_client_frame BOOLEAN DEFAULT 0;
ALTER TABLE lenses ADD COLUMN buy_price INTEGER DEFAULT 0;
ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'Наличные';
UPDATE finance
SET type = 'расход'
WHERE type = 'вложение' AND description LIKE '%БРАК%';