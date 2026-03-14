import sqlite3


def fix_db():
    conn = sqlite3.connect('optics_crm.db')
    cursor = conn.cursor()

    # 1. Сначала посмотрим, как на самом деле записаны типы (для отладки)
    cursor.execute("SELECT DISTINCT type FROM finance")
    types = cursor.fetchall()
    print(f"Сейчас в базе есть такие типы: {types}")

    # 2. Исправляем БРАК, игнорируя регистр букв
    cursor.execute("""
        UPDATE finance 
        SET type = 'расход' 
        WHERE description LIKE '%БРАК%' 
           OR description LIKE '%брак%'
    """)

    count = cursor.rowcount
    conn.commit()
    conn.close()

    print(f"✅ Успешно исправлено записей: {count}")
    print("Теперь обнови страницу отчета в браузере.")


if __name__ == "__main__":
    fix_db()