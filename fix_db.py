import sqlite3

def fix():
    try:
        # Подключаемся к твоей базе
        conn = sqlite3.connect('optics_crm.db')
        cursor = conn.cursor()
        
        # Выполняем команду добавления колонки
        cursor.execute("ALTER TABLE orders ADD COLUMN comment TEXT")
        
        conn.commit()
        print("✅ Успех! Колонка 'comment' добавлена в таблицу orders.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ Колонка уже существует.")
        else:
            print(f"❌ Ошибка: {e}")
    except Exception as e:
        print(f"❌ Что-то пошло не так: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix()