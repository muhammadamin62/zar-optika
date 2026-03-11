import sqlite3

def add_column():
    conn = sqlite3.connect('optics_crm.db') # Убедись, что имя файла совпадает
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE frames ADD COLUMN photo TEXT DEFAULT 'no_image.png'")
        conn.commit()
        print("✅ Колонка 'photo' успешно добавлена!")
    except sqlite3.OperationalError:
        print("⚠️ Колонка уже существует или таблица не найдена.")
    finally:
        conn.close()

if __name__ == "__main__":
    add_column()