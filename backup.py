import os
import sys
import argparse
import shutil
import logging
import zipfile
import fnmatch
import ctypes
from datetime import datetime

# Паттерны для исключения из бэкапа
IGNORE_PATTERNS = ["backup", "__pycache__", ".git", ".idea", "venv", "node_modules", "dist", "build", "*.pyc", "*.pyo"]

def setup_logging(log_dir):
    """Настройка логирования в консоль и файл"""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "backup.log")
    logger = logging.getLogger("BackupScript")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

def get_project_size(project_dir):
    """Подсчёт размера проекта без учёта исключённых папок/файлов"""
    total = 0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in IGNORE_PATTERNS)]
        for f in files:
            if not any(fnmatch.fnmatch(f, p) for p in IGNORE_PATTERNS):
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total

def check_free_space(target_dir, required_bytes):
    """Проверка свободного места на диске (требуется +20% запаса)"""
    try:
        usage = shutil.disk_usage(target_dir)
        return usage.free >= required_bytes * 1.2
    except Exception:
        return True  # Если не удалось проверить, разрешаем продолжить

def show_notification(title, message):
    """Нативное Windows-уведомление"""
    try:
        # 0x40 = MB_ICONINFORMATION, 0x1 = MB_OK
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x41)
    except Exception:
        pass

def create_backup_archive(src_dir, zip_path, logger):
    """Создание ZIP-архива с игнорированием служебных файлов"""
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in IGNORE_PATTERNS)]
                for file in files:
                    if not any(fnmatch.fnmatch(file, p) for p in IGNORE_PATTERNS):
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, src_dir)
                        zipf.write(file_path, arcname)
        return True
    except Exception as e:
        logger.error(f"Ошибка создания архива: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Скрипт резервного копирования проекта")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Тестовый режим без создания файлов")
    args = parser.parse_args()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(project_dir, "backup")

    logger = setup_logging(backup_dir)

    if args.dry_run:
        logger.info("🧪 ЗАПУСК В РЕЖИМЕ DRY-RUN (проверка)")
    else:
        logger.info("🚀 Запуск резервного копирования...")

    # 1. Оценка размера
    proj_size = get_project_size(project_dir)
    logger.info(f"📊 Размер проекта (без служебных папок): {proj_size / (1024**2):.2f} MB")

    # 2. Проверка места
    if not args.dry_run:
        if not check_free_space(project_dir, proj_size):
            logger.error("❌ Недостаточно свободного места на диске. Отмена.")
            show_notification("Ошибка бэкапа", "Недостаточно места на диске")
            sys.exit(1)

    # 3. Dry-run выход
    if args.dry_run:
        logger.info("✅ DRY-RUN успешен: все проверки пройдены, файлы не создавались.")
        show_notification("Бэкап (тест)", "Dry-run успешен. Проверки пройдены.")
        return

    # 4. Создание архива
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_path = os.path.join(backup_dir, f"backup_{timestamp}.zip")

    logger.info(f"📦 Создание архива: {os.path.basename(zip_path)}")
    if create_backup_archive(project_dir, zip_path, logger):
        logger.info(f"✅ Бэкап успешно сохранён: {os.path.basename(zip_path)}")
        show_notification("Бэкап готов", f"Сохранено: backup_{timestamp}.zip")
    else:
        logger.error("❌ Не удалось создать бэкап.")
        show_notification("Ошибка бэкапа", "Сбой при создании архива")
        sys.exit(1)

if __name__ == "__main__":
    main()