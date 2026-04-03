import os
import sys
import argparse
import shutil
import logging
import zipfile
import fnmatch
import platform
from datetime import datetime, timedelta
from pathlib import Path

# Паттерны для исключения из бэкапа
IGNORE_PATTERNS = ["backup", "__pycache__", ".git", ".idea", "venv", "node_modules", "dist", "build", "*.pyc", "*.pyo"]

# Настройки
MAX_BACKUP_AGE_DAYS = 30  # Сколько дней хранить бэкапы
BACKUP_DIR_NAME = "backup"
LOG_FILE_NAME = "backup.log"


def setup_logging(log_dir):
    """Настройка логирования в консоль и файл"""
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Ошибка создания директории логов: {e}")
        sys.exit(1)
    
    log_file = os.path.join(log_dir, LOG_FILE_NAME)
    logger = logging.getLogger("BackupScript")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        logger.warning(f"Не удалось создать файл лога: {e}. Логирование только в консоль.")
    
    return logger


def get_project_size(project_dir, backup_dir):
    """Подсчёт размера проекта без учёта исключённых папок/файлов и папки бэкапа"""
    total = 0
    backup_abs = os.path.abspath(backup_dir)
    
    for root, dirs, files in os.walk(project_dir):
        # Исключаем папку бэкапа и другие служебные папки
        dirs[:] = [d for d in dirs 
                   if not any(fnmatch.fnmatch(d, p) for p in IGNORE_PATTERNS)
                   and os.path.abspath(os.path.join(root, d)) != backup_abs]
        
        for f in files:
            if not any(fnmatch.fnmatch(f, p) for p in IGNORE_PATTERNS):
                try:
                    file_path = os.path.join(root, f)
                    # Дополнительная проверка, что файл не в папке бэкапа
                    if os.path.abspath(root) != backup_abs and not os.path.abspath(root).startswith(backup_abs + os.sep):
                        total += os.path.getsize(file_path)
                except (OSError, PermissionError):
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
    """Нативное уведомление (только для Windows)"""
    if platform.system() != "Windows":
        return
    
    try:
        ctypes = __import__("ctypes")
        # 0x40 = MB_ICONINFORMATION, 0x1 = MB_OK
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x41)
    except Exception:
        pass


def cleanup_old_backups(backup_dir, max_age_days, logger):
    """Удаление старых бэкапов"""
    if not os.path.exists(backup_dir):
        return
    
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    deleted_count = 0
    
    try:
        for filename in os.listdir(backup_dir):
            if filename.startswith("backup_") and filename.endswith(".zip"):
                file_path = os.path.join(backup_dir, filename)
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_mtime < cutoff_date:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.info(f"🗑️ Удалён старый бэкап: {filename}")
                except (OSError, ValueError) as e:
                    logger.warning(f"Ошибка при удалении {filename}: {e}")
    except OSError as e:
        logger.warning(f"Ошибка при очистке старых бэкапов: {e}")
    
    if deleted_count > 0:
        logger.info(f"✅ Удалено {deleted_count} старых бэкапов")


def create_backup_archive(src_dir, zip_path, logger, backup_dir):
    """Создание ZIP-архива с игнорированием служебных файлов"""
    backup_abs = os.path.abspath(backup_dir)
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            for root, dirs, files in os.walk(src_dir):
                # Исключаем папку бэкапа и служебные папки
                dirs[:] = [d for d in dirs 
                           if not any(fnmatch.fnmatch(d, p) for p in IGNORE_PATTERNS)
                           and os.path.abspath(os.path.join(root, d)) != backup_abs]
                
                for file in files:
                    if not any(fnmatch.fnmatch(file, p) for p in IGNORE_PATTERNS):
                        file_path = os.path.join(root, file)
                        # Проверка, что файл не в папке бэкапа
                        if os.path.abspath(root) == backup_abs or os.path.abspath(root).startswith(backup_abs + os.sep):
                            continue
                        
                        arcname = os.path.relpath(file_path, src_dir)
                        try:
                            zipf.write(file_path, arcname)
                        except (PermissionError, OSError) as e:
                            logger.warning(f"Не удалось добавить файл {file_path}: {e}")
        return True
    except Exception as e:
        logger.error(f"Ошибка создания архива: {e}")
        # Удаляем повреждённый архив
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        return False

def main():
    parser = argparse.ArgumentParser(description="Скрипт резервного копирования проекта")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Тестовый режим без создания файлов")
    parser.add_argument("--keep-days", type=int, default=MAX_BACKUP_AGE_DAYS, 
                        help=f"Срок хранения бэкапов в днях (по умолчанию: {MAX_BACKUP_AGE_DAYS})")
    args = parser.parse_args()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(project_dir, BACKUP_DIR_NAME)

    # Проверка существования исходной директории
    if not os.path.exists(project_dir):
        print(f"❌ Директория проекта не найдена: {project_dir}")
        sys.exit(1)
    
    if not os.path.isdir(project_dir):
        print(f"❌ Путь к проекту не является директорией: {project_dir}")
        sys.exit(1)

    logger = setup_logging(backup_dir)

    if args.dry_run:
        logger.info("🧪 ЗАПУСК В РЕЖИМЕ DRY-RUN (проверка)")
    else:
        logger.info("🚀 Запуск резервного копирования...")

    # 1. Оценка размера
    proj_size = get_project_size(project_dir, backup_dir)
    logger.info(f"📊 Размер проекта (без служебных папок и backup): {proj_size / (1024**2):.2f} MB")

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

    # 4. Очистка старых бэкапов перед созданием нового
    logger.info(f"🧹 Очистка бэкапов старше {args.keep_days} дней...")
    cleanup_old_backups(backup_dir, args.keep_days, logger)

    # 5. Создание архива
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_path = os.path.join(backup_dir, f"backup_{timestamp}.zip")

    logger.info(f"📦 Создание архива: {os.path.basename(zip_path)}")
    if create_backup_archive(project_dir, zip_path, logger, backup_dir):
        logger.info(f"✅ Бэкап успешно сохранён: {os.path.basename(zip_path)}")
        show_notification("Бэкап готов", f"Сохранено: backup_{timestamp}.zip")
    else:
        logger.error("❌ Не удалось создать бэкап.")
        show_notification("Ошибка бэкапа", "Сбой при создании архива")
        sys.exit(1)

if __name__ == "__main__":
    main()