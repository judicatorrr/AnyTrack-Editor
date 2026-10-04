from __future__ import annotations

import html
import math
import sys
import time
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

import numpy as np
import pyqtgraph as pg
try:
    import psutil
except ImportError:  # The UI still starts while first-run dependencies finish installing.
    psutil = None
from PySide6 import QtCore, QtGui, QtWidgets

from . import __version__
from .map_widget import MapWidget
from .telemetry_panels import GraphStack
from .record_index import RecordIndex
from .chart_axes import TimeAxisItem, distance_segments
from .controls import SegmentedControl
from .gps_anomalies import GPSAnomaly, detect_gps_anomalies
from .icons import PATHS as ICON_PATHS, icon as pack_icon
from .local_graphhopper import LOCAL_ROUTE_URL, LocalGraphHopperManager
from .model import ActivityModel, SUPPORTED_EXTENSIONS, export_combined_gpx
from .route_planner import (
    DEFAULT_HOSTED_CREDIT_LIMIT,
    RoutePlannerPanel,
    route_service_requires_key,
)


APP_NAME = "AnyTrack Editor"

GEOFABRIK_RUSSIA_REGIONS = (
    ("northwestern-fed-district", "Северо-Западный ФО", "Northwestern Federal District", 624),
    ("central-fed-district", "Центральный ФО", "Central Federal District", 838),
    ("volga-fed-district", "Приволжский ФО", "Volga Federal District", 738),
    ("south-fed-district", "Южный ФО", "Southern Federal District", 300),
    ("north-caucasus-fed-district", "Северо-Кавказский ФО", "North Caucasus Federal District", 122),
    ("ural-fed-district", "Уральский ФО", "Ural Federal District", 376),
    ("siberian-fed-district", "Сибирский ФО", "Siberian Federal District", 558),
    ("far-eastern-fed-district", "Дальневосточный ФО", "Far Eastern Federal District", 371),
    ("crimean-fed-district", "Крымский ФО", "Crimean Federal District", 39),
    ("kaliningrad", "Калининградская область", "Kaliningrad", 28),
)


def resource_path(relative_path: str) -> Path:
    """Resolve bundled assets both from sources and a PyInstaller package."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative_path


DARK_QSS = """
QMainWindow, QWidget { background: #181c22; color: #e7e9ee; }
QToolBar { background:#20252d; border-bottom:1px solid #353c47; spacing:6px; padding:6px; }
QToolButton, QPushButton, QComboBox { background:#2b313b; border:1px solid #434c59; border-radius:5px; padding:6px 10px; }
QToolButton:hover, QPushButton:hover, QComboBox:hover { background:#353d49; }
QToolButton:disabled, QPushButton:disabled { color:#707781; background:#22272e; }
QComboBox QAbstractItemView, QMenu { background:#2b313b; color:#e7e9ee; selection-background-color:#435166; }
QMenu { border:1px solid #363d49; padding:4px; }
QMenu::item { padding:6px 24px 6px 10px; }
QLabel#title { font-size:18px; font-weight:600; }
QLabel#muted { color:#89909b; }
QLabel#telemetryValues { color:#aeb5c0; }
QLabel#sectionLabel { color:#89909b; font-size:11px; font-weight:600; }
QWidget#statRow, QWidget#statRow QLabel { background:transparent; }
QFrame#card { background:#20252d; border:1px solid #353c47; border-radius:8px; }
QFrame#selectionCard { background:#1c2128; border:1px solid #3b4450; border-radius:7px; }
QFrame#selectionToolbar { background:rgba(32,37,45,245); border:1px solid #566173; border-radius:8px; }
QFrame#selectionToolbar QToolButton { border:none; border-radius:5px; padding:5px 8px; }
QFrame#selectionToolbar QToolButton:hover { background:#343b47; }
QFrame#selectionToolbar QToolButton#selectionCut { color:#ff687d; }
QFrame#activityDropZone { background:#1d2734; border:2px dashed #7c899b; border-radius:10px; }
QFrame#activityDropZone:hover, QFrame#activityDropZone[dragActive="true"] { background:#243247; border-color:#67b7ff; }
QFrame#activityDropZone QLabel { background:transparent; border:none; }
QLabel#dropZoneTitle { color:#e7e9ee; font-size:13px; font-weight:bold; }
QLabel#dropZoneHint { color:#89909b; font-size:11px; }
QToolButton#toolbarIconButton { padding:0; }
QToolButton#historyButton { padding:0; }
QToolButton#offlineMapButton { padding:5px 10px; }
QToolButton#openFileButton { background:#5b5125; border-color:#95843c; }
QToolButton#openFileButton:hover { background:#6a5e2a; }
QToolButton#saveResultButton, QToolButton#convertFileButton { background:#443b55; border-color:#6c5c83; }
QToolButton#saveResultButton:hover, QToolButton#convertFileButton:hover { background:#514665; }
QToolButton#createRouteButton { background:#304c3d; border-color:#4d7b61; }
QToolButton#createRouteButton:hover { background:#395a48; }
QToolButton#checkTrackButton { background:#31495a; border-color:#4f7086; }
QToolButton#checkTrackButton:hover { background:#395568; }
QToolButton#saveResultButton, QToolButton#convertFileButton, QToolButton#createRouteButton, QToolButton#checkTrackButton { font-weight:bold; }
QListWidget { background:#181c22; border:1px solid #353c47; border-radius:5px; outline:0; }
QListWidget::item { padding:5px 4px; border-radius:4px; }
QListWidget::item:selected { background:#303846; color:#ffffff; }
QSlider::groove:horizontal { background:#3a414d; height:5px; border-radius:2px; }
QSlider::sub-page:horizontal { background:#4da3ff; border-radius:2px; }
QSlider::handle:horizontal { background:#e7e9ee; width:14px; margin:-5px 0; border-radius:7px; }
QStatusBar { background:#20252d; color:#b2bac5; }
"""

LIGHT_QSS = """
QMainWindow, QWidget { background: #f4f6f9; color: #17202b; }
QToolBar { background:#ffffff; border-bottom:1px solid #cfd6df; spacing:6px; padding:6px; }
QToolButton, QPushButton, QComboBox { background:#e9edf2; color:#17202b; border:1px solid #b9c2ce; border-radius:5px; padding:6px 10px; }
QToolButton:hover, QPushButton:hover, QComboBox:hover { background:#dde4ec; }
QToolButton:disabled, QPushButton:disabled { color:#98a1ad; background:#edf0f4; }
QComboBox QAbstractItemView, QMenu { background:#ffffff; color:#17202b; selection-background-color:#cfe2f5; }
QMenu { border:1px solid #b9c2ce; padding:4px; }
QMenu::item { padding:6px 24px 6px 10px; }
QLabel#title { font-size:18px; font-weight:600; }
QLabel#muted { color:#657184; }
QLabel#telemetryValues { color:#526071; }
QLabel#sectionLabel { color:#657184; font-size:11px; font-weight:600; }
QWidget#statRow, QWidget#statRow QLabel { background:transparent; }
QFrame#card { background:#ffffff; border:1px solid #cfd6df; border-radius:8px; }
QFrame#selectionCard { background:#f8fafc; border:1px solid #c5ced9; border-radius:7px; }
QFrame#selectionToolbar { background:rgba(255,255,255,245); border:1px solid #aeb9c6; border-radius:8px; }
QFrame#selectionToolbar QToolButton { border:none; border-radius:5px; padding:5px 8px; }
QFrame#selectionToolbar QToolButton:hover { background:#e5ebf2; }
QFrame#selectionToolbar QToolButton#selectionCut { color:#d83f58; }
QFrame#activityDropZone { background:#edf3fa; border:2px dashed #8291a4; border-radius:10px; }
QFrame#activityDropZone:hover, QFrame#activityDropZone[dragActive="true"] { background:#e2f1ff; border-color:#2f7fc4; }
QFrame#activityDropZone QLabel { background:transparent; border:none; }
QLabel#dropZoneTitle { color:#1c2838; font-size:13px; font-weight:bold; }
QLabel#dropZoneHint { color:#657184; font-size:11px; }
QToolButton#toolbarIconButton { padding:0; }
QToolButton#historyButton { padding:0; }
QToolButton#offlineMapButton { padding:5px 10px; }
QToolButton#openFileButton { background:#ffe89a; border-color:#d3b94f; }
QToolButton#openFileButton:hover { background:#ffde72; }
QToolButton#saveResultButton, QToolButton#convertFileButton { background:#e8ddf5; border-color:#baa7d0; }
QToolButton#saveResultButton:hover, QToolButton#convertFileButton:hover { background:#dccbea; }
QToolButton#createRouteButton { background:#d4eadb; border-color:#91bda0; }
QToolButton#createRouteButton:hover { background:#c1dfcb; }
QToolButton#checkTrackButton { background:#d6e7f2; border-color:#92b7ce; }
QToolButton#checkTrackButton:hover { background:#c2dbe9; }
QToolButton#saveResultButton, QToolButton#convertFileButton, QToolButton#createRouteButton, QToolButton#checkTrackButton { font-weight:bold; }
QListWidget { background:#ffffff; border:1px solid #cfd6df; border-radius:5px; outline:0; }
QListWidget::item { padding:5px 4px; border-radius:4px; }
QListWidget::item:selected { background:#d7e8f8; color:#17202b; }
QSlider::groove:horizontal { background:#cbd3dd; height:5px; border-radius:2px; }
QSlider::sub-page:horizontal { background:#2f7fbf; border-radius:2px; }
QSlider::handle:horizontal { background:#17202b; width:14px; margin:-5px 0; border-radius:7px; }
QStatusBar { background:#ffffff; color:#526071; }
"""


METRICS = {
    "speed": {"unit": "km/h", "colour": "#4DA3FF", "factor": 3.6},
    "heart_rate": {"unit": "bpm", "colour": "#FF6178", "factor": 1.0},
    "cadence": {"unit": "rpm", "colour": "#FFD166", "factor": 1.0},
    "power": {"unit": "W", "colour": "#B77BFF", "factor": 1.0},
    "altitude": {"unit": "m", "colour": "#50D890", "factor": 1.0},
}


TRACK_COLOURS = (
    "#50E39C", "#4DA3FF", "#FF6178", "#FFD166",
    "#B77BFF", "#FF9F43", "#45D0E6", "#E76F51",
)


@dataclass
class TrackDocument:
    model: ActivityModel
    colour: str
    visible: bool = True
    timeline_offset: float = 0.0
    timeline_start: float = 0.0
    timeline_end: float = 0.0
    timeline_group: int = 0


def smooth_series(values: np.ndarray, strength: int) -> np.ndarray:
    """Progressive visual low-pass smoothing that keeps missing samples as gaps."""
    source = np.asarray(values, dtype=float)
    if strength <= 0 or len(source) < 3:
        return source.copy()
    result = source.copy()
    valid = np.isfinite(source)
    boundaries = np.flatnonzero(np.diff(np.r_[False, valid, False]))
    kernel = np.array([0.25, 0.5, 0.25], dtype=float)
    for start, end in boundaries.reshape(-1, 2):
        segment = source[start:end].copy()
        if len(segment) < 2:
            continue
        for _ in range(int(strength)):
            segment = np.convolve(np.pad(segment, 1, mode="edge"), kernel, mode="valid")
        result[start:end] = segment
    return result


def display_series(
    x: np.ndarray,
    values: np.ndarray,
    strength: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a continuous visual curve from sparse sensor samples.

    FIT devices commonly omit an unchanged heart-rate value from individual
    RECORD messages. Drawing the raw NaNs makes that valid series look like a
    cloud of tiny dashes. Finite samples are therefore joined inside natural
    recording runs, while genuinely long pauses remain visible as gaps.
    """
    x = np.asarray(x, dtype=float)
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(x) & np.isfinite(values)
    x_valid = x[valid]
    y_valid = values[valid]
    if not len(x_valid):
        return np.array([], dtype=float), np.array([], dtype=float)
    if len(x_valid) == 1:
        return x_valid, y_valid

    positive_steps = np.diff(x_valid)
    positive_steps = positive_steps[positive_steps > 0.0]
    typical_step = float(np.median(positive_steps)) if len(positive_steps) else 1.0
    # Bridge sparse HR/cadence records, but retain a visible break for a real
    # sensor/recording pause. Some FIT devices write unchanged sensor values
    # only every few dozen seconds, so a two-minute floor is intentional.
    maximum_gap = max(120.0, typical_step * 12.0)
    split_at = np.flatnonzero(np.diff(x_valid) > maximum_gap) + 1
    groups = np.split(np.arange(len(x_valid)), split_at)
    plot_x: list[np.ndarray] = []
    plot_y: list[np.ndarray] = []
    for group in groups:
        if not len(group):
            continue
        if plot_x:
            plot_x.append(np.array([math.nan]))
            plot_y.append(np.array([math.nan]))
        plot_x.append(x_valid[group])
        plot_y.append(smooth_series(y_valid[group], strength))
    return np.concatenate(plot_x), np.concatenate(plot_y)


TRANSLATIONS = {
    "ru": {
        "toolbar": "Главная",
        "open": "ОТКРЫТЬ",
        "save": "СОХРАНИТЬ РЕЗУЛЬТАТ",
        "save_hint_single": "Сохранить обработанный трек в исходном формате",
        "save_hint_multiple": "Сохранить активный трек, объединённый GPX или отдельные файлы",
        "convert": "СОХРАНИТЬ В ДРУГОМ ФОРМАТЕ",
        "convert_hint": "Преобразовать активный трек в GPX или TCX",
        "undo": "ОТМЕНА",
        "redo": "ПОВТОРИТЬ",
        "crop": "ОБРЕЗАТЬ",
        "delete": "УДАЛИТЬ ФРАГМЕНТ",
        "drop": "Перетащите сюда файлы FIT, GPX или TCX либо выберите их в панели слева",
        "map": "Карта:",
        "fit_route": "Показать весь маршрут",
        "show": "ПОКАЗАТЬ:",
        "activity": "ТРЕНИРОВКА",
        "tracks": "ТРЕНИРОВКИ",
        "general_stats": "ОБЩАЯ СТАТИСТИКА",
        "selected_stats": "ВЫДЕЛЕННАЯ ОБЛАСТЬ",
        "track_count": "{name}  ·  треков: {count}",
        "track_visibility": "Показывать трек на карте",
        "remove_track": "Удалить трек из списка",
        "track_removed": "Трек «{name}» удалён из списка",
        "telemetry_tracks": "ТРЕКИ",
        "selection": "Выделение",
        "selection_cut": "Удалить",
        "selection_edit": "Редактировать",
        "selection_zoom": "Масштаб",
        "selection_edit_title": "Точные границы выделения",
        "selection_start": "Начало",
        "selection_end": "Конец",
        "selection_time_hint": "Введите время в формате ЧЧ:ММ:СС",
        "selection_time_error": "Проверьте время начала и конца. Конец должен быть позже начала.",
        "smooth": "Плавность",
        "smooth_hint": "Сглаживает только отображение графика; исходные данные не меняются",
        "metric_unavailable": "{metric}: в загруженных треках нет данных",
        "duration": "Длительность",
        "distance": "Расстояние",
        "records": "Точки",
        "avg_hr": "Средний пульс",
        "avg_speed": "Средняя скорость",
        "avg_power": "Средняя мощность",
        "resource_usage": "CPU {cpu:.1f}% · RAM {ram}",
        "resource_tooltip": "Текущее потребление AnyTrack Editor вместе с дочерним процессом локального GraphHopper",
        "local_server_running_short": "Локальный сервер запущен",
        "local_server_stopped_short": "Локальный сервер не запущен",
        "local_server_indicator_hint": "Состояние локального GraphHopper для построения маршрутов без интернета",
        "exit_confirm_title": "Выход из AnyTrack Editor",
        "exit_confirm_text": "Действительно закрыть приложение? Несохранённые изменения будут потеряны.",
        "ready": "Готово",
        "loaded": "Загружено треков: {tracks}; точек: {count}",
        "deleted": "Выбранные точки помечены для удаления",
        "cropped": "Тренировка обрезана до выбранного диапазона",
        "undo_done": "Последнее действие отменено",
        "redo_done": "Последнее действие повторено",
        "undo_hint": "Отменить последнее действие",
        "redo_hint": "Повторить последнее действие",
        "open_title": "Открыть одну или несколько тренировок",
        "open_filter": "Файлы тренировок (*.fit *.gpx *.tcx);;FIT (*.fit);;GPX (*.gpx);;TCX (*.tcx);;Все файлы (*.*)",
        "open_error": "Не удалось открыть файл",
        "drop_zone_title": "Перетащите тренировку сюда",
        "drop_zone_hint": "FIT, GPX или TCX · нажмите для выбора",
        "delete_title": "Удаление фрагмента",
        "delete_all": "Это действие удалит все точки. Операция отменена.",
        "crop_title": "Обрезка",
        "crop_empty": "В выбранном диапазоне нет активных точек.",
        "save_title": "Сохранить отредактированный файл",
        "save_filter": "Файлы {ext} (*.{ext})",
        "save_scope_title": "Что сохранить?",
        "save_scope_text": "Загружено несколько треков. Выберите понятный сценарий экспорта:",
        "save_scope_info": "«Сохранить результат» не объединяет треки автоматически. Выберите режим: один активный трек, единый GPX с сегментами или отдельные файлы. Исходные файлы не изменяются.",
        "save_active": "Только активный трек ({name})",
        "save_combined": "Все треки одним объединённым GPX",
        "save_separate": "Каждый трек отдельным файлом",
        "save_cancel": "Отмена",
        "save_combined_title": "Сохранить объединённый маршрут",
        "save_combined_ok": "Все активные участки сохранены в один GPX-файл.",
        "save_separate_title": "Папка для отдельных файлов",
        "save_separate_ok": "Сохранено отдельных файлов: {count}",
        "save_separate_status": "Сохранено файлов: {count}; папка: {path}",
        "save_none": "Нет активных точек для сохранения.",
        "saved": "Сохранено",
        "saved_ok": "Файл {format} сохранён и успешно проверен.",
        "saved_status": "Сохранено: {path}",
        "validation": "Предупреждение проверки",
        "save_error": "Не удалось сохранить",
        "route_save_title": "Сохранить построенный маршрут",
        "route_save_ok": "Маршрут сохранён в GPX без скорости и временных меток.",
        "convert_title": "Сохранить активный трек в другом формате",
        "convert_filter": "GPX (*.gpx);;TCX (*.tcx)",
        "convert_ok": "Трек преобразован в {format} и сохранён.",
        "convert_same": "Выберите формат, отличный от исходного.",
        "settings": "Настройки",
        "about_title": "О программе",
        "settings_hint": "Язык, оформление и кеш карт",
        "language": "Язык",
        "theme": "Оформление",
        "appearance": "Язык и оформление",
        "general_settings": "Язык, оформление и кеш карт",
        "theme_dark": "Ночной режим",
        "theme_light": "Дневной режим",
        "cache": "Кеш карт",
        "cache_size": "Занято: {size}",
        "cache_clear": "Очистить кеш карт",
        "cache_clear_title": "Очистка кеша",
        "cache_clear_confirm": "Удалить все скачанные карты? Для их повторного просмотра снова потребуется интернет.",
        "cache_cleared": "Кеш карт очищен. Освобождено: {size}.",
        "cache_busy": "Дождитесь окончания загрузки карты.",
        "offline_map": "Скачать карту",
        "offline_map_hint": "Скачать область загруженных маршрутов для работы без интернета",
        "offline_title": "Скачать карту маршрута",
        "offline_text": "Будут скачаны недостающие тайлы выбранной карты вокруг всех видимых маршрутов.",
        "offline_level": "Детализация",
        "offline_fast": "Быстро — текущий масштаб ({count} файлов)",
        "offline_standard": "Стандартно — текущий и следующий ({count} файлов)",
        "offline_detailed": "Подробно — от −1 до +2 уровней ({count} файлов)",
        "offline_too_large": "Для этого режима требуется {count} файлов. Уменьшите детализацию или приблизьте карту к нужному участку.",
        "offline_no_route": "Сначала загрузите трек с GPS-координатами.",
        "offline_cached": "Эта область уже полностью сохранена в кеше.",
        "offline_progress": "Загрузка карты: {done} из {total}",
        "offline_done": "Карта сохранена для работы без интернета: {count} файлов.",
        "offline_done_errors": "Сохранено файлов: {count}; не удалось скачать: {failed}.",
        "gps_check": "ПРОВЕРИТЬ ТРЕК НА ОШИБКИ",
        "gps_check_hint": "Найти GPS-телепорты, аномальную скорость и другие подозрительные точки",
        "gps_title": "Проверка трека на ошибки",
        "gps_no_route": "В активном треке нет достаточного количества GPS-точек.",
        "gps_none": "Подозрительных GPS-скачков и скоростных аномалий не найдено.",
        "gps_no_timing": "Это маршрут без временных меток. Скорость в нём не рассчитывается, поэтому проверка скоростных аномалий не требуется.",
        "gps_found": "Найдено подозрительных участков: {count}. Нажмите красную точку на карте, дважды щёлкните строку или используйте кнопку «Показать на графике».",
        "gps_excursion": "Вылет и возврат",
        "gps_jump": "Резкий переход",
        "gps_speed": "Аномальная скорость",
        "gps_select_all": "Выбрать всё",
        "gps_select_none": "Снять выделение",
        "gps_show": "Показать на графике",
        "gps_remove": "Удалить отмеченные",
        "gps_removed": "Удалено подозрительных GPS-точек: {count}",
        "gps_nothing_selected": "Не выбрано ни одной точки для удаления.",
        "gps_chart_focus": "На графике выделен подозрительный участок: {time}",
        "track_warning_title": "Возможные ошибки в треке",
        "track_warning_count": "Найдено подозрительных участков: {count}",
        "track_warning_found_title": "Что обнаружено",
        "track_warning_found_text": "GPS-телепорты, резкие скачки координат или скорость выше спортивного лимита.",
        "track_warning_safe_title": "Исходный файл не изменён",
        "track_warning_safe_text": "Ни одна точка не удалена автоматически — вы сами решаете, какие данные исправлять.",
        "track_warning_next_title": "Что делать дальше",
        "track_warning_next_text": "Откройте проверку, сравните отмеченные точки с картой и диаграммой, затем выберите нужное действие.",
        "track_warning_review": "Проверить сейчас",
        "track_warning_later": "Позже",
        "create_route": "СОЗДАТЬ МАРШРУТ",
        "create_route_hint": "Построить новый спортивный маршрут через GraphHopper",
        "routing": "Построение маршрутов",
        "routing_source": "Источник маршрутов",
        "routing_cloud": "Облачный сервис",
        "routing_local": "Локальный GraphHopper",
        "routing_url": "Адрес GraphHopper",
        "routing_key": "API-ключ",
        "routing_key_hint": "Для graphhopper.com нужен ключ; локальный open-source сервер работает без него.",
        "routing_key_placeholder": "Вставьте API-ключ GraphHopper",
        "routing_account_links": "<a href='https://graphhopper.com/dashboard/signup'>Зарегистрироваться и получить ключ</a> · <a href='https://graphhopper.com/dashboard/login'>Войти в GraphHopper</a>",
        "credits_title": "Кредиты GraphHopper за сегодня",
        "credits_reset": "Сброс через {time}",
        "credits_value": "{used} / {limit}",
        "credits_percent": "Использовано {percent}% дневного лимита",
        "credits_unknown": "Точный расход появится после ответа GraphHopper. 500 — лимит бесплатного тарифа.",
        "credits_need_key": "Укажите API-ключ, чтобы увидеть облачный лимит.",
        "credits_local": "Локальный GraphHopper: облачные кредиты не применяются.",
        "routing_key_missing_title": "Не указан ключ GraphHopper",
        "routing_key_missing": "Для построения через облачный GraphHopper сначала укажите API-ключ в настройках. Локальный GraphHopper-сервер работает без ключа.",
        "open_settings": "Открыть настройки",
        "local_status": "Состояние локального сервера",
        "local_not_installed": "Компоненты не установлены",
        "local_needs_map": "Выберите карту OpenStreetMap (.osm.pbf)",
        "local_needs_prepare": "Карта выбрана, но база маршрутов ещё не подготовлена",
        "local_needs_rebuild": "База создана без поддержки высоты — подготовьте карту повторно",
        "local_stopped": "Готов к запуску",
        "local_downloading": "Загрузка компонентов…",
        "local_downloading_map": "Загрузка карты OpenStreetMap…",
        "local_extracting": "Распаковка переносимой Java…",
        "local_importing": "Подготовка базы маршрутов…",
        "local_starting": "Запуск локального сервера…",
        "local_stopping": "Остановка локального сервера…",
        "local_running": "Локальный сервер работает · интернет для маршрута не нужен",
        "local_error": "Ошибка локального GraphHopper",
        "local_install": "Установить компоненты",
        "local_installed": "Компоненты установлены",
        "local_install_title": "Установка локального GraphHopper",
        "local_install_confirm": "Скачать GraphHopper и переносимую Java 25? Потребуется примерно 150–250 МБ и подключение к интернету только на время установки.",
        "local_install_hint": "Будут загружены GraphHopper и переносимая Java 25. Карта устанавливается отдельно.",
        "local_map": "02. Карта маршрутизации",
        "local_setup_section": "01. Подключение компонентов",
        "local_prepare_section": "03. Подготовка карты",
        "local_server_section": "Локальный сервер",
        "local_map_none": "Файл .osm.pbf не выбран",
        "local_map_help": "Автоматическая загрузка использует актуальный файл OpenStreetMap с Geofabrik.<br>Можно также <a href='https://download.geofabrik.de/'>скачать другой регион вручную</a>.",
        "local_map_region": "Регион карты",
        "local_download_map": "Скачать карту автоматически",
        "local_download_map_title": "Загрузка карты OpenStreetMap",
        "local_download_map_confirm": "Скачать карту «{region}» с Geofabrik? Приблизительный размер: {size} МБ.",
        "local_download_map_overwrite": "Карта «{region}» уже скачана. Перезаписать файл и затем заново подготовить базу маршрутов?",
        "local_region_downloaded": "✓ {region} — скачано",
        "local_stopping_for_download": "Останавливаю локальный сервер перед загрузкой карты…",
        "local_stop_download_timeout": "Не удалось остановить локальный сервер. Остановите процесс и повторите загрузку.",
        "local_download_progress": "Загрузка карты: {received} из {total}",
        "local_download_progress_unknown": "Загрузка карты: получено {received}",
        "local_delete_map_hint": "Удалить скачанную карту выбранного региона",
        "local_delete_map_title": "Удаление региональной карты",
        "local_delete_map_confirm": "Удалить скачанную карту «{region}»? Если она используется сейчас, подготовленная база маршрутов также будет удалена.",
        "local_delete_map_done": "Карта «{region}» удалена.",
        "local_choose_map": "Выбрать .osm.pbf",
        "local_prepare": "Подготовить карту",
        "local_start": "Запустить",
        "local_stop": "Остановить",
        "local_test": "Проверить",
        "local_open_folder": "Открыть папку данных",
        "local_delete_database": "Удалить базу маршрутов",
        "local_auto_start": "Запускать автоматически вместе с AnyTrack Editor",
        "local_stop_on_exit": "Останавливать при закрытии AnyTrack Editor",
        "local_memory": "Память для импорта",
        "local_memory_hint": "Для выбранной карты рекомендуется не менее {memory} ГБ ОЗУ.",
        "local_memory_no_map": "После выбора карты приложение подскажет рекомендуемый объём памяти для подготовки.",
        "local_size": "Занято локальным модулем: {size}",
        "local_folder": "Папка данных: {path}",
        "local_select_map_title": "Выберите карту OpenStreetMap",
        "local_select_map_filter": "OpenStreetMap PBF (*.osm.pbf)",
        "local_rebuild_title": "Подготовка карты",
        "local_rebuild_confirm": "Существующая база маршрутов будет удалена и создана заново. Продолжить?",
        "local_delete_title": "Удаление базы маршрутов",
        "local_delete_confirm": "Удалить подготовленную базу маршрутов? GraphHopper и исходный .osm.pbf останутся.",
        "local_test_ok": "Локальный GraphHopper отвечает на порту 8989.",
        "local_test_failed": "Локальный GraphHopper сейчас не запущен.",
        "local_setup_required": "Сначала установите компоненты, выберите .osm.pbf и подготовьте карту в настройках.",
        "local_start_required": "Локальный GraphHopper остановлен. Запустите его в настройках или включите автоматический запуск.",
        "local_download_error": "Ошибка локального GraphHopper: {error}",
        "local_log": "Полный журнал: {path}",
        "dialog_close": "Закрыть",
        "note_fit": "При редактировании FIT эта версия изменяет только сообщения RECORD. Полный пересчёт Lap / Session / Activity будет добавлен далее.",
        "note_xml": "GPX и TCX открываются, редактируются и сохраняются в исходном формате. Неизвестные расширения этих XML-форматов пока не сохраняются.",
        "about": "AnyTrack Editor работает с маршрутами FIT, GPX и TCX: показывает карту и показатели тренировки, помогает найти GPS-сбои, удалить лишние точки или целый участок и сохранить готовый результат.\n\nМожно открыть несколько частей одной тренировки, расположить их на общей временной шкале и при необходимости объединить в GPX. Новый маршрут строится по контрольным точкам через настроенный сервис GraphHopper.\n\nОткрытые файлы тренировок обрабатываются локально и не отправляются на сервер; при создании маршрута GraphHopper получает только поставленные на карте контрольные точки.",
        "about_easter_egg": "Если маршрут внезапно ведёт через озеро — возможно, это не приключение, а GPS 🙂",
        "speed": "Скорость",
        "heart_rate": "Пульс",
        "cadence": "Каденс",
        "power": "Мощность",
        "altitude": "Высота",
        "telemetry": "ТЕЛЕМЕТРИЯ",
        "raw_axis": "Значение",
        "time_axis": "Время",
        "cursor": "Курсор",
        "no_values": "Нет данных под курсором",
        "menu_view_all": "Показать весь трек",
        "menu_selection": "Показать выделенный фрагмент",
        "edit_delete": "Удалить фрагмент",
        "edit_crop": "Обрезать",
    },
    "en": {
        "toolbar": "Main",
        "open": "OPEN",
        "save": "SAVE RESULT",
        "save_hint_single": "Save the edited track in its original format",
        "save_hint_multiple": "Save the active track, a combined GPX, or separate files",
        "convert": "SAVE IN ANOTHER FORMAT",
        "convert_hint": "Convert the active track to GPX or TCX",
        "undo": "UNDO",
        "redo": "REDO",
        "crop": "CROP",
        "delete": "DELETE RANGE",
        "drop": "Drop FIT, GPX or TCX files here or select them in the panel on the left",
        "map": "Map:",
        "fit_route": "Fit entire route",
        "show": "SHOW:",
        "activity": "ACTIVITY",
        "tracks": "ACTIVITIES",
        "general_stats": "OVERALL STATISTICS",
        "selected_stats": "SELECTED AREA",
        "track_count": "{name}  ·  tracks: {count}",
        "track_visibility": "Show track on map",
        "remove_track": "Remove track from the list",
        "track_removed": "Track “{name}” removed from the list",
        "telemetry_tracks": "TRACKS",
        "selection": "Selection",
        "selection_cut": "Delete",
        "selection_edit": "Edit",
        "selection_zoom": "Zoom",
        "selection_edit_title": "Exact selection bounds",
        "selection_start": "Start",
        "selection_end": "End",
        "selection_time_hint": "Enter time as HH:MM:SS",
        "selection_time_error": "Check the start and end times. End must be later than start.",
        "smooth": "Smooth",
        "smooth_hint": "Smooths the chart display only; source data is unchanged",
        "metric_unavailable": "{metric}: no data in the loaded tracks",
        "duration": "Duration",
        "distance": "Distance",
        "records": "Points",
        "avg_hr": "Avg HR",
        "avg_speed": "Avg speed",
        "avg_power": "Avg power",
        "resource_usage": "CPU {cpu:.1f}% · RAM {ram}",
        "resource_tooltip": "Current AnyTrack Editor usage including the local GraphHopper child process",
        "local_server_running_short": "Local server is running",
        "local_server_stopped_short": "Local server is not running",
        "local_server_indicator_hint": "Local GraphHopper status for offline route building",
        "exit_confirm_title": "Exit AnyTrack Editor",
        "exit_confirm_text": "Close the application? Unsaved changes will be lost.",
        "ready": "Ready",
        "loaded": "Loaded tracks: {tracks}; points: {count}",
        "deleted": "Selected points marked for deletion",
        "cropped": "Activity cropped to selected range",
        "undo_done": "Last action undone",
        "redo_done": "Last action repeated",
        "undo_hint": "Undo last action",
        "redo_hint": "Redo last action",
        "open_title": "Open one or more activities",
        "open_filter": "Activity files (*.fit *.gpx *.tcx);;FIT (*.fit);;GPX (*.gpx);;TCX (*.tcx);;All files (*.*)",
        "open_error": "Cannot open file",
        "drop_zone_title": "Drop an activity here",
        "drop_zone_hint": "FIT, GPX or TCX · click to browse",
        "delete_title": "Delete range",
        "delete_all": "That would remove all points. The operation was cancelled.",
        "crop_title": "Crop",
        "crop_empty": "The selection contains no active points.",
        "save_title": "Save edited activity",
        "save_filter": "{ext} files (*.{ext})",
        "save_scope_title": "What should be saved?",
        "save_scope_text": "Several tracks are loaded. Choose an explicit export mode:",
        "save_scope_info": "Save Result does not merge tracks automatically. Choose one mode: active track, one GPX with segments, or separate files. Source files are never modified.",
        "save_active": "Active track only ({name})",
        "save_combined": "All tracks as one combined GPX",
        "save_separate": "Every track as a separate file",
        "save_cancel": "Cancel",
        "save_combined_title": "Save combined route",
        "save_combined_ok": "All active ranges were saved as one GPX file.",
        "save_separate_title": "Folder for separate files",
        "save_separate_ok": "Separate files saved: {count}",
        "save_separate_status": "Files saved: {count}; folder: {path}",
        "save_none": "There are no active points to save.",
        "saved": "Saved",
        "saved_ok": "The {format} file was saved and verified successfully.",
        "saved_status": "Saved: {path}",
        "validation": "Validation warning",
        "save_error": "Save failed",
        "route_save_title": "Save planned route",
        "route_save_ok": "The route was saved as GPX without speed or timestamps.",
        "convert_title": "Save active track in another format",
        "convert_filter": "GPX (*.gpx);;TCX (*.tcx)",
        "convert_ok": "Track converted to {format} and saved.",
        "convert_same": "Choose a format different from the source format.",
        "settings": "Settings",
        "about_title": "About",
        "settings_hint": "Language, appearance and map cache",
        "language": "Language",
        "theme": "Appearance",
        "appearance": "Language and appearance",
        "general_settings": "Language, appearance and map cache",
        "theme_dark": "Dark mode",
        "theme_light": "Light mode",
        "cache": "Map cache",
        "cache_size": "Used: {size}",
        "cache_clear": "Clear map cache",
        "cache_clear_title": "Clear cache",
        "cache_clear_confirm": "Delete all downloaded maps? Internet will be required to view them again.",
        "cache_cleared": "Map cache cleared. Freed: {size}.",
        "cache_busy": "Wait until the map download is complete.",
        "offline_map": "Download map",
        "offline_map_hint": "Download the area around loaded routes for offline use",
        "offline_title": "Download route map",
        "offline_text": "Missing tiles from the selected provider around all visible routes will be downloaded.",
        "offline_level": "Detail",
        "offline_fast": "Fast — current zoom ({count} files)",
        "offline_standard": "Standard — current and next zoom ({count} files)",
        "offline_detailed": "Detailed — from −1 to +2 zoom levels ({count} files)",
        "offline_too_large": "This mode requires {count} files. Reduce detail or zoom into the required area.",
        "offline_no_route": "Load a track with GPS coordinates first.",
        "offline_cached": "This area is already fully cached.",
        "offline_progress": "Downloading map: {done} of {total}",
        "offline_done": "Map saved for offline use: {count} files.",
        "offline_done_errors": "Files saved: {count}; downloads failed: {failed}.",
        "gps_check": "CHECK TRACK FOR ERRORS",
        "gps_check_hint": "Find GPS teleports, abnormal speed and other suspicious points",
        "gps_title": "Check track for errors",
        "gps_no_route": "The active track does not contain enough GPS points.",
        "gps_none": "No suspicious GPS jumps or speed anomalies were found.",
        "gps_no_timing": "This route has no timestamps. Its speed is not calculated, so speed-anomaly checking is not required.",
        "gps_found": "Suspicious sections found: {count}. Click a red map marker, double-click a row, or use Show on chart.",
        "gps_excursion": "Excursion and return",
        "gps_jump": "Abrupt transition",
        "gps_speed": "Abnormal speed",
        "gps_select_all": "Select all",
        "gps_select_none": "Clear selection",
        "gps_show": "Show on chart",
        "gps_remove": "Remove checked",
        "gps_removed": "Suspicious GPS points removed: {count}",
        "gps_nothing_selected": "No points are selected for removal.",
        "gps_chart_focus": "Suspicious section selected on chart: {time}",
        "track_warning_title": "Possible track errors",
        "track_warning_count": "Suspicious sections found: {count}",
        "track_warning_found_title": "What was detected",
        "track_warning_found_text": "GPS teleports, abrupt coordinate jumps or speed above the sports limit.",
        "track_warning_safe_title": "The source file is unchanged",
        "track_warning_safe_text": "No point was removed automatically — you decide which data should be corrected.",
        "track_warning_next_title": "What to do next",
        "track_warning_next_text": "Open the review, compare marked points with the map and charts, then choose the appropriate action.",
        "track_warning_review": "Review now",
        "track_warning_later": "Later",
        "create_route": "CREATE ROUTE",
        "create_route_hint": "Build a new sports route with GraphHopper",
        "routing": "Route planning",
        "routing_source": "Routing source",
        "routing_cloud": "Hosted service",
        "routing_local": "Local GraphHopper",
        "routing_url": "GraphHopper URL",
        "routing_key": "API key",
        "routing_key_hint": "graphhopper.com requires a key; a local open-source server does not.",
        "routing_key_placeholder": "Paste the GraphHopper API key",
        "routing_account_links": "<a href='https://graphhopper.com/dashboard/signup'>Sign up and get a key</a> · <a href='https://graphhopper.com/dashboard/login'>Sign in to GraphHopper</a>",
        "credits_title": "Credits used today",
        "credits_reset": "Resets in {time}",
        "credits_value": "{used} / {limit}",
        "credits_percent": "{percent}% of daily limit used",
        "credits_unknown": "Exact usage appears after a GraphHopper response. 500 is the Free plan limit.",
        "credits_need_key": "Add an API key to view the hosted limit.",
        "credits_local": "Local GraphHopper: hosted credits do not apply.",
        "routing_key_missing_title": "GraphHopper key is missing",
        "routing_key_missing": "Add an API key in Settings before using the hosted GraphHopper service. A local GraphHopper server does not require a key.",
        "open_settings": "Open Settings",
        "local_status": "Local server status",
        "local_not_installed": "Components are not installed",
        "local_needs_map": "Select an OpenStreetMap map (.osm.pbf)",
        "local_needs_prepare": "The map is selected, but its route database is not prepared",
        "local_needs_rebuild": "The database has no elevation support — prepare the map again",
        "local_stopped": "Ready to start",
        "local_downloading": "Downloading components…",
        "local_downloading_map": "Downloading OpenStreetMap map…",
        "local_extracting": "Extracting portable Java…",
        "local_importing": "Preparing route database…",
        "local_starting": "Starting local server…",
        "local_stopping": "Stopping local server…",
        "local_running": "Local server is running · route calculation is offline",
        "local_error": "Local GraphHopper error",
        "local_install": "Install components",
        "local_installed": "Components installed",
        "local_install_title": "Install local GraphHopper",
        "local_install_confirm": "Download GraphHopper and portable Java 25? Installation needs about 150–250 MB and internet access only while downloading.",
        "local_install_hint": "GraphHopper and portable Java 25 will be downloaded. Map data is selected separately.",
        "local_map": "02. Routing map",
        "local_setup_section": "01. Install components",
        "local_prepare_section": "03. Prepare map",
        "local_server_section": "Local server",
        "local_map_none": "No .osm.pbf file selected",
        "local_map_help": "Automatic download uses the current OpenStreetMap extract from Geofabrik.<br>You can also <a href='https://download.geofabrik.de/'>download another region manually</a>.",
        "local_map_region": "Map region",
        "local_download_map": "Download map automatically",
        "local_download_map_title": "Download OpenStreetMap map",
        "local_download_map_confirm": "Download “{region}” from Geofabrik? Approximate size: {size} MB.",
        "local_download_map_overwrite": "The “{region}” map is already downloaded. Replace it and then rebuild the route database?",
        "local_region_downloaded": "✓ {region} — downloaded",
        "local_stopping_for_download": "Stopping the local server before downloading the map…",
        "local_stop_download_timeout": "The local server could not be stopped. Stop the process and try the download again.",
        "local_download_progress": "Downloading map: {received} of {total}",
        "local_download_progress_unknown": "Downloading map: {received} received",
        "local_delete_map_hint": "Delete the downloaded map for the selected region",
        "local_delete_map_title": "Delete regional map",
        "local_delete_map_confirm": "Delete the downloaded “{region}” map? If it is currently active, its prepared route database will also be deleted.",
        "local_delete_map_done": "The “{region}” map was deleted.",
        "local_choose_map": "Choose .osm.pbf",
        "local_prepare": "Prepare map",
        "local_start": "Start",
        "local_stop": "Stop",
        "local_test": "Test",
        "local_open_folder": "Open data folder",
        "local_delete_database": "Delete route database",
        "local_auto_start": "Start automatically with AnyTrack Editor",
        "local_stop_on_exit": "Stop when AnyTrack Editor closes",
        "local_memory": "Import memory",
        "local_memory_hint": "At least {memory} GB of RAM is recommended for the selected map.",
        "local_memory_no_map": "After a map is selected, the app will recommend how much memory to use for preparation.",
        "local_size": "Local module size: {size}",
        "local_folder": "Data folder: {path}",
        "local_select_map_title": "Choose an OpenStreetMap map",
        "local_select_map_filter": "OpenStreetMap PBF (*.osm.pbf)",
        "local_rebuild_title": "Prepare map",
        "local_rebuild_confirm": "The existing route database will be deleted and rebuilt. Continue?",
        "local_delete_title": "Delete route database",
        "local_delete_confirm": "Delete the prepared route database? GraphHopper and the source .osm.pbf will remain.",
        "local_test_ok": "Local GraphHopper responds on port 8989.",
        "local_test_failed": "Local GraphHopper is not currently running.",
        "local_setup_required": "Install the components, choose an .osm.pbf file and prepare its map in Settings first.",
        "local_start_required": "Local GraphHopper is stopped. Start it in Settings or enable automatic start.",
        "local_download_error": "Local GraphHopper error: {error}",
        "local_log": "Full log: {path}",
        "dialog_close": "Close",
        "note_fit": "For FIT files this version edits RECORD messages only. Full Lap / Session / Activity recalculation is the next stage.",
        "note_xml": "GPX and TCX can be opened, edited and saved in their original format. Unknown XML extensions are not preserved yet.",
        "about": "AnyTrack Editor works with FIT, GPX and TCX routes: view the map and workout metrics, find GPS faults, remove unwanted points or a whole section, and save the finished result.\n\nYou can open several parts of one workout, arrange them on a shared timeline and combine them as GPX. New routes are built from map waypoints through the configured GraphHopper service.\n\nOpened workout files are processed locally and never uploaded; when creating a route, GraphHopper receives only the waypoints placed on the map.",
        "about_easter_egg": "If the route suddenly crosses a lake, it might be the GPS rather than an adventure 🙂",
        "speed": "Speed",
        "heart_rate": "Heart rate",
        "cadence": "Cadence",
        "power": "Power",
        "altitude": "Altitude",
        "telemetry": "TELEMETRY",
        "raw_axis": "Value",
        "time_axis": "Time",
        "cursor": "Cursor",
        "no_values": "No data at cursor",
        "menu_view_all": "View full track",
        "menu_selection": "View selected range",
        "edit_delete": "Delete range",
        "edit_crop": "Crop",
    },
}


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def fmt_time_long(seconds: float, language: str = "ru") -> str:
    """Human-readable timeline labels that stay compact on chart axes."""
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if language == "en":
        return (f"{hours} h " if hours else "") + f"{minutes:02d} min {seconds:02d} s"
    if hours:
        return f"{hours} ч {minutes:02d} мин {seconds:02d} сек"
    return f"{minutes:02d} мин {seconds:02d} сек"


def _legacy_line_icon(kind: str, colour: str = "#e7e9ee") -> QtGui.QIcon:
    """Fallback for an icon that has not yet moved to the shared SVG pack."""
    pixmap = QtGui.QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(colour), 1.65)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    if kind == "open":
        path = QtGui.QPainterPath(QtCore.QPointF(3.5, 8.0))
        path.lineTo(3.5, 19.0)
        path.lineTo(19.0, 19.0)
        path.lineTo(21.0, 10.0)
        path.lineTo(10.0, 10.0)
        path.lineTo(8.0, 7.0)
        path.lineTo(3.5, 7.0)
        painter.drawPath(path)
    elif kind == "save":
        painter.drawRoundedRect(QtCore.QRectF(4.0, 3.0, 16.0, 18.0), 1.5, 1.5)
        painter.drawRect(QtCore.QRectF(7.0, 3.0, 9.0, 6.0))
        painter.drawRoundedRect(QtCore.QRectF(7.0, 13.0, 10.0, 8.0), 1.2, 1.2)
        painter.drawLine(14.0, 5.0, 14.0, 8.0)
    elif kind == "convert":
        painter.drawLine(3.5, 8.0, 18.0, 8.0)
        painter.drawLine(18.0, 8.0, 14.5, 4.5)
        painter.drawLine(18.0, 8.0, 14.5, 11.5)
        painter.drawLine(20.5, 16.0, 6.0, 16.0)
        painter.drawLine(6.0, 16.0, 9.5, 12.5)
        painter.drawLine(6.0, 16.0, 9.5, 19.5)
    elif kind == "download":
        painter.drawLine(12.0, 3.0, 12.0, 15.0)
        painter.drawLine(7.5, 10.5, 12.0, 15.0)
        painter.drawLine(16.5, 10.5, 12.0, 15.0)
        painter.drawRoundedRect(QtCore.QRectF(4.0, 17.0, 16.0, 4.0), 1.0, 1.0)
    elif kind == "gps_check":
        painter.drawEllipse(QtCore.QRectF(5.0, 5.0, 14.0, 14.0))
        painter.drawEllipse(QtCore.QRectF(9.0, 9.0, 6.0, 6.0))
        painter.drawLine(12.0, 2.5, 12.0, 6.5)
        painter.drawLine(12.0, 17.5, 12.0, 21.5)
        painter.drawLine(2.5, 12.0, 6.5, 12.0)
        painter.drawLine(17.5, 12.0, 21.5, 12.0)
    elif kind == "settings":
        painter.drawEllipse(QtCore.QRectF(8.5, 8.5, 7.0, 7.0))
        painter.drawEllipse(QtCore.QRectF(4.0, 4.0, 16.0, 16.0))
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            painter.drawLine(
                QtCore.QPointF(12 + math.cos(radians) * 8, 12 + math.sin(radians) * 8),
                QtCore.QPointF(12 + math.cos(radians) * 10, 12 + math.sin(radians) * 10),
            )
    elif kind == "help":
        painter.drawEllipse(QtCore.QRectF(4.0, 4.0, 16.0, 16.0))
        path = QtGui.QPainterPath(QtCore.QPointF(8.0, 9.0))
        path.cubicTo(8.5, 5.5, 15.5, 5.5, 16.0, 9.0)
        path.cubicTo(16.3, 11.2, 13.0, 11.8, 12.0, 14.0)
        painter.drawPath(path)
        painter.setBrush(QtGui.QColor(colour))
        painter.drawEllipse(QtCore.QRectF(11.1, 16.5, 1.8, 1.8))
    elif kind in {"undo", "redo"}:
        direction = -1.0 if kind == "undo" else 1.0
        path = QtGui.QPainterPath(QtCore.QPointF(12.0 - direction * 7.0, 7.0))
        path.cubicTo(
            12.0 - direction * 2.0, 4.0,
            12.0 + direction * 7.0, 7.0,
            12.0 + direction * 7.0, 15.0,
        )
        path.cubicTo(
            12.0 + direction * 7.0, 18.0,
            12.0 + direction * 5.0, 20.0,
            12.0 + direction * 2.0, 21.0,
        )
        painter.drawPath(path)
        painter.drawLine(12.0 - direction * 7.0, 7.0, 12.0 - direction * 3.0, 3.5)
        painter.drawLine(12.0 - direction * 7.0, 7.0, 12.0 - direction * 3.0, 10.5)
    elif kind == "crop":
        painter.drawLine(5.0, 3.0, 5.0, 16.5)
        painter.drawLine(5.0, 16.5, 19.0, 16.5)
        painter.drawLine(19.0, 7.5, 19.0, 21.0)
        painter.drawLine(9.0, 7.5, 19.0, 7.5)
    elif kind in {"trash", "delete"}:
        painter.drawRoundedRect(QtCore.QRectF(7.0, 8.0, 10.0, 12.0), 1.5, 1.5)
        painter.drawLine(5.5, 6.0, 18.5, 6.0)
        painter.drawLine(9.0, 4.0, 15.0, 4.0)
        painter.drawLine(10.0, 11.0, 10.0, 17.0)
        painter.drawLine(14.0, 11.0, 14.0, 17.0)
    elif kind == "cycling":
        painter.drawEllipse(QtCore.QRectF(1.5, 12.0, 8.0, 8.0))
        painter.drawEllipse(QtCore.QRectF(14.5, 12.0, 8.0, 8.0))
        path = QtGui.QPainterPath(QtCore.QPointF(5.5, 16.0))
        for x, y in ((9, 8), (15, 8), (11.5, 16), (5.5, 16), (9, 8), (11.5, 16)):
            path.lineTo(x, y)
        painter.drawPath(path)
        painter.drawLine(15, 5, 18.5, 16)
        painter.drawLine(15, 5, 19, 5)
        painter.drawLine(6.5, 6, 11, 6)
    elif kind == "running":
        painter.drawEllipse(QtCore.QRectF(12.5, 2.0, 4.0, 4.0))
        path = QtGui.QPainterPath(QtCore.QPointF(5, 10))
        for x, y in ((9, 7), (13, 9), (16, 13), (21, 12)):
            path.lineTo(x, y)
        painter.drawPath(path)
        painter.drawLine(13, 9, 10, 14)
        painter.drawLine(10, 14, 15, 17)
        painter.drawLine(15, 17, 14, 22)
        painter.drawLine(10, 14, 7, 18)
        painter.drawLine(7, 18, 2, 18)
    elif kind == "scissors":
        painter.drawEllipse(QtCore.QRectF(3.5, 4.0, 5.5, 5.5))
        painter.drawEllipse(QtCore.QRectF(3.5, 14.5, 5.5, 5.5))
        painter.drawLine(8.0, 8.0, 20.5, 18.5)
        painter.drawLine(8.0, 16.0, 20.5, 5.5)
    elif kind == "edit":
        painter.drawRoundedRect(QtCore.QRectF(4.0, 5.0, 14.0, 15.0), 1.5, 1.5)
        painter.drawLine(8.0, 16.0, 18.5, 5.5)
        painter.drawLine(16.0, 4.0, 20.0, 8.0)
        painter.drawLine(7.0, 18.0, 10.0, 17.0)
    elif kind == "zoom":
        painter.drawEllipse(QtCore.QRectF(4.0, 4.0, 12.0, 12.0))
        painter.drawLine(15.0, 15.0, 21.0, 21.0)
        painter.drawLine(7.0, 10.0, 13.0, 10.0)
        painter.drawLine(10.0, 7.0, 10.0, 13.0)
    elif kind == "clock":
        painter.drawEllipse(QtCore.QRectF(3.5, 3.5, 17.0, 17.0))
        painter.drawLine(12.0, 6.5, 12.0, 12.0)
        painter.drawLine(12.0, 12.0, 16.0, 14.0)
    elif kind == "distance":
        painter.drawLine(4.0, 12.0, 20.0, 12.0)
        painter.drawLine(4.0, 12.0, 8.0, 8.0)
        painter.drawLine(4.0, 12.0, 8.0, 16.0)
        painter.drawLine(20.0, 12.0, 16.0, 8.0)
        painter.drawLine(20.0, 12.0, 16.0, 16.0)
    elif kind == "points":
        painter.drawEllipse(QtCore.QRectF(3.5, 9.5, 5.0, 5.0))
        painter.drawEllipse(QtCore.QRectF(9.5, 3.5, 5.0, 5.0))
        painter.drawEllipse(QtCore.QRectF(15.5, 13.5, 5.0, 5.0))
        painter.drawLine(7.5, 10.5, 10.5, 7.5)
        painter.drawLine(13.5, 7.5, 17.5, 14.5)
    elif kind == "heart":
        path = QtGui.QPainterPath(QtCore.QPointF(12.0, 20.0))
        path.cubicTo(10.0, 17.5, 4.0, 14.0, 4.0, 8.5)
        path.cubicTo(4.0, 3.5, 10.0, 3.0, 12.0, 7.0)
        path.cubicTo(14.0, 3.0, 20.0, 3.5, 20.0, 8.5)
        path.cubicTo(20.0, 14.0, 14.0, 17.5, 12.0, 20.0)
        painter.drawPath(path)
    elif kind == "speed":
        painter.drawArc(QtCore.QRectF(4.0, 5.0, 16.0, 16.0), 20 * 16, 140 * 16)
        painter.drawLine(12.0, 13.0, 18.0, 8.0)
        painter.drawEllipse(QtCore.QRectF(10.8, 11.8, 2.4, 2.4))
    elif kind == "power":
        path = QtGui.QPainterPath(QtCore.QPointF(13.5, 2.5))
        path.lineTo(6.5, 13.0)
        path.lineTo(11.0, 13.0)
        path.lineTo(9.5, 21.5)
        path.lineTo(17.5, 10.0)
        path.lineTo(13.0, 10.0)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "language":
        painter.drawEllipse(QtCore.QRectF(3.5, 3.5, 17.0, 17.0))
        painter.drawArc(QtCore.QRectF(8.0, 3.5, 8.0, 17.0), 90 * 16, 180 * 16)
        painter.drawArc(QtCore.QRectF(8.0, 3.5, 8.0, 17.0), 270 * 16, 180 * 16)
        painter.drawLine(4.5, 9.0, 19.5, 9.0)
        painter.drawLine(4.5, 15.0, 19.5, 15.0)
    elif kind == "theme":
        path = QtGui.QPainterPath(QtCore.QPointF(16.5, 3.5))
        path.cubicTo(9.0, 4.0, 6.0, 9.0, 8.0, 14.0)
        path.cubicTo(9.8, 18.5, 14.5, 20.0, 19.5, 17.0)
        path.cubicTo(13.0, 17.0, 10.5, 9.0, 16.5, 3.5)
        painter.drawPath(path)
    elif kind == "cache":
        painter.drawEllipse(QtCore.QRectF(4.0, 4.0, 16.0, 6.0))
        painter.drawArc(QtCore.QRectF(4.0, 8.0, 16.0, 6.0), 180 * 16, 180 * 16)
        painter.drawArc(QtCore.QRectF(4.0, 13.0, 16.0, 6.0), 180 * 16, 180 * 16)
        painter.drawLine(4.0, 7.0, 4.0, 16.0)
        painter.drawLine(20.0, 7.0, 20.0, 16.0)
    elif kind == "layout_vertical":
        painter.drawRoundedRect(QtCore.QRectF(4.0, 3.0, 16.0, 7.0), 1.0, 1.0)
        painter.drawRoundedRect(QtCore.QRectF(4.0, 14.0, 16.0, 7.0), 1.0, 1.0)
        painter.drawLine(8.0, 6.5, 16.0, 6.5)
        painter.drawLine(8.0, 17.5, 16.0, 17.5)
    elif kind == "layout_horizontal":
        painter.drawRoundedRect(QtCore.QRectF(3.0, 4.0, 7.0, 16.0), 1.0, 1.0)
        painter.drawRoundedRect(QtCore.QRectF(14.0, 4.0, 7.0, 16.0), 1.0, 1.0)
        painter.drawLine(6.5, 8.0, 6.5, 16.0)
        painter.drawLine(17.5, 8.0, 17.5, 16.0)
    elif kind == "fit":
        painter.drawLine(4.0, 9.0, 4.0, 4.0)
        painter.drawLine(4.0, 4.0, 9.0, 4.0)
        painter.drawLine(15.0, 4.0, 20.0, 4.0)
        painter.drawLine(20.0, 4.0, 20.0, 9.0)
        painter.drawLine(4.0, 15.0, 4.0, 20.0)
        painter.drawLine(4.0, 20.0, 9.0, 20.0)
        painter.drawLine(15.0, 20.0, 20.0, 20.0)
        painter.drawLine(20.0, 20.0, 20.0, 15.0)

    painter.end()
    return QtGui.QIcon(pixmap)


def line_icon(kind: str, colour: str = "#e7e9ee") -> QtGui.QIcon:
    return pack_icon(kind, colour) if kind in ICON_PATHS else _legacy_line_icon(kind, colour)


class OutlinedCheckBox(QtWidgets.QCheckBox):
    """Checkbox whose indicator remains legible with every native Qt theme."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        font = QtGui.QFont(self.font())
        font.setPointSizeF(max(10.5, font.pointSizeF() + 1.0))
        self.setFont(font)
        self.setMinimumHeight(28)
        self.set_theme("dark")

    def set_theme(self, theme: str) -> None:
        if theme == "light":
            self._indicator_background = QtGui.QColor("#ffffff")
            self._indicator_border = QtGui.QColor("#77879a")
            self._indicator_checked = QtGui.QColor("#2f7fc4")
        else:
            self._indicator_background = QtGui.QColor("#111820")
            self._indicator_border = QtGui.QColor("#91a1b5")
            self._indicator_checked = QtGui.QColor("#4ba8ff")
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        painter = QtWidgets.QStylePainter(self)
        painter.drawControl(QtWidgets.QStyle.ControlElement.CE_CheckBox, option)
        indicator = self.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_CheckBoxIndicator, option, self
        ).adjusted(0, 0, -1, -1)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QtGui.QPen(self._indicator_border, 1.4))
        painter.setBrush(
            self._indicator_checked if self.isChecked() else self._indicator_background
        )
        painter.drawRoundedRect(QtCore.QRectF(indicator), 3.0, 3.0)
        if self.isChecked():
            painter.setPen(QtGui.QPen(
                QtGui.QColor("#ffffff"), 2.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            ))
            left = indicator.left() + indicator.width() * 0.23
            middle_x = indicator.left() + indicator.width() * 0.44
            middle_y = indicator.top() + indicator.height() * 0.66
            painter.drawLine(
                QtCore.QPointF(left, indicator.top() + indicator.height() * 0.50),
                QtCore.QPointF(middle_x, middle_y),
            )
            painter.drawLine(
                QtCore.QPointF(middle_x, middle_y),
                QtCore.QPointF(
                    indicator.left() + indicator.width() * 0.79,
                    indicator.top() + indicator.height() * 0.31,
                ),
            )


class SetupStepsCard(QtWidgets.QFrame):
    """Settings card that visually connects its numbered setup stages."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._step_icons: list[QtWidgets.QWidget] = []
        self._step_line_colour = QtGui.QColor("#4ba8ff")

    def set_step_icons(self, icons: list[QtWidgets.QWidget]) -> None:
        self._step_icons = list(icons)
        self.update()

    def set_step_line_colour(self, colour: str) -> None:
        self._step_line_colour = QtGui.QColor(colour)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        if len(self._step_icons) < 2:
            return
        centres = [
            icon.mapTo(self, icon.rect().center()) for icon in self._step_icons
            if icon.isVisible()
        ]
        if len(centres) < 2:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(self._step_line_colour, 2.0)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rail_x = min(point.x() for point in centres) - 12
        painter.drawLine(
            QtCore.QPointF(rail_x, centres[0].y()),
            QtCore.QPointF(rail_x, centres[-1].y()),
        )
        painter.setBrush(self._step_line_colour)
        for point in centres:
            painter.drawEllipse(QtCore.QPointF(rail_x, point.y()), 3.2, 3.2)


class ActivityDropZone(QtWidgets.QFrame):
    """Visible file target that also opens the native file picker on click."""

    filesDropped = QtCore.Signal(list)
    browseRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("activityDropZone")
        self.setAcceptDrops(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setProperty("dragActive", False)
        self.setMinimumHeight(104)
        self.setMaximumHeight(116)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title_label = QtWidgets.QLabel()
        self.title_label.setObjectName("dropZoneTitle")
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.hint_label = QtWidgets.QLabel()
        self.hint_label.setObjectName("dropZoneHint")
        self.hint_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)

    @staticmethod
    def accepted_paths(urls: list[QtCore.QUrl]) -> list[str]:
        return [
            url.toLocalFile() for url in urls
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS
        ]

    def set_texts(self, title: str, hint: str) -> None:
        self.title_label.setText(title)
        self.hint_label.setText(hint)

    def set_theme(self, theme: str) -> None:
        colour = "#526071" if theme == "light" else "#aab5c4"
        self.icon_label.setPixmap(line_icon("upload", colour).pixmap(32, 32))

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.browseRequested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self.accepted_paths(event.mimeData().urls()):
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self._set_drag_active(False)
        paths = self.accepted_paths(event.mimeData().urls())
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()


class TrackWarningDialog(QtWidgets.QDialog):
    """Structured warning shown after suspicious GPS data is loaded."""

    def __init__(
        self,
        count: int,
        text: dict[str, str],
        theme: str,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("trackWarningDialog")
        self.setWindowTitle(text["track_warning_title"])
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMaximumWidth(680)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        heading = QtWidgets.QHBoxLayout()
        heading.setSpacing(12)
        icon_label = QtWidgets.QLabel()
        icon_label.setFixedSize(42, 42)
        icon_label.setPixmap(line_icon("track_check", "#ffb547").pixmap(38, 38))
        icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        heading_text = QtWidgets.QVBoxLayout()
        heading_text.setSpacing(2)
        title = QtWidgets.QLabel(text["track_warning_title"])
        title.setObjectName("warningHeading")
        count_label = QtWidgets.QLabel(text["track_warning_count"].format(count=count))
        count_label.setObjectName("warningCount")
        heading_text.addWidget(title)
        heading_text.addWidget(count_label)
        heading.addWidget(icon_label)
        heading.addLayout(heading_text, 1)
        layout.addLayout(heading)

        rows = (
            ("speed", text["track_warning_found_title"], text["track_warning_found_text"], "#ff7185"),
            ("save", text["track_warning_safe_title"], text["track_warning_safe_text"], "#55c987"),
            ("track_check", text["track_warning_next_title"], text["track_warning_next_text"], "#5bb1ff"),
        )
        for index, (icon_kind, row_title, body, colour) in enumerate(rows):
            if index:
                divider = QtWidgets.QFrame()
                divider.setObjectName("warningDivider")
                divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                layout.addWidget(divider)
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(12)
            row_icon = QtWidgets.QLabel()
            row_icon.setFixedSize(28, 28)
            row_icon.setPixmap(line_icon(icon_kind, colour).pixmap(24, 24))
            row_icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter)
            copy = QtWidgets.QVBoxLayout()
            copy.setSpacing(3)
            row_heading = QtWidgets.QLabel(row_title)
            row_heading.setObjectName("warningRowTitle")
            row_body = QtWidgets.QLabel(body)
            row_body.setObjectName("warningRowBody")
            row_body.setWordWrap(True)
            copy.addWidget(row_heading)
            copy.addWidget(row_body)
            row.addWidget(row_icon)
            row.addLayout(copy, 1)
            layout.addLayout(row)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.later_button = QtWidgets.QPushButton(text["track_warning_later"])
        self.review_button = QtWidgets.QPushButton(text["track_warning_review"])
        self.review_button.setObjectName("warningReviewButton")
        self.review_button.setDefault(True)
        self.later_button.clicked.connect(self.reject)
        self.review_button.clicked.connect(self.accept)
        buttons.addWidget(self.later_button)
        buttons.addWidget(self.review_button)
        layout.addLayout(buttons)

        if theme == "light":
            muted, divider, accent = "#5f6d7c", "#d5dbe3", "#287bc1"
        else:
            muted, divider, accent = "#aab5c4", "#3d4652", "#4ba8ff"
        self.setStyleSheet(
            "QLabel#warningHeading { font-size:18px; font-weight:700; }"
            f"QLabel#warningCount {{ color:{accent}; font-size:14px; font-weight:650; }}"
            "QLabel#warningRowTitle { font-size:13px; font-weight:700; }"
            f"QLabel#warningRowBody {{ color:{muted}; }}"
            f"QFrame#warningDivider {{ color:{divider}; background:{divider}; max-height:1px; border:none; }}"
            f"QPushButton#warningReviewButton {{ background:{accent}; color:white; border-color:{accent}; font-weight:700; }}"
        )


class StatRow(QtWidgets.QWidget):
    """One precisely aligned icon/value/caption row."""

    def __init__(self, compact: bool = False, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statRow")
        self._compact = compact
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 1 if compact else 3, 0, 1 if compact else 3)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(0)

        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setFixedSize(25, 30 if compact else 38)
        self.icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.icon_label, 0, 0, 2, 1)

        self.value_label = QtWidgets.QLabel()
        self.value_label.setStyleSheet(
            f"font-size:{15 if compact else 18}px; font-weight:700; color:#f4f6fa;"
        )
        layout.addWidget(self.value_label, 0, 1)

        self.caption_label = QtWidgets.QLabel()
        self.caption_label.setStyleSheet("font-size:11px; color:#89909b;")
        layout.addWidget(self.caption_label, 1, 1)
        layout.setColumnStretch(1, 1)

    def set_stat(self, icon: str, colour: str, caption: str, value: str) -> None:
        if getattr(self, "_icon_key", None) != (icon, colour):
            self.icon_label.setPixmap(line_icon(icon, colour).pixmap(QtCore.QSize(20, 20)))
            self._icon_key = (icon, colour)
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self.show()


class StatsPanel(QtWidgets.QWidget):
    """Reusable fixed-grid statistics block; icons share one guide column."""

    def __init__(self, compact: bool = False, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rows = [StatRow(compact, self) for _ in range(9)]
        for row in self._rows:
            self._layout.addWidget(row)
        self.clear()

    def set_stats(self, stats: list[tuple[str, str, str, str]]) -> None:
        for row, values in zip(self._rows, stats):
            row.set_stat(*values)
        for row in self._rows[len(stats):]:
            row.hide()

    def clear(self) -> None:
        for row in self._rows:
            row.hide()


class TrackListRow(QtWidgets.QWidget):
    """Compact activity row with map visibility and remove controls."""

    visibilityChanged = QtCore.Signal(bool)
    removeRequested = QtCore.Signal()
    activated = QtCore.Signal()

    def __init__(self, name: str, colour: str, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("trackRow")
        self.setStyleSheet(
            "QWidget#trackRow, QWidget#trackRow QLabel { background:transparent; }"
            "QToolButton#trackRemove { background:transparent; border:none; padding:3px; border-radius:5px; }"
            "QToolButton#trackRemove:hover { background:#4b2930; }"
        )
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 3, 2)
        layout.setSpacing(6)

        self.visibility_box = QtWidgets.QCheckBox()
        self.visibility_box.setChecked(True)
        self.visibility_box.setStyleSheet("QCheckBox { background:transparent; padding:0; }")
        layout.addWidget(self.visibility_box)

        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(12, 12)
        self.swatch.setStyleSheet(
            f"background:{colour}; border:1px solid #0f1115; border-radius:3px;"
        )
        self.swatch.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.swatch)

        self.name_label = QtWidgets.QLabel(name)
        self.name_label.setToolTip(name)
        self.name_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.name_label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.name_label, 1)

        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setObjectName("trackRemove")
        self.remove_button.setAutoRaise(True)
        self.remove_button.setFixedSize(26, 26)
        self.remove_button.setIcon(line_icon("trash", "#b8bec8"))
        self.remove_button.setIconSize(QtCore.QSize(16, 16))
        layout.addWidget(self.remove_button)

        self.visibility_box.toggled.connect(self.visibilityChanged)
        self.remove_button.clicked.connect(self.removeRequested)

    def set_active(self, active: bool) -> None:
        font = self.name_label.font()
        font.setWeight(QtGui.QFont.Weight.DemiBold if active else QtGui.QFont.Weight.Normal)
        self.name_label.setFont(font)

    def set_language(self, visibility_tooltip: str, remove_tooltip: str) -> None:
        self.visibility_box.setToolTip(visibility_tooltip)
        self.visibility_box.setAccessibleName(visibility_tooltip)
        self.remove_button.setToolTip(remove_tooltip)
        self.remove_button.setAccessibleName(remove_tooltip)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mousePressEvent(event)


class TelemetryViewBox(pg.ViewBox):
    """ViewBox with a tiny context menu translated by the application."""

    def __init__(self, owner: "MainWindow"):
        super().__init__(enableMenu=True)
        self.owner = owner
        self._menu: QtWidgets.QMenu | None = None
        # Wheel and drag interaction must only change the time axis. The value
        # scale remains fixed, so zoom behaves like a timeline rather than a photo.
        self.setMouseEnabled(x=True, y=False)

    def wheelEvent(self, event, axis=None):
        # Even a wheel event over a value axis must only zoom time.
        super().wheelEvent(event, axis=0)

    def raiseContextMenu(self, event) -> None:  # noqa: N802 - Qt/pyqtgraph API name
        menu = QtWidgets.QMenu()
        view_all = menu.addAction(self.owner.tr("menu_view_all"))
        selected = menu.addAction(self.owner.tr("menu_selection"))
        view_all.triggered.connect(self.owner.reset_telemetry_view)
        selected.triggered.connect(self.owner.zoom_to_selection)
        self._menu = menu
        menu.popup(event.screenPos().toPoint())


class MaskEditCommand(QtGui.QUndoCommand):
    def __init__(
        self,
        window: "MainWindow",
        model: ActivityModel,
        before: np.ndarray,
        after: np.ndarray,
        text: str,
    ):
        super().__init__(text)
        self.window = window
        self.model = model
        self.before = before.copy()
        self.after = after.copy()

    def undo(self) -> None:
        self.window._apply_mask(self.model, self.before)

    def redo(self) -> None:
        self.window._apply_mask(self.model, self.after)


class MultiMaskEditCommand(QtGui.QUndoCommand):
    """Apply one montage edit to every affected source without redraw churn."""

    def __init__(
        self,
        window: "MainWindow",
        changes: list[tuple[ActivityModel, np.ndarray, np.ndarray]],
        text: str,
    ):
        super().__init__(text)
        self.window = window
        self.changes = [
            (model, before.copy(), after.copy())
            for model, before, after in changes
        ]

    def _apply(self, use_after: bool) -> None:
        for model, before, after in self.changes:
            model.active = (after if use_after else before).copy()
        self.window.refresh_plots(reset_region=True, fit_map=True)

    def undo(self) -> None:
        self._apply(False)

    def redo(self) -> None:
        self._apply(True)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings("VJ Ostrov", "Track Editor")
        self.language = str(self.settings.value("language", "ru"))
        if self.language not in TRANSLATIONS:
            self.language = "ru"
        self.theme = str(self.settings.value("theme", "dark"))
        if self.theme not in {"dark", "light"}:
            self.theme = "dark"
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1380, 900)
        self.setAcceptDrops(True)
        self.tracks: list[TrackDocument] = []
        self.active_track_index = -1
        self._regions: list[pg.LinearRegionItem] = []
        self._telemetry_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._telemetry_plot_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._telemetry_gps: tuple[np.ndarray, np.ndarray, np.ndarray] = (
            np.array([]), np.array([]), np.array([])
        )
        self._telemetry_by_track: dict[
            int, dict[str, tuple[np.ndarray, np.ndarray]]
        ] = {}
        self._telemetry_plot_by_track: dict[
            int, dict[str, tuple[np.ndarray, np.ndarray]]
        ] = {}
        self._telemetry_gps_by_track: dict[
            int, tuple[np.ndarray, np.ndarray, np.ndarray]
        ] = {}
        self._timeline_order: list[int] = []
        self._timeline_separators: list[float] = []
        self._telemetry_duration = 1.0
        self._cursor_line: pg.InfiniteLine | None = None
        self._cursor_points: pg.ScatterPlotItem | None = None
        self._metric_preferences = {field: True for field in METRICS}
        self._selection_drag_start: float | None = None
        self._selection_drag_mode: str | None = None
        self._selection_drag_initial_region: tuple[float, float] | None = None
        self._selection_user_defined = False
        self._record_indices = {}
        self._smooth_cache = {}
        self._selection_refresh_timer = QtCore.QTimer(self)
        self._selection_refresh_timer.setSingleShot(True)
        self._selection_refresh_timer.setInterval(33)
        self._selection_refresh_timer.timeout.connect(self._refresh_selection_details)
        self._smooth_timer = QtCore.QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(80)
        self._smooth_timer.timeout.connect(self._apply_smoothing)
        self.undo_stack = QtGui.QUndoStack(self)
        self.local_graphhopper = LocalGraphHopperManager(self.settings, self)
        self._route_panel: RoutePlannerPanel | None = None
        self._route_draft_state: dict = {}
        self._route_layout_state: tuple[list[int], list[int]] | None = None
        self._build_ui()
        self._setup_resource_monitor()
        self.apply_theme(self.theme, persist=False)
        self._retranslate_ui()
        self._set_loaded(False)
        QtCore.QTimer.singleShot(350, self._maybe_start_local_graphhopper)

    def tr(self, key: str, **values: object) -> str:
        return TRANSLATIONS[self.language][key].format(**values)

    @staticmethod
    def _human_size(size: int) -> str:
        value = float(max(0, size))
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024.0 or unit == "GB":
                return f"{value:.0f} {unit}" if unit in {"B", "KB"} else f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{value:.1f} GB"

    def _setup_resource_monitor(self) -> None:
        self.local_server_indicator = QtWidgets.QLabel()
        self.local_server_indicator.setObjectName("localServerIndicator")
        self.local_server_indicator.setMinimumWidth(230)
        self.local_server_indicator.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.statusBar().addPermanentWidget(self.local_server_indicator)
        self.resource_usage_label = QtWidgets.QLabel("CPU — · RAM —")
        self.resource_usage_label.setObjectName("resourceUsage")
        self.resource_usage_label.setMinimumWidth(150)
        self.resource_usage_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.statusBar().addPermanentWidget(self.resource_usage_label)
        try:
            self._resource_process = psutil.Process() if psutil is not None else None
        except (psutil.Error, OSError):
            self._resource_process = None
        self._resource_known_processes: dict[int, object] = {}
        self._resource_timer = QtCore.QTimer(self)
        self._resource_timer.setInterval(1500)
        self._resource_timer.timeout.connect(self._update_resource_usage)
        self._resource_timer.start()
        self._update_local_server_indicator()
        self._update_resource_usage()

    def _update_local_server_indicator(self, running: bool | None = None) -> None:
        if not hasattr(self, "local_server_indicator"):
            return
        if running is None:
            running = self.local_graphhopper.is_running()
        dot_colour = "#4fd17b" if running else "#ff5f73"
        text_colour = "#526071" if self.theme == "light" else "#b8c1cc"
        label = self.tr(
            "local_server_running_short" if running else "local_server_stopped_short"
        )
        self.local_server_indicator.setText(
            f'<span style="color:{dot_colour}; font-size:15px;">●</span>'
            f'&nbsp;<span style="color:{text_colour};">{label}</span>'
        )
        self.local_server_indicator.setStyleSheet(
            "font-weight:650; color:#62d28d; padding:0 8px;"
            if running else "font-weight:650; color:#ff7487; padding:0 8px;"
        )

    def _update_resource_usage(self) -> None:
        self._update_local_server_indicator()
        if psutil is None or self._resource_process is None:
            self.resource_usage_label.setText("CPU — · RAM —")
            return
        try:
            processes = [self._resource_process, *self._resource_process.children(recursive=True)]
            alive: dict[int, psutil.Process] = {}
            cpu = 0.0
            memory = 0
            for discovered in processes:
                try:
                    process = self._resource_known_processes.get(discovered.pid, discovered)
                    alive[process.pid] = process
                    # The first call primes psutil and returns zero; subsequent
                    # timer ticks contain the real interval usage.
                    cpu += float(process.cpu_percent(interval=None))
                    memory += int(process.memory_info().rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self._resource_known_processes = alive
            self.resource_usage_label.setText(self.tr(
                "resource_usage", cpu=cpu, ram=self._human_size(memory)
            ))
        except (psutil.Error, OSError):
            self.resource_usage_label.setText("CPU — · RAM —")

    def _metric_button_style(self, colour: str) -> str:
        neutral = "#eef1f5" if self.theme == "light" else "#20242c"
        disabled = "#e2e6eb" if self.theme == "light" else "#191c21"
        disabled_text = "#8d97a5" if self.theme == "light" else "#666d78"
        return (
            f"QToolButton {{ color:{colour}; background:{neutral}; border:1px solid {colour}; "
            "border-radius:14px; padding:5px 10px; font-weight:600; }"
            f"QToolButton:checked {{ color:#ffffff; background:{colour}; border-color:{colour}; }}"
            "QToolButton:enabled:hover { border-width:2px; padding:4px 9px; }"
            f"QToolButton:disabled, QToolButton:checked:disabled {{ color:{disabled_text}; "
            f"background:{disabled}; border:1px solid #aeb6c1; }}"
        )

    def apply_theme(self, theme: str, *, persist: bool = True) -> None:
        self.theme = "light" if theme == "light" else "dark"
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.setStyleSheet(LIGHT_QSS if self.theme == "light" else DARK_QSS)
        if hasattr(self, "graph_stack"):
            self.graph_stack.set_theme(self.theme)
        if hasattr(self, "map_widget"):
            self.map_widget.set_theme(self.theme)
        if hasattr(self, "activity_drop_zone"):
            self.activity_drop_zone.set_theme(self.theme)
        if hasattr(self, "chart_mode"):
            self.chart_mode.set_theme(self.theme)
            self.sport_mode.set_theme(self.theme)
        if hasattr(self, "routing_source"):
            self.routing_source.set_theme(self.theme)
        if hasattr(self, "metric_checks"):
            for field, button in self.metric_checks.items():
                button.setStyleSheet(self._metric_button_style(str(METRICS[field]["colour"])))
        caption_colour = "#657184" if self.theme == "light" else "#89909b"
        for panel_name in ("summary", "selection_summary"):
            panel = getattr(self, panel_name, None)
            if panel is not None:
                for row in panel._rows:
                    row.caption_label.setStyleSheet(f"font-size:11px; color:{caption_colour};")
        icon_colour = "#263445" if self.theme == "light" else "#e7e9ee"
        for action, kind in (
            (getattr(self, "save_action", None), "save"),
            (getattr(self, "convert_action", None), "convert"),
            (getattr(self, "gps_check_action", None), "track_check"),
            (getattr(self, "offline_map_action", None), "download"),
            (getattr(self, "settings_action", None), "settings"),
            (getattr(self, "about_action", None), "help"),
        ):
            if action is not None:
                action.setIcon(line_icon(kind, icon_colour))
        if hasattr(self, "create_route_action"):
            self.create_route_action.setIcon(line_icon("route_create", icon_colour))
        if hasattr(self, "undo_action"):
            self.undo_action.setIcon(line_icon("undo", icon_colour))
            self.redo_action.setIcon(line_icon("redo", icon_colour))
            self.vertical_view_button.setIcon(line_icon("layout_vertical", icon_colour))
            self.horizontal_view_button.setIcon(line_icon("layout_horizontal", icon_colour))
            self.telemetry_fit_button.setIcon(line_icon("fit", icon_colour))
            self.selection_cut_button.setIcon(line_icon("trash", "#d83f58" if self.theme == "light" else "#ff687d"))
            self.selection_zoom_button.setIcon(line_icon("zoom", icon_colour))
            self.sport_mode.setItemIcon(0, line_icon("cycling", icon_colour))
            self.sport_mode.setItemIcon(1, line_icon("running", icon_colour))
            self.routing_source.setItemIcon(0, line_icon("cloud", icon_colour))
            self.routing_source.setItemIcon(1, line_icon("local_network", icon_colour))
        if hasattr(self, "routing_group"):
            border = "#2f7fc4" if self.theme == "light" else "#4ba8ff"
            background = "#eef7ff" if self.theme == "light" else "#151f2a"
            field_background = "#ffffff" if self.theme == "light" else "#0d1117"
            text_colour = "#1c2838" if self.theme == "light" else "#eef5ff"
            card_background = "#ffffff" if self.theme == "light" else "#1d2732"
            muted = "#657184" if self.theme == "light" else "#aab5c4"
            common_group_style = (
                f"QGroupBox {{ background:{background}; "
                f"border:2px solid {border}; border-radius:7px; margin-top:12px; "
                "padding:10px 8px 8px 8px; font-weight:bold; }"
                f"QGroupBox::title {{ color:{border}; "
                "subcontrol-origin:margin; left:10px; padding:0 5px; }"
            )
            self.general_settings_group.setStyleSheet(
                common_group_style
                + "QLabel#settingsRowLabel { font-weight:bold; }"
                + f"QPushButton {{ background:{card_background}; color:{text_colour}; "
                f"border:1px solid {border}; border-radius:5px; padding:6px 10px; }}"
            )
            self.routing_group.setStyleSheet(
                f"QGroupBox {{ background:{background}; border:2px solid {border}; "
                "border-radius:7px; margin-top:12px; padding:10px 8px 8px 8px; font-weight:bold; }"
                f"QGroupBox::title {{ color:{border}; subcontrol-origin:margin; "
                "left:10px; padding:0 5px; }"
                f"QLineEdit#routingUrlEdit, QLineEdit#routingKeyEdit {{ background:{field_background}; "
                f"color:{text_colour}; border:2px solid {border}; border-radius:5px; padding:5px 8px; }}"
                f"QLabel#routingAccountLink {{ color:{border}; padding-top:3px; }}"
            )
            self.credits_card.setStyleSheet(
                f"QFrame#creditsCard {{ background:{card_background}; border:1px solid {border}; "
                "border-radius:7px; }"
                "QFrame#creditsCard QLabel { background:transparent; border:none; }"
                "QLabel#creditsTitle { font-size:12px; font-weight:bold; }"
                f"QLabel#creditsReset {{ color:{muted}; padding:3px 7px; "
                f"background:{background}; border-radius:9px; }}"
                "QLabel#creditsValue { font-size:22px; font-weight:bold; }"
                f"QLabel#creditsStatus {{ color:{muted}; }}"
                "QProgressBar { border:none; border-radius:5px; background:#39424d; }"
                f"QProgressBar::chunk {{ border-radius:5px; background:{border}; }}"
            )
            local_card_style = (
                f"QFrame#localSetupCard, QFrame#localServerCard {{ background:{card_background}; "
                f"border:2px solid {border}; border-radius:7px; }}"
                "QFrame#localSetupCard QLabel, QFrame#localServerCard QLabel, "
                "QFrame#localSetupCard QCheckBox, QFrame#localServerCard QCheckBox { "
                "background:transparent; border:none; }"
                f"QLabel#localCardTitle {{ color:{text_colour}; font-size:13px; font-weight:bold; "
                "padding-bottom:2px; }"
                f"QLabel#localStatusText {{ color:{text_colour}; font-size:14px; font-weight:bold; }}"
            )
            self.local_setup_card.setStyleSheet(
                local_card_style
                + f"QFrame#localStepDivider {{ background:{border}; border:none; max-height:1px; }}"
                + f"QFrame#localPrepareOptions {{ background:{background}; border:1px solid {border}; "
                "border-radius:6px; }"
                + "QLabel#localOptionTitle { font-weight:bold; }"
                + f"QLabel#localProgressLabel {{ color:{text_colour}; font-weight:bold; }}"
                + "QPushButton#localDownloadMapButton { background:#326f9f; color:white; "
                "border:1px solid #55a0d6; font-weight:bold; padding:7px 12px; }"
                + "QPushButton#localDownloadMapButton:hover { background:#3c82b8; }"
                + "QToolButton#localDeleteMapButton { background:#713946; color:white; "
                "border:1px solid #a15466; border-radius:5px; padding:6px; }"
                + "QToolButton#localDeleteMapButton:hover { background:#884552; }"
                + f"QToolButton#localDeleteMapButton:disabled {{ background:{background}; "
                f"border:1px solid {muted}; }}"
                + "QPushButton#localPrepareButton { background:#2f7f54; color:white; "
                "border:1px solid #4ba674; font-weight:bold; padding:7px 12px; }"
                + "QPushButton#localPrepareButton:hover { background:#389463; }"
            )
            self.local_server_card.setStyleSheet(
                local_card_style
                + "QPushButton { min-height:38px; font-weight:bold; border-radius:6px; padding:6px 12px; }"
                + "QPushButton#localStartButton { background:#2f7f54; color:white; border:1px solid #4ba674; }"
                + "QPushButton#localStartButton:hover { background:#389463; }"
                + "QPushButton#localStopButton { background:#733844; color:white; border:1px solid #a85768; }"
                + "QPushButton#localStopButton:hover { background:#884552; }"
                + f"QPushButton#localTestButton {{ background:{background}; color:{text_colour}; "
                f"border:1px solid {border}; }}"
                + f"QPushButton#localTestButton:hover {{ background:{card_background}; }}"
                + f"QPushButton:disabled {{ background:{background}; color:{muted}; border:1px solid {muted}; }}"
            )
            self.local_start_button.setIcon(line_icon("play", "#ffffff"))
            self.local_stop_button.setIcon(line_icon("stop", "#ffffff"))
            self.local_test_button.setIcon(line_icon("server_check", text_colour))
            self.local_download_map_button.setIcon(line_icon("download", "#ffffff"))
            self.local_delete_map_button.setIcon(line_icon("trash", "#ffffff"))
            self.local_prepare_button.setIcon(line_icon("settings", "#ffffff"))
            self.clear_cache_button.setIcon(line_icon("trash", text_colour))
            self.local_server_icon.setPixmap(
                line_icon("local_network", text_colour).pixmap(20, 20)
            )
            self.local_setup_icon.setPixmap(line_icon("download", border).pixmap(19, 19))
            self.local_map_icon.setPixmap(line_icon("route_create", border).pixmap(19, 19))
            self.local_prepare_icon.setPixmap(line_icon("settings", border).pixmap(19, 19))
            self.local_setup_card.set_step_line_colour(border)
            self.local_auto_start_check.set_theme(self.theme)
            self.local_stop_on_exit_check.set_theme(self.theme)
            for kind, label in self._settings_row_icons.items():
                label.setPixmap(line_icon(kind, text_colour).pixmap(18, 18))
            self.local_map_path.setStyleSheet(
                f"background:{field_background}; color:{text_colour}; border:1px solid {border}; "
                "border-radius:5px; padding:7px;"
            )
        if persist:
            self.settings.setValue("theme", self.theme)

    @property
    def model(self) -> ActivityModel | None:
        if 0 <= self.active_track_index < len(self.tracks):
            return self.tracks[self.active_track_index].model
        return None

    def _build_ui(self) -> None:
        self.toolbar = self.addToolBar("Main")
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.setIconSize(QtCore.QSize(18, 18))
        self.save_action = self.toolbar.addAction("")
        self.convert_action = self.toolbar.addAction("")
        self.file_route_separator = self.toolbar.addSeparator()
        self.create_route_action = self.toolbar.addAction("")
        self.gps_check_action = self.toolbar.addAction("")
        self.create_route_action.setIcon(line_icon("route_create"))
        self.save_action.setIcon(line_icon("save"))
        self.convert_action.setIcon(line_icon("convert"))
        self.gps_check_action.setIcon(line_icon("track_check"))
        for action, object_name in (
            (self.save_action, "saveResultButton"),
            (self.convert_action, "convertFileButton"),
            (self.create_route_action, "createRouteButton"),
            (self.gps_check_action, "checkTrackButton"),
        ):
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QtWidgets.QToolButton):
                button.setObjectName(object_name)
        self.route_history_separator = self.toolbar.addSeparator()
        self.undo_action = self.toolbar.addAction("")
        self.redo_action = self.toolbar.addAction("")
        self.undo_action.setIcon(line_icon("undo"))
        self.redo_action.setIcon(line_icon("redo"))
        self.undo_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.redo_action.setShortcuts([QtGui.QKeySequence.StandardKey.Redo, QtGui.QKeySequence("Ctrl+Y")])
        for action in (self.undo_action, self.redo_action):
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QtWidgets.QToolButton):
                button.setObjectName("historyButton")
                button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setIconSize(QtCore.QSize(18, 18))
                button.setFixedSize(38, 34)
        self.history_view_separator = self.toolbar.addSeparator()
        view_gap = QtWidgets.QWidget()
        view_gap.setFixedWidth(8)
        self.view_gap_action = self.toolbar.addWidget(view_gap)
        self.view_label = QtWidgets.QLabel()
        self.view_label.setObjectName("sectionLabel")
        self.view_label.setStyleSheet("font-size:12px; font-weight:700; margin-right:4px;")
        self.view_label_action = self.toolbar.addWidget(self.view_label)
        self.vertical_view_button = QtWidgets.QToolButton()
        self.horizontal_view_button = QtWidgets.QToolButton()
        for button, kind in (
            (self.vertical_view_button, "layout_vertical"),
            (self.horizontal_view_button, "layout_horizontal"),
        ):
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIcon(line_icon(kind))
            button.setIconSize(QtCore.QSize(28, 28))
            button.setFixedSize(44, 40)
            action = self.toolbar.addWidget(button)
            if button is self.vertical_view_button:
                self.vertical_view_action = action
            else:
                self.horizontal_view_action = action
        self.vertical_view_button.setChecked(True)
        view_group = QtWidgets.QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self.vertical_view_button)
        view_group.addButton(self.horizontal_view_button)
        self.vertical_view_button.toggled.connect(
            lambda checked: checked and self._set_content_orientation(QtCore.Qt.Orientation.Vertical)
        )
        self.horizontal_view_button.toggled.connect(
            lambda checked: checked and self._set_content_orientation(QtCore.Qt.Orientation.Horizontal)
        )
        self.view_end_separator = self.toolbar.addSeparator()
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.offline_map_action = QtGui.QAction(self)
        self.offline_map_action.setIcon(line_icon("download"))
        self.settings_action = self.toolbar.addAction("")
        self.settings_action.setIcon(line_icon("settings"))
        self.language_combo = QtWidgets.QComboBox()
        self.language_combo.addItem("RU", "ru")
        self.language_combo.addItem("EN", "en")
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.language)))
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("", "dark")
        self.theme_combo.addItem("", "light")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.theme)))
        self.about_action = self.toolbar.addAction("")
        self.about_action.setIcon(line_icon("help"))
        self.open_shortcut = QtGui.QAction(self)
        self.open_shortcut.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        self.open_shortcut.setShortcutContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.addAction(self.open_shortcut)

        self.settings_button = self.toolbar.widgetForAction(self.settings_action)
        self.about_button = self.toolbar.widgetForAction(self.about_action)
        for button in (self.settings_button, self.about_button):
            if isinstance(button, QtWidgets.QToolButton):
                button.setObjectName("toolbarIconButton")
                button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setIconSize(QtCore.QSize(18, 18))
                button.setFixedSize(38, 34)

        self.open_shortcut.triggered.connect(self.open_dialog)
        self.create_route_action.triggered.connect(self.create_route_dialog)
        self.save_action.triggered.connect(self.save_dialog)
        self.convert_action.triggered.connect(self.convert_dialog)
        self.gps_check_action.triggered.connect(self.check_gps_dialog)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.about_action.triggered.connect(self.show_about)
        self.offline_map_action.triggered.connect(self.download_map_dialog)
        self.settings_action.triggered.connect(self.show_settings)
        self.language_combo.currentIndexChanged.connect(self.change_language)
        self.theme_combo.currentIndexChanged.connect(self.change_theme)
        self.undo_stack.canUndoChanged.connect(self._update_undo_actions)
        self.undo_stack.canRedoChanged.connect(self._update_undo_actions)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.workspace_splitter = splitter
        self.setCentralWidget(splitter)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 5, 10)
        left_layout.setSpacing(6)

        self.header = QtWidgets.QLabel()
        self.header.setObjectName("title")
        left_layout.addWidget(self.header)

        self.content_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(7)
        self.content_splitter.setOpaqueResize(True)
        left_layout.addWidget(self.content_splitter, 1)
        self.map_widget = MapWidget()
        self.map_widget.setMinimumWidth(320)
        self.map_widget.download_button.setDefaultAction(self.offline_map_action)
        self.map_widget.download_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.map_widget.cacheDownloadProgress.connect(self._cache_download_progress)
        self.map_widget.cacheDownloadFinished.connect(self._cache_download_finished)
        self.map_widget.searchMessage.connect(
            lambda message: self.statusBar().showMessage(message, 8000)
        )
        self.content_splitter.addWidget(self.map_widget)
        telemetry_container = QtWidgets.QWidget()
        # Keep chart labels and their controls readable while still allowing
        # the user to give most of the workspace to either pane.
        telemetry_container.setMinimumSize(770, 260)
        telemetry_layout = QtWidgets.QVBoxLayout(telemetry_container)
        telemetry_layout.setContentsMargins(0, 0, 0, 0)
        telemetry_layout.setSpacing(6)
        self.telemetry_container = telemetry_container

        metric_controls = QtWidgets.QHBoxLayout()
        self.metric_controls_layout = metric_controls
        metric_controls.setSpacing(8)
        self.metrics_prefix = QtWidgets.QLabel()
        self.metrics_prefix.setObjectName("sectionLabel")
        metric_controls.addWidget(self.metrics_prefix)
        self.metric_checks: dict[str, QtWidgets.QToolButton] = {}
        for field, specification in METRICS.items():
            button = QtWidgets.QToolButton()
            button.setCheckable(True)
            button.setChecked(True)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            colour = str(specification["colour"])
            button.setStyleSheet(self._metric_button_style(colour))
            button.toggled.connect(self._metric_visibility_changed)
            metric_controls.addWidget(button)
            self.metric_checks[field] = button
        metric_controls.addStretch(1)
        self.smooth_label = QtWidgets.QLabel()
        self.smooth_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.smooth_slider.setRange(0, 30)
        self.smooth_slider.setValue(4)
        self.smooth_slider.setFixedWidth(170)
        self.smooth_value = QtWidgets.QLabel("4")
        self.smooth_value.setFixedWidth(24)
        self.smooth_value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.smooth_slider.valueChanged.connect(self._smooth_changed)
        self.telemetry_fit_button = QtWidgets.QToolButton()
        self.telemetry_fit_button.setAutoRaise(True)
        self.telemetry_fit_button.setIcon(line_icon("fit"))
        self.telemetry_fit_button.setIconSize(QtCore.QSize(18, 18))
        self.telemetry_fit_button.setFixedSize(36, 32)
        self.telemetry_fit_button.setToolTip(self.tr("menu_view_all"))
        self.telemetry_fit_button.clicked.connect(self.reset_telemetry_view)
        metric_controls.addWidget(self.telemetry_fit_button)
        telemetry_layout.addLayout(metric_controls)

        chart_options = QtWidgets.QHBoxLayout()
        self.chart_options_layout = chart_options
        chart_options.addWidget(self.smooth_label)
        chart_options.addWidget(self.smooth_slider)
        chart_options.addWidget(self.smooth_value)
        chart_options.addStretch(1)
        self.chart_display_label = QtWidgets.QLabel()
        self.chart_display_label.setObjectName("sectionLabel")
        self.chart_display_label.setStyleSheet("font-size:12px; font-weight:600;")
        chart_options.addWidget(self.chart_display_label)
        self.chart_mode = SegmentedControl([("Раздельно", "separate"), ("Вместе", "combined")])
        self.chart_mode.setMinimumWidth(180)
        self.chart_mode.currentIndexChanged.connect(self._chart_mode_changed)
        chart_options.addWidget(self.chart_mode)
        telemetry_layout.addLayout(chart_options)

        self.telemetry_values = QtWidgets.QLabel()
        self.telemetry_values.setObjectName("telemetryValues")
        self.telemetry_values.setMinimumHeight(20)
        telemetry_layout.addWidget(self.telemetry_values)

        self._syncing_x = False
        self.graph_stack = GraphStack(self, METRICS, TimeAxisItem, TelemetryViewBox)
        self._active_panel_key = "combined"
        self.telemetry_plot = self.graph_stack.panels["combined"].plot
        self.telemetry_view_box = self.graph_stack.panels["combined"].view
        self.telemetry_plot.setBackground("#181c22")
        self.telemetry_plot.showGrid(x=True, y=True, alpha=0.13)
        self.telemetry_plot.getAxis("bottom").setTextPen("#858d98")
        self.telemetry_plot.getAxis("left").setTextPen("#858d98")
        self.telemetry_plot.viewport().setMouseTracking(True)
        self.telemetry_plot.viewport().installEventFilter(self)
        self.telemetry_bubble = QtWidgets.QLabel(self.telemetry_plot.viewport())
        self.telemetry_bubble.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.telemetry_bubble.setWordWrap(False)
        self.telemetry_bubble.setMaximumWidth(330)
        self.telemetry_bubble.setMargin(9)
        self.telemetry_bubble.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.telemetry_bubble.setStyleSheet(
            "QLabel { background:rgba(247,249,252,245); color:#29313d; "
            "border:1px solid #c9ced8; border-radius:8px; }"
        )
        self.telemetry_bubble.hide()
        self.selection_toolbar = QtWidgets.QFrame(self.telemetry_plot.viewport())
        self.selection_toolbar.setObjectName("selectionToolbar")
        selection_actions = QtWidgets.QHBoxLayout(self.selection_toolbar)
        selection_actions.setContentsMargins(5, 4, 5, 4)
        selection_actions.setSpacing(2)
        self.selection_cut_button = QtWidgets.QToolButton()
        self.selection_cut_button.setObjectName("selectionCut")
        self.selection_zoom_button = QtWidgets.QToolButton()
        for button, icon_kind in (
            (self.selection_cut_button, "trash"),
            (self.selection_zoom_button, "zoom"),
        ):
            button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIcon(line_icon(icon_kind))
            button.setIconSize(QtCore.QSize(16, 16))
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            selection_actions.addWidget(button)
        self.selection_cut_button.clicked.connect(self.delete_selected)
        self.selection_zoom_button.clicked.connect(self.zoom_to_selection)
        self.selection_toolbar.adjustSize()
        self.selection_toolbar.hide()
        telemetry_layout.addWidget(self.graph_stack, 1)
        self.telemetry_track_names = QtWidgets.QLabel()
        self.telemetry_track_names.setObjectName("muted")
        self.telemetry_track_names.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.telemetry_track_names.setWordWrap(True)
        self.telemetry_track_names.setMinimumHeight(20)
        self.track_legend_scroll = QtWidgets.QScrollArea()
        self.track_legend_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.track_legend_scroll.setWidgetResizable(True)
        self.track_legend_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.track_legend_scroll.setWidget(self.telemetry_track_names)
        self.track_legend_scroll.setFixedHeight(0)
        self.track_legend_scroll.hide()
        telemetry_layout.addWidget(self.track_legend_scroll)
        self.content_splitter.addWidget(telemetry_container)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([450, 450])

        side = QtWidgets.QFrame()
        side.setObjectName("card")
        side.setMinimumWidth(290)
        side.setMaximumWidth(360)
        side_layout = QtWidgets.QVBoxLayout(side)
        self.activity_title = QtWidgets.QLabel()
        self.activity_title.setObjectName("title")
        self.activity_title.hide()
        self.activity_drop_zone = ActivityDropZone()
        self.activity_drop_zone.browseRequested.connect(self.open_dialog)
        self.activity_drop_zone.filesDropped.connect(self.load_activities)
        side_layout.addWidget(self.activity_drop_zone)
        self.file_label = QtWidgets.QLabel("—")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("muted")
        side_layout.addWidget(self.file_label)
        side_layout.addSpacing(10)
        self.tracks_label = QtWidgets.QLabel()
        self.tracks_label.setObjectName("sectionLabel")
        side_layout.addWidget(self.tracks_label)
        self.track_list = QtWidgets.QListWidget()
        self.track_list.setMinimumHeight(88)
        self.track_list.setMaximumHeight(190)
        self.track_list.currentRowChanged.connect(self._active_track_changed)
        side_layout.addWidget(self.track_list)
        side_layout.addSpacing(10)
        self.general_stats_label = QtWidgets.QLabel()
        self.general_stats_label.setObjectName("sectionLabel")
        side_layout.addWidget(self.general_stats_label)
        self.sport_mode = SegmentedControl([("Велосипед", "cycling"), ("Бег / ходьба", "running")])
        self.sport_mode.setItemIcon(0, line_icon("cycling"))
        self.sport_mode.setItemIcon(1, line_icon("running"))
        self.sport_mode.currentIndexChanged.connect(self._sport_changed)
        side_layout.addWidget(self.sport_mode)
        self.summary = StatsPanel()
        side_layout.addWidget(self.summary)

        side_layout.addSpacing(8)
        self.selection_card = QtWidgets.QFrame()
        self.selection_card.setObjectName("selectionCard")
        selection_card_layout = QtWidgets.QVBoxLayout(self.selection_card)
        selection_card_layout.setContentsMargins(10, 9, 10, 9)
        selection_card_layout.setSpacing(4)
        self.selection_stats_label = QtWidgets.QLabel()
        self.selection_stats_label.setObjectName("sectionLabel")
        selection_card_layout.addWidget(self.selection_stats_label)
        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setWordWrap(True)
        self.selection_label.setObjectName("muted")
        selection_card_layout.addWidget(self.selection_label)
        self.selection_summary = StatsPanel(compact=True)
        selection_card_layout.addWidget(self.selection_summary)
        side_layout.addWidget(self.selection_card)
        side_layout.addStretch(1)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        side_layout.addWidget(self.note)

        side_scroll = QtWidgets.QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        side_scroll.setMinimumWidth(308)
        side_scroll.setMaximumWidth(382)
        side_scroll.setWidget(side)
        self.activity_sidebar = side_scroll
        self.editor_workspace = left
        splitter.addWidget(side_scroll)
        splitter.addWidget(left)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 1050])
        self._build_settings_dialog()

    def _build_settings_dialog(self) -> None:
        self.settings_dialog = QtWidgets.QDialog(self)
        self.settings_dialog.setMinimumWidth(680)
        self.settings_dialog.resize(700, 760)
        layout = QtWidgets.QVBoxLayout(self.settings_dialog)
        self.general_settings_group = QtWidgets.QGroupBox()
        self.general_settings_group.setObjectName("settingsSectionGroup")
        general_layout = QtWidgets.QGridLayout(self.general_settings_group)
        general_layout.setHorizontalSpacing(14)
        general_layout.setVerticalSpacing(9)
        self._settings_row_icons: dict[str, QtWidgets.QLabel] = {}

        def settings_row_label(kind: str) -> tuple[QtWidgets.QWidget, QtWidgets.QLabel]:
            widget = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(7)
            icon = QtWidgets.QLabel()
            icon.setFixedSize(22, 22)
            icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            icon.setPixmap(line_icon(kind).pixmap(18, 18))
            text_label = QtWidgets.QLabel()
            text_label.setObjectName("settingsRowLabel")
            text_label.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            widget.setMinimumHeight(30)
            row.addWidget(icon)
            row.addWidget(text_label)
            row.addStretch(1)
            self._settings_row_icons[kind] = icon
            return widget, text_label

        language_row_label, self.settings_language_label = settings_row_label("language")
        theme_row_label, self.settings_theme_label = settings_row_label("theme")
        cache_row_label, self.settings_cache_label = settings_row_label("cache")
        general_layout.addWidget(language_row_label, 0, 0)
        general_layout.addWidget(self.language_combo, 0, 1)
        general_layout.addWidget(theme_row_label, 1, 0)
        general_layout.addWidget(self.theme_combo, 1, 1)
        cache_controls = QtWidgets.QWidget()
        cache_layout = QtWidgets.QHBoxLayout(cache_controls)
        cache_layout.setContentsMargins(0, 0, 0, 0)
        self.cache_size_label = QtWidgets.QLabel()
        self.cache_size_label.setObjectName("muted")
        self.clear_cache_button = QtWidgets.QPushButton()
        self.clear_cache_button.setIcon(line_icon("trash"))
        self.clear_cache_button.clicked.connect(self.clear_map_cache)
        cache_layout.addWidget(self.cache_size_label)
        cache_layout.addStretch(1)
        cache_layout.addWidget(self.clear_cache_button)
        general_layout.addWidget(cache_row_label, 2, 0)
        general_layout.addWidget(cache_controls, 2, 1)
        general_layout.setColumnStretch(1, 1)
        layout.addWidget(self.general_settings_group)
        # Compatibility aliases used by extensions written for older builds.
        self.appearance_group = self.general_settings_group
        self.cache_group = self.general_settings_group
        self.routing_group = QtWidgets.QGroupBox()
        self.routing_group.setObjectName("routingGroup")
        routing_layout = QtWidgets.QVBoxLayout(self.routing_group)
        self.routing_source_label = QtWidgets.QLabel()
        self.routing_source_label.setObjectName("routeSourceLabel")
        routing_layout.addWidget(self.routing_source_label)
        self.routing_source = SegmentedControl([
            ("Облачный сервис", "cloud"),
            ("Локальный GraphHopper", "local"),
        ])
        self.routing_source.setItemIcon(0, line_icon("cloud"))
        self.routing_source.setItemIcon(1, line_icon("local_network"))
        stored_source = str(self.settings.value("routing_source", "local"))
        self.routing_source.setCurrentIndex(1 if stored_source == "local" else 0)
        routing_layout.addWidget(self.routing_source)
        self.routing_stack = QtWidgets.QStackedWidget()
        routing_layout.addWidget(self.routing_stack)

        self.routing_cloud_page = QtWidgets.QWidget()
        cloud_layout = QtWidgets.QFormLayout(self.routing_cloud_page)
        cloud_layout.setContentsMargins(0, 9, 0, 0)
        self.routing_url_edit = QtWidgets.QLineEdit(str(self.settings.value(
            "routing_url", "https://graphhopper.com/api/1/route"
        )))
        self.routing_key_edit = QtWidgets.QLineEdit(str(self.settings.value("routing_key", "")))
        self.routing_url_edit.setObjectName("routingUrlEdit")
        self.routing_key_edit.setObjectName("routingKeyEdit")
        self.routing_url_edit.setMinimumHeight(34)
        self.routing_key_edit.setMinimumHeight(38)
        self.routing_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.routing_key_edit.editingFinished.connect(
            lambda: self.settings.setValue("routing_key", self.routing_key_edit.text().strip())
        )
        self.routing_url_edit.editingFinished.connect(
            lambda: self.settings.setValue("routing_url", self.routing_url_edit.text().strip())
        )
        self.routing_url_label = QtWidgets.QLabel()
        self.routing_key_label = QtWidgets.QLabel()
        cloud_layout.addRow(self.routing_url_label, self.routing_url_edit)
        cloud_layout.addRow(self.routing_key_label, self.routing_key_edit)
        self.routing_hint = QtWidgets.QLabel()
        self.routing_hint.setObjectName("muted")
        self.routing_hint.setWordWrap(True)
        cloud_layout.addRow(self.routing_hint)
        self.routing_account_link = QtWidgets.QLabel()
        self.routing_account_link.setObjectName("routingAccountLink")
        self.routing_account_link.setOpenExternalLinks(True)
        self.routing_account_link.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        cloud_layout.addRow(self.routing_account_link)

        self.credits_card = QtWidgets.QFrame()
        self.credits_card.setObjectName("creditsCard")
        credits_layout = QtWidgets.QVBoxLayout(self.credits_card)
        credits_layout.setContentsMargins(12, 10, 12, 11)
        credits_layout.setSpacing(7)
        credits_top = QtWidgets.QHBoxLayout()
        self.credits_title_label = QtWidgets.QLabel()
        self.credits_title_label.setObjectName("creditsTitle")
        self.credits_reset_label = QtWidgets.QLabel()
        self.credits_reset_label.setObjectName("creditsReset")
        credits_top.addWidget(self.credits_title_label)
        credits_top.addWidget(self.credits_reset_label)
        credits_top.addStretch(1)
        credits_layout.addLayout(credits_top)
        self.credits_value_label = QtWidgets.QLabel("— / —")
        self.credits_value_label.setObjectName("creditsValue")
        credits_layout.addWidget(self.credits_value_label)
        self.credits_progress = QtWidgets.QProgressBar()
        self.credits_progress.setTextVisible(False)
        self.credits_progress.setRange(0, 100)
        self.credits_progress.setValue(0)
        self.credits_progress.setMinimumHeight(10)
        credits_layout.addWidget(self.credits_progress)
        self.credits_percent_label = QtWidgets.QLabel()
        self.credits_percent_label.setObjectName("creditsStatus")
        self.credits_percent_label.setWordWrap(True)
        credits_layout.addWidget(self.credits_percent_label)
        cloud_layout.addRow(self.credits_card)
        self.routing_stack.addWidget(self.routing_cloud_page)

        self.routing_local_page = QtWidgets.QWidget()
        local_layout = QtWidgets.QVBoxLayout(self.routing_local_page)
        local_layout.setContentsMargins(0, 9, 0, 0)
        local_layout.setSpacing(8)
        self.local_server_card = QtWidgets.QFrame()
        self.local_server_card.setObjectName("localServerCard")
        server_layout = QtWidgets.QVBoxLayout(self.local_server_card)
        server_layout.setContentsMargins(12, 10, 12, 11)
        server_layout.setSpacing(8)
        server_header = QtWidgets.QHBoxLayout()
        self.local_server_icon = QtWidgets.QLabel()
        self.local_server_icon.setPixmap(line_icon("local_network").pixmap(20, 20))
        self.local_server_title = QtWidgets.QLabel()
        self.local_server_title.setObjectName("localCardTitle")
        server_header.addWidget(self.local_server_icon)
        server_header.addWidget(self.local_server_title)
        server_header.addStretch(1)
        server_layout.addLayout(server_header)
        self.local_status_text = QtWidgets.QLabel()
        self.local_status_text.setObjectName("localStatusText")
        self.local_status_text.setWordWrap(True)
        self.local_size_label = QtWidgets.QLabel()
        self.local_size_label.setObjectName("muted")
        self.local_folder_label = QtWidgets.QLabel()
        self.local_folder_label.setObjectName("muted")
        self.local_folder_label.setWordWrap(True)
        server_layout.addWidget(self.local_status_text)
        server_layout.addWidget(self.local_size_label)
        server_layout.addWidget(self.local_folder_label)
        service_row = QtWidgets.QHBoxLayout()
        self.local_start_button = QtWidgets.QPushButton()
        self.local_start_button.setObjectName("localStartButton")
        self.local_stop_button = QtWidgets.QPushButton()
        self.local_stop_button.setObjectName("localStopButton")
        self.local_test_button = QtWidgets.QPushButton()
        self.local_test_button.setObjectName("localTestButton")
        for button in (
            self.local_start_button, self.local_stop_button, self.local_test_button,
        ):
            button.setMinimumHeight(38)
            button.setIconSize(QtCore.QSize(18, 18))
        service_row.addWidget(self.local_start_button, 1)
        service_row.addWidget(self.local_stop_button)
        service_row.addWidget(self.local_test_button)
        server_layout.addLayout(service_row)
        self.local_auto_start_check = OutlinedCheckBox()
        self.local_auto_start_check.setChecked(
            str(self.settings.value("local_graphhopper_auto_start", "true")).lower()
            not in {"false", "0"}
        )
        self.local_stop_on_exit_check = OutlinedCheckBox()
        self.local_stop_on_exit_check.setChecked(
            str(self.settings.value("local_graphhopper_stop_on_exit", "true")).lower()
            not in {"false", "0"}
        )
        server_layout.addWidget(self.local_auto_start_check)
        server_layout.addWidget(self.local_stop_on_exit_check)
        local_layout.addWidget(self.local_server_card)
        # Compatibility alias: status and controls now intentionally share one card.
        self.local_status_card = self.local_server_card
        self.local_status_title = self.local_server_title

        self.local_setup_card = SetupStepsCard()
        self.local_setup_card.setObjectName("localSetupCard")
        setup_layout = QtWidgets.QVBoxLayout(self.local_setup_card)
        setup_layout.setContentsMargins(12, 10, 12, 11)
        setup_layout.setSpacing(8)
        self.local_setup_title = QtWidgets.QLabel()
        self.local_setup_title.setObjectName("localCardTitle")
        setup_header = QtWidgets.QHBoxLayout()
        self.local_setup_icon = QtWidgets.QLabel()
        self.local_setup_icon.setPixmap(line_icon("download").pixmap(19, 19))
        setup_header.addWidget(self.local_setup_icon)
        setup_header.addWidget(self.local_setup_title)
        setup_header.addStretch(1)
        setup_layout.addLayout(setup_header)

        self.local_install_hint = QtWidgets.QLabel()
        self.local_install_hint.setObjectName("muted")
        self.local_install_hint.setWordWrap(True)
        setup_layout.addWidget(self.local_install_hint)
        install_row = QtWidgets.QHBoxLayout()
        self.local_install_button = QtWidgets.QPushButton()
        self.local_open_folder_button = QtWidgets.QPushButton()
        install_row.addWidget(self.local_install_button, 1)
        install_row.addWidget(self.local_open_folder_button)
        setup_layout.addLayout(install_row)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        divider.setObjectName("localStepDivider")
        setup_layout.addWidget(divider)
        self.local_map_title = QtWidgets.QLabel()
        self.local_map_title.setObjectName("localCardTitle")
        map_header = QtWidgets.QHBoxLayout()
        self.local_map_icon = QtWidgets.QLabel()
        self.local_map_icon.setPixmap(line_icon("route_create").pixmap(19, 19))
        map_header.addWidget(self.local_map_icon)
        map_header.addWidget(self.local_map_title)
        map_header.addStretch(1)
        setup_layout.addLayout(map_header)
        region_row = QtWidgets.QHBoxLayout()
        self.local_region_label = QtWidgets.QLabel()
        self.local_region_combo = QtWidgets.QComboBox()
        stored_region = str(self.settings.value(
            "local_graphhopper_region", "northwestern-fed-district"
        ))
        for slug, russian, english, size_mb in GEOFABRIK_RUSSIA_REGIONS:
            self.local_region_combo.addItem(
                russian if self.language == "ru" else english,
                {"slug": slug, "ru": russian, "en": english, "size": size_mb},
            )
        for index in range(self.local_region_combo.count()):
            data = self.local_region_combo.itemData(index)
            if isinstance(data, dict) and data.get("slug") == stored_region:
                self.local_region_combo.setCurrentIndex(index)
                break
        self.local_download_map_button = QtWidgets.QPushButton()
        self.local_download_map_button.setObjectName("localDownloadMapButton")
        self.local_download_map_button.setIcon(line_icon("download"))
        self.local_download_map_button.setIconSize(QtCore.QSize(18, 18))
        self.local_delete_map_button = QtWidgets.QToolButton()
        self.local_delete_map_button.setObjectName("localDeleteMapButton")
        self.local_delete_map_button.setIcon(line_icon("trash"))
        self.local_delete_map_button.setIconSize(QtCore.QSize(18, 18))
        self.local_delete_map_button.setFixedSize(36, 36)
        region_row.addWidget(self.local_region_label)
        region_row.addWidget(self.local_region_combo, 1)
        region_row.addWidget(self.local_download_map_button)
        region_row.addWidget(self.local_delete_map_button)
        setup_layout.addLayout(region_row)
        self.local_map_path = QtWidgets.QLabel()
        self.local_map_path.setObjectName("localMapPath")
        self.local_map_path.setWordWrap(True)
        self.local_map_path.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        setup_layout.addWidget(self.local_map_path)
        self.local_map_help = QtWidgets.QLabel()
        self.local_map_help.setObjectName("routingAccountLink")
        self.local_map_help.setOpenExternalLinks(True)
        self.local_map_help.setWordWrap(True)
        self.local_map_help.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        setup_layout.addWidget(self.local_map_help)
        map_row = QtWidgets.QHBoxLayout()
        self.local_choose_map_button = QtWidgets.QPushButton()
        map_row.addWidget(self.local_choose_map_button, 1)
        setup_layout.addLayout(map_row)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        divider.setObjectName("localStepDivider")
        setup_layout.addWidget(divider)
        self.local_prepare_title = QtWidgets.QLabel()
        self.local_prepare_title.setObjectName("localCardTitle")
        prepare_header = QtWidgets.QHBoxLayout()
        self.local_prepare_icon = QtWidgets.QLabel()
        self.local_prepare_icon.setPixmap(line_icon("settings").pixmap(19, 19))
        prepare_header.addWidget(self.local_prepare_icon)
        prepare_header.addWidget(self.local_prepare_title)
        prepare_header.addStretch(1)
        setup_layout.addLayout(prepare_header)
        self.local_setup_card.set_step_icons([
            self.local_setup_icon, self.local_map_icon, self.local_prepare_icon,
        ])
        prepare_options = QtWidgets.QFrame()
        prepare_options.setObjectName("localPrepareOptions")
        prepare_options_layout = QtWidgets.QGridLayout(prepare_options)
        prepare_options_layout.setContentsMargins(10, 9, 10, 9)
        prepare_options_layout.setHorizontalSpacing(14)
        prepare_options_layout.setVerticalSpacing(5)
        self.local_memory_label = QtWidgets.QLabel()
        self.local_memory_label.setObjectName("localOptionTitle")
        self.local_memory_combo = QtWidgets.QComboBox()
        for amount in (2, 4, 8, 12, 16):
            self.local_memory_combo.addItem(f"{amount} GB", amount)
        memory_index = self.local_memory_combo.findData(self.local_graphhopper.memory_gb)
        self.local_memory_combo.setCurrentIndex(max(0, memory_index))
        prepare_options_layout.addWidget(self.local_memory_label, 0, 0)
        prepare_options_layout.addWidget(self.local_memory_combo, 1, 0)
        self.local_memory_hint = QtWidgets.QLabel()
        self.local_memory_hint.setObjectName("muted")
        self.local_memory_hint.setWordWrap(True)
        self.local_memory_hint.setMinimumWidth(270)
        prepare_options_layout.addWidget(self.local_memory_hint, 0, 1, 2, 1)
        prepare_options_layout.setColumnStretch(1, 1)
        setup_layout.addWidget(prepare_options)

        prepare_row = QtWidgets.QHBoxLayout()
        self.local_prepare_button = QtWidgets.QPushButton()
        self.local_prepare_button.setObjectName("localPrepareButton")
        self.local_delete_database_button = QtWidgets.QPushButton()
        prepare_row.addWidget(self.local_prepare_button, 1)
        prepare_row.addWidget(self.local_delete_database_button)
        setup_layout.addLayout(prepare_row)

        self.local_progress_label = QtWidgets.QLabel()
        self.local_progress_label.setObjectName("localProgressLabel")
        self.local_progress_label.hide()
        setup_layout.addWidget(self.local_progress_label)
        self.local_progress = QtWidgets.QProgressBar()
        self.local_progress.setRange(0, 100)
        self.local_progress.setValue(0)
        self.local_progress.setTextVisible(True)
        self.local_progress.hide()
        setup_layout.addWidget(self.local_progress)
        local_layout.addWidget(self.local_setup_card)

        self.routing_stack.addWidget(self.routing_local_page)
        self.routing_stack.setCurrentIndex(1 if stored_source == "local" else 0)
        layout.addWidget(self.routing_group)

        self._credits_reset_at = float(self.settings.value("routing_credit_reset_at", 0.0) or 0.0)
        self._credits_timer = QtCore.QTimer(self)
        self._credits_timer.setInterval(60_000)
        self._credits_timer.timeout.connect(self._refresh_credit_labels_from_cache)
        self._credits_timer.start()
        self.routing_key_edit.editingFinished.connect(self._routing_credentials_changed)
        self.routing_url_edit.editingFinished.connect(self._routing_credentials_changed)
        self.routing_source.currentIndexChanged.connect(self._routing_source_changed)
        self.local_install_button.clicked.connect(self._install_local_graphhopper)
        self.local_choose_map_button.clicked.connect(self._choose_local_graphhopper_map)
        self.local_download_map_button.clicked.connect(self._download_local_graphhopper_map)
        self.local_delete_map_button.clicked.connect(self._delete_local_graphhopper_map)
        self.local_region_combo.currentIndexChanged.connect(
            self._local_region_changed
        )
        self.local_prepare_button.clicked.connect(self._prepare_local_graphhopper_map)
        self.local_delete_database_button.clicked.connect(self._delete_local_graphhopper_database)
        self.local_start_button.clicked.connect(self.local_graphhopper.start_service)
        self.local_stop_button.clicked.connect(self.local_graphhopper.stop_service)
        self.local_test_button.clicked.connect(self._test_local_graphhopper)
        self.local_open_folder_button.clicked.connect(self._open_local_graphhopper_folder)
        self.local_memory_combo.currentIndexChanged.connect(
            lambda: self.local_graphhopper.set_memory_gb(
                int(self.local_memory_combo.currentData())
            )
        )
        self.local_auto_start_check.toggled.connect(
            lambda value: self.settings.setValue("local_graphhopper_auto_start", value)
        )
        self.local_stop_on_exit_check.toggled.connect(
            lambda value: self.settings.setValue("local_graphhopper_stop_on_exit", value)
        )
        self.local_graphhopper.stateChanged.connect(self._local_graphhopper_state_changed)
        self.local_graphhopper.progressChanged.connect(self._local_graphhopper_progress)
        self.local_graphhopper.downloadBytesChanged.connect(
            self._local_graphhopper_download_bytes
        )
        self.local_graphhopper.componentsChanged.connect(self._refresh_local_graphhopper_ui)
        self.local_graphhopper.prepared.connect(self._refresh_local_graphhopper_ui)
        self.local_graphhopper.failed.connect(self._local_graphhopper_failed)
        self._local_graphhopper_state = self.local_graphhopper.state()
        self._local_graphhopper_details = ""
        self._pending_map_download: tuple[str, str] | None = None
        self._map_download_wait_attempts = 0
        self._map_download_wait_timer = QtCore.QTimer(self)
        self._map_download_wait_timer.setInterval(150)
        self._map_download_wait_timer.timeout.connect(
            self._continue_pending_local_map_download
        )
        self.settings_buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        self.settings_buttons.rejected.connect(self.settings_dialog.reject)
        layout.addWidget(self.settings_buttons)

    def _set_content_orientation(self, orientation: QtCore.Qt.Orientation) -> None:
        """Switch the map/telemetry pane between stacked and side-by-side views."""
        if hasattr(self, "content_splitter"):
            self.content_splitter.setOrientation(orientation)
            available = (
                self.content_splitter.height()
                if orientation == QtCore.Qt.Orientation.Vertical
                else self.content_splitter.width()
            )
            half = max(1, (available - self.content_splitter.handleWidth()) // 2)
            self.content_splitter.setSizes([half, half])

    def _retranslate_ui(self) -> None:
        for index, text in enumerate(
            ["Раздельно", "Вместе"] if self.language == "ru"
            else ["Separate", "Combined"]
        ):
            self.chart_mode.setItemText(index, text)
        self.chart_mode.setToolTip(
            "Раздельные: своя шкала у каждого параметра. Единая: общая шкала в исходных единицах."
            if self.language == "ru" else
            "Separate: each metric has its own scale. Combined: shared scale in original units."
        )
        self.chart_display_label.setText(
            "ОТОБРАЖЕНИЕ ГРАФИКОВ" if self.language == "ru" else "CHART DISPLAY"
        )
        for index, text in enumerate(
            ["Велосипед", "Бег / ходьба"] if self.language == "ru"
            else ["Cycling", "Run / walk"]
        ):
            self.sport_mode.setItemText(index, text)
        self.sport_mode.setToolTip(
            "Режим расчёта: велосипед — км/ч, бег и ходьба — мин/км."
            if self.language == "ru" else
            "Calculation mode: cycling uses km/h, running and walking use min/km."
        )
        self.toolbar.setWindowTitle(self.tr("toolbar"))
        for action, key in (
            (self.create_route_action, "create_route"),
            (self.save_action, "save"),
            (self.convert_action, "convert"), (self.gps_check_action, "gps_check"),
            (self.offline_map_action, "offline_map"),
        ):
            action.setText(self.tr(key))
        self.open_shortcut.setText(self.tr("open"))
        self.save_action.setToolTip(
            self.tr("save_hint_multiple") if len(self.tracks) > 1
            else self.tr("save_hint_single")
        )
        self.convert_action.setToolTip(self.tr("convert_hint"))
        self.create_route_action.setToolTip(self.tr("create_route_hint"))
        self.gps_check_action.setToolTip(self.tr("gps_check_hint"))
        self.offline_map_action.setToolTip(self.tr("offline_map_hint"))
        self.settings_action.setText("")
        self.about_action.setText("")
        self.settings_action.setToolTip(self.tr("settings_hint"))
        self.about_action.setToolTip(self.tr("about_title"))
        self.settings_dialog.setWindowTitle(self.tr("settings"))
        self.settings_language_label.setText(self.tr("language"))
        self.settings_theme_label.setText(self.tr("theme"))
        self.settings_cache_label.setText(self.tr("cache"))
        self.general_settings_group.setTitle(self.tr("general_settings"))
        self.theme_combo.setItemText(0, self.tr("theme_dark"))
        self.theme_combo.setItemText(1, self.tr("theme_light"))
        self.clear_cache_button.setText(self.tr("cache_clear"))
        self.routing_group.setTitle(self.tr("routing"))
        self.routing_source_label.setText(self.tr("routing_source"))
        self.routing_source.setItemText(0, self.tr("routing_cloud"))
        self.routing_source.setItemText(1, self.tr("routing_local"))
        self.routing_url_label.setText(self.tr("routing_url"))
        self.routing_key_label.setText(self.tr("routing_key"))
        self.routing_hint.setText(self.tr("routing_key_hint"))
        self.routing_key_edit.setPlaceholderText(self.tr("routing_key_placeholder"))
        self.routing_account_link.setText(self.tr("routing_account_links"))
        self.credits_title_label.setText(self.tr("credits_title"))
        self.local_setup_title.setText(self.tr("local_setup_section"))
        self.local_prepare_title.setText(self.tr("local_prepare_section"))
        self.local_server_title.setText(self.tr("local_server_section"))
        self.local_install_hint.setText(self.tr("local_install_hint"))
        self.local_install_button.setText(self.tr("local_install"))
        self.local_open_folder_button.setText(self.tr("local_open_folder"))
        self.local_map_title.setText(self.tr("local_map"))
        self.local_region_label.setText(self.tr("local_map_region"))
        self.local_download_map_button.setText(self.tr("local_download_map"))
        self.local_delete_map_button.setToolTip(self.tr("local_delete_map_hint"))
        self.local_delete_map_button.setAccessibleName(self.tr("local_delete_map_hint"))
        self._refresh_local_region_labels()
        self.local_map_help.setText(self.tr("local_map_help"))
        self.local_choose_map_button.setText(self.tr("local_choose_map"))
        self.local_prepare_button.setText(self.tr("local_prepare"))
        self.local_delete_database_button.setText(self.tr("local_delete_database"))
        self.local_memory_label.setText(self.tr("local_memory"))
        self.local_start_button.setText(self.tr("local_start"))
        self.local_stop_button.setText(self.tr("local_stop"))
        self.local_test_button.setText(self.tr("local_test"))
        self.local_auto_start_check.setText(self.tr("local_auto_start"))
        self.local_stop_on_exit_check.setText(self.tr("local_stop_on_exit"))
        close_button = self.settings_buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        if close_button is not None:
            close_button.setText(self.tr("dialog_close"))
        self._refresh_credit_labels_from_cache()
        self._refresh_local_graphhopper_ui()
        self._update_cache_size_label()
        self.undo_action.setText("")
        self.redo_action.setText("")
        self.undo_action.setToolTip(self.tr("undo_hint"))
        self.redo_action.setToolTip(self.tr("redo_hint"))
        self.view_label.setText("ВИД" if self.language == "ru" else "VIEW")
        self.vertical_view_button.setToolTip(
            "Вертикальная компоновка" if self.language == "ru" else "Vertical layout"
        )
        self.horizontal_view_button.setToolTip(
            "Горизонтальная компоновка" if self.language == "ru" else "Horizontal layout"
        )
        self.telemetry_fit_button.setToolTip(self.tr("menu_view_all"))
        if self.model is None:
            self.header.setText(self.tr("drop"))
        else:
            self._update_header()
        self.map_widget.set_language(self.language)
        if hasattr(self, "resource_usage_label"):
            self.resource_usage_label.setToolTip(self.tr("resource_tooltip"))
        if hasattr(self, "local_server_indicator"):
            self.local_server_indicator.setToolTip(
                self.tr("local_server_indicator_hint")
            )
            self._update_local_server_indicator()
        self.activity_title.setText(self.tr("activity"))
        self.activity_drop_zone.set_texts(
            self.tr("drop_zone_title"), self.tr("drop_zone_hint")
        )
        self.tracks_label.setText(self.tr("tracks"))
        self.general_stats_label.setText(self.tr("general_stats"))
        self.selection_stats_label.setText(self.tr("selected_stats"))
        self.selection_cut_button.setText(self.tr("selection_cut"))
        self.selection_zoom_button.setText(self.tr("selection_zoom"))
        self.selection_cut_button.setToolTip(self.tr("delete"))
        self.selection_zoom_button.setToolTip(self.tr("menu_selection"))
        self.selection_toolbar.adjustSize()
        for row in range(self.track_list.count()):
            item = self.track_list.item(row)
            row_widget = self.track_list.itemWidget(item)
            if isinstance(row_widget, TrackListRow):
                row_widget.set_language(self.tr("track_visibility"), self.tr("remove_track"))
        self.metrics_prefix.setText(self.tr("show"))
        for field, button in self.metric_checks.items():
            button.setText(f"●  {self.tr(field)}")
        self._update_metric_availability()
        self.smooth_label.setText(f"{self.tr('smooth')}:")
        self.smooth_slider.setToolTip(self.tr("smooth_hint"))
        self.smooth_label.setToolTip(self.tr("smooth_hint"))
        self._update_track_legend()
        self.note.setText(
            self.tr("note_fit") if self.model and self.model.source_format == "fit"
            else self.tr("note_xml") if self.model else ""
        )
        if self.model:
            self._update_summary()
            self._update_selection_label()
            self._render_telemetry(self._current_region())
        else:
            self.selection_label.setText(f"{self.tr('selection')}: —")
            self.selection_card.hide()
            self.telemetry_values.setText(f"{self.tr('cursor')}: —")
            self._update_plot_labels()
        self._position_selection_toolbar()
        self.statusBar().showMessage(self.tr("ready"))
        self._update_undo_actions()

    def change_language(self) -> None:
        self.language = str(self.language_combo.currentData())
        self.settings.setValue("language", self.language)
        self._retranslate_ui()

    def change_theme(self) -> None:
        self.apply_theme(str(self.theme_combo.currentData()))

    def show_settings(self) -> None:
        self._update_cache_size_label()
        self._refresh_credit_labels_from_cache()
        self.local_graphhopper.emit_current_state()
        self._refresh_local_graphhopper_ui()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _routing_source_changed(self, index: int) -> None:
        source = str(self.routing_source.currentData())
        self.settings.setValue("routing_source", source)
        self.routing_stack.setCurrentIndex(1 if source == "local" else 0)
        if source == "local":
            self.local_graphhopper.emit_current_state()
            self._refresh_local_graphhopper_ui()
        else:
            self._refresh_credit_labels_from_cache()

    def _maybe_start_local_graphhopper(self) -> None:
        if (
            str(self.routing_source.currentData()) == "local"
            and self.local_auto_start_check.isChecked()
            and self.local_graphhopper.state() == "stopped"
        ):
            self.local_graphhopper.start_service()

    def _local_graphhopper_state_changed(self, state: str, details: str) -> None:
        self._local_graphhopper_state = state
        self._local_graphhopper_details = details
        self._update_local_server_indicator(state == "running")
        self._refresh_local_graphhopper_ui()

    def _local_graphhopper_progress(self, percent: int, _stage: str) -> None:
        if _stage == "error":
            self._hide_local_progress()
            return
        stage_labels = {
            "map": "local_downloading_map",
            "import": "local_importing",
            "engine": "local_downloading",
            "runtime": "local_downloading",
            "extracting": "local_extracting",
        }
        if _stage in stage_labels:
            self.local_progress_label.setText(self.tr(stage_labels[_stage]))
            self.local_progress_label.show()
        self.local_progress.show()
        if percent < 0:
            self.local_progress.setRange(0, 0)
            self.local_progress.setTextVisible(False)
        else:
            self.local_progress.setRange(0, 100)
            self.local_progress.setTextVisible(True)
            self.local_progress.setValue(max(0, min(100, percent)))
            if percent >= 100:
                QtCore.QTimer.singleShot(1200, self._hide_local_progress)

    def _local_graphhopper_download_bytes(
        self, received: int, total: int, stage: str
    ) -> None:
        if stage != "map":
            return
        if total > 0:
            text = self.tr(
                "local_download_progress",
                received=self._human_size(max(0, received)),
                total=self._human_size(total),
            )
        else:
            text = self.tr(
                "local_download_progress_unknown",
                received=self._human_size(max(0, received)),
            )
        self.local_progress_label.setText(text)
        self.local_progress_label.show()
        self.local_progress.show()

    def _hide_local_progress(self) -> None:
        self.local_progress.hide()
        self.local_progress_label.hide()

    def _region_map_files(self, slug: str) -> list[Path]:
        return self.local_graphhopper.downloaded_map_files(slug)

    def _local_region_changed(self) -> None:
        data = self.local_region_combo.currentData()
        slug = str(data.get("slug", "")) if isinstance(data, dict) else ""
        self.settings.setValue("local_graphhopper_region", slug)
        self._refresh_local_graphhopper_ui()

    def _refresh_local_region_labels(self) -> None:
        if not hasattr(self, "local_region_combo"):
            return
        for index in range(self.local_region_combo.count()):
            data = self.local_region_combo.itemData(index)
            if not isinstance(data, dict):
                continue
            slug = str(data.get("slug", ""))
            region = str(data.get("ru" if self.language == "ru" else "en", slug))
            if self._region_map_files(slug):
                region = self.tr("local_region_downloaded", region=region)
            self.local_region_combo.setItemText(index, region)

    def _refresh_local_graphhopper_ui(self) -> None:
        if not hasattr(self, "local_status_text"):
            return
        state = getattr(self, "_local_graphhopper_state", self.local_graphhopper.state())
        details = getattr(self, "_local_graphhopper_details", "")
        status_keys = {
            "not_installed": "local_not_installed",
            "needs_map": "local_needs_map",
            "needs_prepare": "local_needs_prepare",
            "needs_rebuild": "local_needs_rebuild",
            "stopped": "local_stopped",
            "downloading": "local_downloading",
            "extracting": "local_extracting",
            "importing": "local_importing",
            "starting": "local_starting",
            "stopping": "local_stopping",
            "running": "local_running",
            "error": "local_error",
        }
        text = self.tr(status_keys.get(state, "local_stopped"))
        if state == "downloading" and details == "map":
            text = self.tr("local_downloading_map")
        if state == "error" and details:
            text += f"\n{details}"
        self.local_status_text.setText(text)
        self.local_status_text.setStyleSheet(
            "color:#55c987;" if state == "running"
            else "color:#ff7185;" if state == "error"
            else ""
        )
        pbf = self.local_graphhopper.pbf_path
        self.local_map_path.setText(
            str(pbf) if pbf.is_file() else self.tr("local_map_none")
        )
        if pbf.is_file():
            try:
                pbf_size = pbf.stat().st_size
            except OSError:
                pbf_size = 0
            recommended_memory = 4 if pbf_size < 250 * 1024 ** 2 else 8 if pbf_size < 700 * 1024 ** 2 else 12
            self.local_memory_hint.setText(self.tr(
                "local_memory_hint", memory=recommended_memory
            ))
            self.local_memory_hint.show()
        else:
            self.local_memory_hint.setText(self.tr("local_memory_no_map"))
            self.local_memory_hint.show()
        self.local_size_label.setText(self.tr(
            "local_size", size=self._human_size(self.local_graphhopper.installation_size())
        ))
        self.local_folder_label.setText(self.tr(
            "local_folder", path=str(self.local_graphhopper.root)
        ))
        self._refresh_local_region_labels()
        installed = self.local_graphhopper.components_installed()
        prepared = (
            self.local_graphhopper.graph_prepared()
            and not self.local_graphhopper.graph_requires_rebuild()
        )
        running = state in {"running", "starting", "stopping"}
        busy = state in {"downloading", "extracting", "importing", "starting", "stopping"}
        self.local_install_button.setText(
            self.tr("local_installed") if installed else self.tr("local_install")
        )
        self.local_install_button.setEnabled(not installed and not busy)
        self.local_choose_map_button.setEnabled(not busy or state == "running")
        self.local_region_combo.setEnabled(not busy)
        # A running server may be stopped automatically before the download.
        self.local_download_map_button.setEnabled(not busy or state == "running")
        selected_region = self.local_region_combo.currentData()
        selected_slug = (
            str(selected_region.get("slug", ""))
            if isinstance(selected_region, dict) else ""
        )
        self.local_delete_map_button.setEnabled(
            bool(selected_slug and self._region_map_files(selected_slug))
            and not busy and not running
        )
        self.local_prepare_button.setEnabled(
            installed and pbf.is_file() and not busy and not running
        )
        self.local_delete_database_button.setEnabled(
            prepared and not busy and not running
        )
        self.local_start_button.setEnabled(prepared and not busy and not running)
        self.local_stop_button.setEnabled(running)
        self.local_test_button.setEnabled(not busy or state == "running")
        if (
            not busy
            and self.local_progress.maximum() == 0
            and getattr(self, "_pending_map_download", None) is None
        ):
            self._hide_local_progress()

    def _download_local_graphhopper_map(self) -> None:
        data = self.local_region_combo.currentData()
        if not isinstance(data, dict):
            return
        slug = str(data.get("slug", "")).strip()
        if not slug:
            return
        region = str(data.get("ru" if self.language == "ru" else "en", slug))
        size_mb = int(data.get("size", 0) or 0)
        filename = f"{slug}-latest.osm.pbf"
        destination = self.local_graphhopper.root / "maps" / filename
        prompt_key = (
            "local_download_map_overwrite"
            if destination.is_file()
            else "local_download_map_confirm"
        )
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("local_download_map_title"),
            self.tr(prompt_key, region=region, size=size_mb),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        url = f"https://download.geofabrik.de/russia/{slug}-latest.osm.pbf"
        process_running = (
            self.local_graphhopper.process.state()
            != QtCore.QProcess.ProcessState.NotRunning
            or self.local_graphhopper.is_running()
        )
        if process_running:
            self._pending_map_download = (url, filename)
            self._map_download_wait_attempts = 0
            self.local_progress_label.setText(self.tr("local_stopping_for_download"))
            self.local_progress_label.show()
            self.local_progress.setRange(0, 0)
            self.local_progress.setTextVisible(False)
            self.local_progress.show()
            self.local_graphhopper.stop_service()
            self._map_download_wait_timer.start()
            return
        self._begin_local_map_download(url, filename)

    def _begin_local_map_download(self, url: str, filename: str) -> None:
        try:
            self.local_graphhopper.download_map(url, filename)
        except Exception as error:
            self._pending_map_download = None
            self._hide_local_progress()
            QtWidgets.QMessageBox.warning(self, self.tr("local_error"), str(error))

    def _continue_pending_local_map_download(self) -> None:
        pending = self._pending_map_download
        if pending is None:
            self._map_download_wait_timer.stop()
            return
        self._map_download_wait_attempts += 1
        process_stopped = (
            self.local_graphhopper.process.state()
            == QtCore.QProcess.ProcessState.NotRunning
            and not self.local_graphhopper.is_running()
        )
        if process_stopped:
            self._map_download_wait_timer.stop()
            self._pending_map_download = None
            self._begin_local_map_download(*pending)
            return
        if self._map_download_wait_attempts >= 100:
            self._map_download_wait_timer.stop()
            self._pending_map_download = None
            self._hide_local_progress()
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("local_error"),
                self.tr("local_stop_download_timeout"),
            )

    def _choose_local_graphhopper_map(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("local_select_map_title"),
            str(self.local_graphhopper.pbf_path.parent)
            if self.local_graphhopper.pbf_path else "",
            self.tr("local_select_map_filter"),
        )
        if path:
            if (
                self.local_graphhopper.process.state()
                != QtCore.QProcess.ProcessState.NotRunning
            ):
                self.local_graphhopper.stop_service()
            self.local_graphhopper.set_pbf_path(path)
            self._local_graphhopper_state = self.local_graphhopper.state()
            self._local_graphhopper_details = ""
            self._refresh_local_graphhopper_ui()

    def _delete_local_graphhopper_map(self) -> None:
        data = self.local_region_combo.currentData()
        if not isinstance(data, dict):
            return
        slug = str(data.get("slug", "")).strip()
        if not slug or not self._region_map_files(slug):
            return
        region = str(data.get("ru" if self.language == "ru" else "en", slug))
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("local_delete_map_title"),
            self.tr("local_delete_map_confirm", region=region),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            removed = self.local_graphhopper.delete_downloaded_map(slug)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, self.tr("local_error"), str(error))
            return
        if removed:
            self.statusBar().showMessage(
                self.tr("local_delete_map_done", region=region), 7000
            )
        self._local_graphhopper_state = self.local_graphhopper.state()
        self._local_graphhopper_details = ""
        self._refresh_local_graphhopper_ui()

    def _install_local_graphhopper(self) -> None:
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("local_install_title"),
            self.tr("local_install_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.local_graphhopper.install_components()

    def _prepare_local_graphhopper_map(self) -> None:
        if self.local_graphhopper.graph_prepared():
            answer = QtWidgets.QMessageBox.question(
                self,
                self.tr("local_rebuild_title"),
                self.tr("local_rebuild_confirm"),
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            try:
                self.local_graphhopper.delete_graph_cache()
            except Exception as error:
                QtWidgets.QMessageBox.warning(
                    self, self.tr("local_error"), str(error)
                )
                return
        self.local_graphhopper.prepare_map()

    def _delete_local_graphhopper_database(self) -> None:
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("local_delete_title"),
            self.tr("local_delete_confirm"),
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.local_graphhopper.delete_graph_cache()
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, self.tr("local_error"), str(error))

    def _test_local_graphhopper(self) -> None:
        if self.local_graphhopper.test_connection():
            QtWidgets.QMessageBox.information(
                self, self.tr("local_status"), self.tr("local_test_ok")
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, self.tr("local_status"), self.tr("local_test_failed")
            )

    def _open_local_graphhopper_folder(self) -> None:
        self.local_graphhopper.root.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self.local_graphhopper.root))
        )

    def _local_graphhopper_failed(self, error: str) -> None:
        self.statusBar().showMessage(self.tr("local_download_error", error=error), 10000)
        if self.settings_dialog.isVisible():
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("local_error"),
                self.tr("local_download_error", error=error)
                + "\n\n"
                + self.tr("local_log", path=str(self.local_graphhopper.log_path)),
            )

    def _routing_credentials_changed(self) -> None:
        key = self.routing_key_edit.text().strip()
        suffix = key[-8:] if key else ""
        if str(self.settings.value("routing_credit_key_suffix", "")) != suffix:
            for setting in (
                "routing_credit_limit", "routing_credit_remaining",
                "routing_credit_reset_at", "routing_credit_key_suffix",
            ):
                self.settings.remove(setting)
            self._credits_reset_at = 0.0
        self._refresh_credit_labels_from_cache()

    def _credit_time_text(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes = max(0, remainder // 60)
        if self.language == "ru":
            return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"
        return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"

    def _refresh_credit_labels_from_cache(self) -> None:
        if not hasattr(self, "credits_value_label"):
            return
        service_url = self.routing_url_edit.text().strip()
        key = self.routing_key_edit.text().strip()
        hosted = route_service_requires_key(service_url)
        if not hosted:
            self.credits_value_label.setText("— / —")
            self.credits_progress.setRange(0, 100)
            self.credits_progress.setValue(0)
            self.credits_reset_label.hide()
            self.credits_percent_label.setText(self.tr("credits_local"))
            return
        if not key:
            self.credits_value_label.setText("— / —")
            self.credits_progress.setRange(0, 100)
            self.credits_progress.setValue(0)
            self.credits_reset_label.hide()
            self.credits_percent_label.setText(self.tr("credits_need_key"))
            return
        suffix = key[-8:]
        stored_suffix = str(self.settings.value("routing_credit_key_suffix", ""))
        try:
            limit = int(self.settings.value("routing_credit_limit", 0) or 0)
            remaining = int(self.settings.value("routing_credit_remaining", -1))
            reset_at = float(self.settings.value("routing_credit_reset_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            limit, remaining, reset_at = 0, -1, 0.0
        if stored_suffix != suffix or limit <= 0 or remaining < 0:
            self.credits_value_label.setText(f"— / {DEFAULT_HOSTED_CREDIT_LIMIT}")
            self.credits_progress.setRange(0, DEFAULT_HOSTED_CREDIT_LIMIT)
            self.credits_progress.setValue(0)
            self.credits_reset_label.hide()
            self.credits_percent_label.setText(self.tr("credits_unknown"))
            return
        # Cached rate-limit headers belong only to the window reported by the
        # API. Once that window has expired (or no valid reset was supplied),
        # keeping the old remainder produces misleading values such as 2/500
        # with "resets in 0 min". Start the new window clean instead.
        if reset_at <= time.time():
            remaining = limit
            reset_at = 0.0
            self.settings.setValue("routing_credit_remaining", remaining)
            self.settings.remove("routing_credit_reset_at")
        used = max(0, min(limit, limit - remaining))
        percent = int(round(used / limit * 100.0))
        self.credits_value_label.setText(self.tr("credits_value", used=used, limit=limit))
        self.credits_progress.setRange(0, limit)
        self.credits_progress.setValue(used)
        self.credits_percent_label.setText(self.tr("credits_percent", percent=percent))
        self._credits_reset_at = reset_at
        if reset_at > time.time():
            self.credits_reset_label.setText(self.tr(
                "credits_reset", time=self._credit_time_text(round(reset_at - time.time()))
            ))
            self.credits_reset_label.show()
        else:
            self.credits_reset_label.hide()

    def _update_graphhopper_credits(
        self, limit: int, remaining: int, reset_seconds: int
    ) -> None:
        limit = max(0, int(limit))
        remaining = max(0, min(limit, int(remaining)))
        if limit <= 0:
            return
        reset_at = time.time() + max(0, int(reset_seconds))
        key = self.routing_key_edit.text().strip()
        self.settings.setValue("routing_credit_limit", limit)
        self.settings.setValue("routing_credit_remaining", remaining)
        self.settings.setValue("routing_credit_reset_at", reset_at)
        self.settings.setValue("routing_credit_key_suffix", key[-8:] if key else "")
        self._credits_reset_at = reset_at
        self._refresh_credit_labels_from_cache()

    def _update_cache_size_label(self) -> None:
        if hasattr(self, "cache_size_label"):
            self.cache_size_label.setText(
                self.tr("cache_size", size=self._human_size(self.map_widget.cache_size_bytes()))
            )

    def clear_map_cache(self) -> None:
        if self.map_widget.cache_download_active:
            QtWidgets.QMessageBox.warning(self, self.tr("cache_clear_title"), self.tr("cache_busy"))
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("cache_clear_title"),
            self.tr("cache_clear_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        removed = self.map_widget.clear_tile_cache()
        self._update_cache_size_label()
        QtWidgets.QMessageBox.information(
            self, self.tr("cache_clear_title"),
            self.tr("cache_cleared", size=self._human_size(removed)),
        )

    def _set_loaded(self, loaded: bool) -> None:
        for action in (
            self.save_action, self.convert_action, self.gps_check_action,
        ):
            action.setEnabled(loaded)
        self.offline_map_action.setEnabled(not self.map_widget.cache_download_active)
        if hasattr(self, "telemetry_fit_button"):
            self.telemetry_fit_button.setEnabled(loaded)
        self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        self.undo_action.setEnabled(self.model is not None and self.undo_stack.canUndo())
        self.redo_action.setEnabled(self.model is not None and self.undo_stack.canRedo())

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        paths = [
            url.toLocalFile() for url in event.mimeData().urls()
            if Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if paths:
            self.load_activities(paths)
            event.acceptProposedAction()

    def open_dialog(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, self.tr("open_title"), "", self.tr("open_filter")
        )
        if paths:
            self.load_activities(paths)

    def create_route_dialog(self) -> None:
        if self._route_panel is not None:
            self._route_panel.close_mode()
            return
        if str(self.routing_source.currentData()) == "local":
            if (
                not self.local_graphhopper.graph_prepared()
                or self.local_graphhopper.graph_requires_rebuild()
            ):
                QtWidgets.QMessageBox.warning(
                    self, self.tr("local_status"), self.tr("local_setup_required")
                )
                self.show_settings()
                return
            if self.local_graphhopper.is_running():
                self._open_route_planner(LOCAL_ROUTE_URL, "")
                return
            if self.local_auto_start_check.isChecked():
                self.statusBar().showMessage(self.tr("local_starting"))
                self.local_graphhopper.ensure_running(
                    lambda: self._open_route_planner(LOCAL_ROUTE_URL, "")
                )
                return
            QtWidgets.QMessageBox.warning(
                self, self.tr("local_status"), self.tr("local_start_required")
            )
            self.show_settings()
            return
        self._open_route_planner(
            self.routing_url_edit.text().strip(),
            self.routing_key_edit.text().strip(),
        )

    def _open_route_planner(self, service_url: str, api_key: str) -> None:
        if self._route_panel is not None:
            self._route_panel.close_mode()
        self._set_route_focus_mode(True)
        panel = RoutePlannerPanel(
            language=self.language,
            theme=self.theme,
            service_url=service_url,
            api_key=api_key,
            map_widget=self.map_widget,
            track_points_provider=self._active_track_route_points,
            initial_state=self._route_draft_state,
        )
        self._route_panel = panel
        panel.creditUsageUpdated.connect(self._update_graphhopper_credits)
        panel.routeCreated.connect(self._route_created_from_panel)
        panel.routeSaveRequested.connect(self._save_route_gpx_from_panel)
        panel.cancelled.connect(
            lambda state, current=panel: self._route_panel_closed(current, state)
        )
        self.statusBar().showMessage(
            "Режим построения маршрута включён" if self.language == "ru"
            else "Route-building mode enabled"
        )

    def _set_route_focus_mode(self, enabled: bool) -> None:
        for action in (
            self.save_action,
            self.convert_action,
            self.create_route_action,
            self.gps_check_action,
            self.file_route_separator,
            self.route_history_separator,
            self.undo_action,
            self.redo_action,
            self.history_view_separator,
            self.view_gap_action,
            self.view_label_action,
            self.vertical_view_action,
            self.horizontal_view_action,
            self.view_end_separator,
        ):
            action.setVisible(not enabled)
        if enabled:
            if self._route_layout_state is None:
                self._route_layout_state = (
                    list(self.workspace_splitter.sizes()),
                    list(self.content_splitter.sizes()),
                )
            self.activity_sidebar.hide()
            self.telemetry_container.hide()
            self.header.hide()
            QtCore.QTimer.singleShot(
                0, lambda: self.workspace_splitter.setSizes([0, max(1, self.width())])
            )
            return
        self.activity_sidebar.show()
        self.telemetry_container.show()
        self.header.show()
        state = self._route_layout_state
        self._route_layout_state = None
        if state is not None:
            workspace_sizes, content_sizes = state
            QtCore.QTimer.singleShot(
                0, lambda sizes=workspace_sizes: self.workspace_splitter.setSizes(sizes)
            )
            QtCore.QTimer.singleShot(
                0, lambda sizes=content_sizes: self.content_splitter.setSizes(sizes)
            )

    def _save_route_gpx_from_panel(
        self,
        coordinates: object,
        route_name: str,
    ) -> None:
        route_coordinates = list(coordinates) if isinstance(coordinates, (list, tuple)) else []
        try:
            model = ActivityModel.from_route(route_coordinates, route_name, 0.0)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, self.tr("save_error"), str(error))
            return
        default_parent = self.model.path.parent if self.model else Path.cwd()
        destination, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("route_save_title"),
            str(default_parent / model.path.name),
            "GPX (*.gpx)",
        )
        if not destination:
            return
        if Path(destination).suffix.lower() != ".gpx":
            destination += ".gpx"
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            model.export(destination)
            QtWidgets.QMessageBox.information(
                self, self.tr("saved"), self.tr("route_save_ok")
            )
            self.statusBar().showMessage(self.tr("saved_status", path=destination))
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, self.tr("save_error"), str(error))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _route_panel_closed(self, panel: RoutePlannerPanel, state: object) -> None:
        if isinstance(state, dict):
            self._route_draft_state = dict(state)
        if self._route_panel is panel:
            self._route_panel = None
        self._set_route_focus_mode(False)
        self.statusBar().showMessage(self.tr("ready"))

    def _active_track_route_points(self) -> list[tuple[float, float]]:
        model = self.model
        if model is None:
            return []
        return [
            (float(point.lat), float(point.lon))
            for index, point in enumerate(model.points)
            if bool(model.active[index]) and math.isfinite(point.lat) and math.isfinite(point.lon)
        ]

    def _route_created_from_panel(
        self,
        coordinates: object,
        route_name: str,
        route_duration_s: float,
    ) -> None:
        route_coordinates = list(coordinates) if isinstance(coordinates, (list, tuple)) else []
        try:
            model = ActivityModel.from_route(
                route_coordinates,
                route_name,
                route_duration_s,
            )
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, self.tr("open_error"), str(error))
            return
        panel = self._route_panel
        if panel is not None:
            panel.close_mode()
        document = TrackDocument(
            model=model,
            colour=TRACK_COLOURS[len(self.tracks) % len(TRACK_COLOURS)],
        )
        self.tracks.append(document)
        self._add_track_list_item(document)
        self.track_list.setCurrentRow(len(self.tracks) - 1)
        self._set_loaded(True)
        self.refresh_plots(reset_region=True, fit_map=True)
        self.statusBar().showMessage(self.tr(
            "loaded", tracks=f"{len(self.tracks):,}",
            count=f"{sum(len(track.model.points) for track in self.tracks):,}",
        ))

    def load_activity(self, path: str) -> None:
        """Backward-compatible single-file entry point."""
        self.load_activities([path])

    def _add_track_list_item(self, document: TrackDocument) -> None:
        item = QtWidgets.QListWidgetItem()
        item.setFlags(
            item.flags()
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
        )
        item.setSizeHint(QtCore.QSize(0, 34))
        item.setToolTip(str(document.model.path))
        self.track_list.addItem(item)

        row_widget = TrackListRow(document.model.path.name, document.colour, self.track_list)
        row_widget.set_language(self.tr("track_visibility"), self.tr("remove_track"))
        row_widget.activated.connect(lambda item=item: self.track_list.setCurrentItem(item))
        row_widget.visibilityChanged.connect(
            lambda visible, item=item: self._track_visibility_changed(item, visible)
        )
        row_widget.removeRequested.connect(lambda item=item: self._remove_track_item(item))
        self.track_list.setItemWidget(item, row_widget)

    def load_activities(self, paths: list[str]) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        errors: list[str] = []
        warning_count = 0
        first_new_row = len(self.tracks)
        known_paths = {str(track.model.path.resolve()).casefold() for track in self.tracks}
        try:
            for path in paths:
                source = Path(path)
                key = str(source.resolve()).casefold()
                if key in known_paths:
                    continue
                try:
                    model = ActivityModel.load(source)
                except Exception as error:
                    errors.append(f"{source.name}: {error}")
                    continue
                colour = TRACK_COLOURS[len(self.tracks) % len(TRACK_COLOURS)]
                self.tracks.append(TrackDocument(model=model, colour=colour))
                known_paths.add(key)
                warning_count += len(detect_gps_anomalies(model, "cycling"))

                self._add_track_list_item(self.tracks[-1])

            if len(self.tracks) > first_new_row:
                self.track_list.setCurrentRow(first_new_row)
                self._set_loaded(True)
                self.refresh_map(fit=True)
                total_points = sum(len(track.model.points) for track in self.tracks)
                self.statusBar().showMessage(self.tr(
                    "loaded", tracks=f"{len(self.tracks):,}", count=f"{total_points:,}"
                ))
            elif not self.tracks:
                self.map_widget.set_tracks([], fit=False)
                self._set_loaded(False)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if errors:
            QtWidgets.QMessageBox.warning(self, self.tr("open_error"), "\n".join(errors))
        if warning_count:
            dialog = TrackWarningDialog(
                warning_count,
                TRANSLATIONS[self.language],
                self.theme,
                self,
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.check_gps_dialog()

    def _update_header(self) -> None:
        self.save_action.setToolTip(
            self.tr("save_hint_multiple") if len(self.tracks) > 1
            else self.tr("save_hint_single")
        )
        if self.model:
            self.header.setText(self.tr(
                "track_count", name=self.model.path.name, count=f"{len(self.tracks):,}"
            ))
        else:
            self.header.setText(self.tr("drop"))

    @staticmethod
    def _document_local_bounds(document: TrackDocument) -> tuple[float, float]:
        indices = np.flatnonzero(document.model.active)
        if not len(indices):
            return 0.0, 0.0
        values = np.array([document.model.points[index].t for index in indices], dtype=float)
        finite = values[np.isfinite(values)]
        if not len(finite):
            return 0.0, 0.0
        return float(np.min(finite)), float(np.max(finite))

    @staticmethod
    def _document_absolute_bounds(
        document: TrackDocument,
    ) -> tuple[float, float] | None:
        indices = np.flatnonzero(document.model.active)
        stamps: list[float] = []
        for index in indices:
            value = document.model.points[index].timestamp_dt
            if value is None:
                continue
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            stamps.append(value.timestamp())
        return (min(stamps), max(stamps)) if stamps else None

    def _compute_timeline_layout(self) -> None:
        """Align simultaneous recordings and concatenate separate fragments."""
        dated: list[tuple[int, float, float, float, float]] = []
        undated: list[tuple[int, float, float]] = []
        empty: list[int] = []
        for index, document in enumerate(self.tracks):
            if not document.model.active.any():
                empty.append(index)
                continue
            local_start, local_end = self._document_local_bounds(document)
            absolute = self._document_absolute_bounds(document)
            if absolute is None:
                undated.append((index, local_start, local_end))
            else:
                dated.append((index, absolute[0], absolute[1], local_start, local_end))

        dated.sort(key=lambda item: (item[1], item[0]))
        groups: list[list[tuple[int, float, float, float, float]]] = []
        group_end = -math.inf
        overlap_tolerance = 2.0
        for item in dated:
            if not groups or item[1] > group_end + overlap_tolerance:
                groups.append([item])
                group_end = item[2]
            else:
                groups[-1].append(item)
                group_end = max(group_end, item[2])

        self._timeline_order = []
        self._timeline_separators = []
        cursor = 0.0
        gap = 5.0
        group_number = 0
        for group in groups:
            group_start = min(item[1] for item in group)
            group_end = max(item[2] for item in group)
            for index, absolute_start, _absolute_end, local_start, local_end in group:
                document = self.tracks[index]
                document.timeline_offset = cursor + (absolute_start - group_start) - local_start
                document.timeline_start = local_start + document.timeline_offset
                document.timeline_end = local_end + document.timeline_offset
                document.timeline_group = group_number
                self._timeline_order.append(index)
            cursor += max(0.0, group_end - group_start)
            group_number += 1
            if group_number < len(groups) or undated:
                self._timeline_separators.append(cursor + gap / 2.0)
                cursor += gap

        for position, (index, local_start, local_end) in enumerate(undated):
            document = self.tracks[index]
            document.timeline_offset = cursor - local_start
            document.timeline_start = cursor
            document.timeline_end = cursor + max(0.0, local_end - local_start)
            document.timeline_group = group_number
            self._timeline_order.append(index)
            cursor = document.timeline_end
            group_number += 1
            if position < len(undated) - 1:
                self._timeline_separators.append(cursor + gap / 2.0)
                cursor += gap

        for index in empty:
            document = self.tracks[index]
            document.timeline_offset = cursor
            document.timeline_start = cursor
            document.timeline_end = cursor
            document.timeline_group = group_number
            self._timeline_order.append(index)

        if not self._timeline_order:
            self._timeline_order = list(range(len(self.tracks)))
        self._telemetry_duration = max(
            1.0,
            *(document.timeline_end for document in self.tracks),
        )

    def _global_times(self, document: TrackDocument, field: str) -> tuple[np.ndarray, np.ndarray]:
        data = self._record_index(document)
        x, values = data.times[document.model.active], data.values[field][document.model.active]
        return x + document.timeline_offset, values

    def _record_index(self, document):
        key = id(document.model)
        if key not in self._record_indices:
            self._record_indices[key] = RecordIndex(document.model)
        return self._record_indices[key]

    def _track_index_at_time(self, seconds: float) -> int:
        candidates = [
            index for index, document in enumerate(self.tracks)
            if document.timeline_start - 0.01 <= seconds <= document.timeline_end + 0.01
            and bool(document.model.active.any())
        ]
        if self.active_track_index in candidates:
            return self.active_track_index
        return candidates[0] if candidates else -1

    def _global_selection_mask(
        self, document: TrackDocument, start: float, end: float
    ) -> np.ndarray:
        low, high = sorted((float(start), float(end)))
        times = self._record_index(document).times
        return document.model.active & (times >= low-document.timeline_offset) & (times <= high-document.timeline_offset)

    def _active_track_changed(self, row: int) -> None:
        if not 0 <= row < len(self.tracks):
            return
        self._hide_hover_feedback()
        self.active_track_index = row
        self._selection_drag_start = None
        self._selection_drag_mode = None
        self._selection_drag_initial_region = None
        self._selection_user_defined = False
        self._update_header()
        self.file_label.setText(str(self.model.path) if self.model else "—")
        self.note.setText(
            self.tr("note_fit") if self.model and self.model.source_format == "fit" else self.tr("note_xml")
        )
        for item_row in range(self.track_list.count()):
            item = self.track_list.item(item_row)
            row_widget = self.track_list.itemWidget(item)
            if isinstance(row_widget, TrackListRow):
                row_widget.set_active(item_row == row)
        self._set_loaded(True)
        self.refresh_plots(reset_region=True, fit_map=False)

    def _track_visibility_changed(self, item: QtWidgets.QListWidgetItem, visible: bool) -> None:
        row = self.track_list.row(item)
        if 0 <= row < len(self.tracks):
            self.tracks[row].visible = bool(visible)
            self._hide_hover_feedback()
            self.refresh_map(fit=False)

    def _remove_track_item(self, item: QtWidgets.QListWidgetItem) -> None:
        row = self.track_list.row(item)
        if not 0 <= row < len(self.tracks):
            return
        removed_name = self.tracks[row].model.path.name
        old_active = self.active_track_index
        row_widget = self.track_list.itemWidget(item)

        blocker = QtCore.QSignalBlocker(self.track_list)
        self.track_list.removeItemWidget(item)
        self.track_list.takeItem(row)
        self.tracks.pop(row)
        if isinstance(row_widget, TrackListRow):
            row_widget.deleteLater()

        if self.tracks:
            if row < old_active:
                new_active = old_active - 1
            elif row == old_active:
                new_active = min(row, len(self.tracks) - 1)
            else:
                new_active = old_active
            new_active = max(0, min(new_active, len(self.tracks) - 1))
            self.track_list.setCurrentRow(new_active)
        else:
            new_active = -1
            self.track_list.setCurrentRow(-1)
        del blocker

        # Commands may reference the removed model, so retaining them would
        # make a later Undo resurrect an invisible document.
        self.undo_stack.clear()
        if new_active >= 0:
            self._active_track_changed(new_active)
            self.refresh_map(fit=True)
        else:
            self.active_track_index = -1
            self._clear_activity_ui()
        self.statusBar().showMessage(self.tr("track_removed", name=removed_name))

    def _clear_activity_ui(self) -> None:
        self._selection_refresh_timer.stop()
        self._smooth_timer.stop()
        self._record_indices.clear()
        self._smooth_cache.clear()
        self._hide_hover_feedback()
        self.header.setText(self.tr("drop"))
        self.file_label.setText("—")
        self.note.setText("")
        self.summary.clear()
        self.selection_summary.clear()
        self.selection_label.setText(f"{self.tr('selection')}: —")
        self.telemetry_values.setText(f"{self.tr('cursor')}: —")
        self.telemetry_track_names.setText("")
        self.track_legend_scroll.setFixedHeight(24)
        self._syncing_x = True
        self.graph_stack.prepare([], combined=True)
        self._activate_panel("combined")
        self._syncing_x = False
        self._update_plot_labels()
        self._cursor_line = None
        self._cursor_points = None
        self._regions.clear()
        self._telemetry_data.clear()
        self._telemetry_plot_data.clear()
        self._telemetry_by_track.clear()
        self._telemetry_plot_by_track.clear()
        self._telemetry_gps_by_track.clear()
        self._telemetry_gps = (np.array([]), np.array([]), np.array([]))
        self._selection_user_defined = False
        self.selection_toolbar.hide()
        self.selection_card.hide()
        self.map_widget.set_tracks([], fit=False)
        self._update_metric_availability()
        self._set_loaded(False)

    def _current_region(self) -> tuple[float, float]:
        if self._regions:
            start, end = self._regions[0].getRegion()
            return float(start), float(end)
        if self.tracks:
            return 0.0, self._telemetry_duration
        return 0.0, 0.0

    def _region_changed(self) -> None:
        self._update_selection_label()
        if self._selection_drag_start is not None:
            if not self._selection_refresh_timer.isActive():
                self._selection_refresh_timer.start()
        else:
            self._selection_refresh_timer.stop()
            self._refresh_selection_details()
        self._position_selection_toolbar()

    def _refresh_selection_details(self) -> None:
        self._update_selection_summary()
        self._update_map_selection()

    def _update_map_selection(self) -> None:
        selected = []
        if self._selection_user_defined:
            start, end = self._current_region()
            for document in self.tracks:
                if not document.visible:
                    continue
                mask = self._global_selection_mask(document, start, end)
                lon, lat = self._record_index(document).route_coordinates(mask)
                selected.append({"lon": lon, "lat": lat, "colour": document.colour})
        self.map_widget.set_selection(selected)

    def _chart_mode_changed(self) -> None:
        if self.model:
            self._render_telemetry(self._current_region())

    def _sport_changed(self) -> None:
        self._update_summary()
        self._update_selection_summary()

    def _activate_panel(self, key: str) -> None:
        if not hasattr(self, "graph_stack") or key not in self.graph_stack.visible_keys:
            return
        panel = self.graph_stack.panels[key]
        changed = self._active_panel_key != key
        self._active_panel_key = key
        self.telemetry_plot, self.telemetry_view_box = panel.plot, panel.view
        self._cursor_line, self._cursor_points = panel.cursor_line, panel.cursor_points
        for name in ("telemetry_bubble", "selection_toolbar"):
            overlay = getattr(self, name, None)
            if overlay is not None and overlay.parent() is not panel.plot.viewport():
                overlay.setParent(panel.plot.viewport())
        if changed:
            self._position_selection_toolbar()

    def _panel_mouse_moved(self, key, event) -> None:
        if key != self._active_panel_key or key not in self.graph_stack.visible_keys or self._selection_drag_start is not None:
            return
        self._telemetry_mouse_moved(event)

    def _sync_x_range(self, bounds) -> None:
        if getattr(self, "_syncing_x", True) or not hasattr(self, "graph_stack"):
            return
        self._syncing_x = True
        try:
            for key in self.graph_stack.visible_keys:
                self.graph_stack.panels[key].plot.setXRange(*bounds, padding=0)
        finally:
            self._syncing_x = False

    def _update_selection_label(self) -> None:
        start, end = self._current_region()
        self.selection_label.setText(
            f"{self.tr('selection')}: {fmt_time_long(start, self.language)} — {fmt_time_long(end, self.language)}  ({fmt_time_long(abs(end - start), self.language)})"
            if self.model else f"{self.tr('selection')}: —"
        )
        if hasattr(self, "selection_card"):
            self.selection_card.setVisible(bool(self.model and self._selection_user_defined))

    def _metric_visibility_changed(self) -> None:
        sender = self.sender()
        if isinstance(sender, QtWidgets.QToolButton) and sender.isEnabled():
            for field, button in self.metric_checks.items():
                if sender is button:
                    self._metric_preferences[field] = button.isChecked()
                    break
        if self.model:
            self._render_telemetry(self._current_region())

    def _update_metric_availability(self) -> None:
        """Grey out metrics that have no useful samples in any loaded track."""
        for field, button in self.metric_checks.items():
            available = False
            for document in self.tracks:
                x, values = self._global_times(document, field)
                finite_values = values[np.isfinite(x) & np.isfinite(values)]
                track_has_values = bool(len(finite_values))
                # Some recorders create cadence/HR/power fields filled only
                # with zero when no matching sensor exists. A zero can be a
                # valid sample inside a real series, but an all-zero series is
                # an absent metric rather than useful telemetry.
                if field in {"heart_rate", "cadence", "power"}:
                    track_has_values = bool((finite_values > 0.0).any())
                if track_has_values:
                    available = True
                    break

            blocker = QtCore.QSignalBlocker(button)
            button.setEnabled(available)
            button.setChecked(available and self._metric_preferences[field])
            del blocker
            button.setCursor(
                QtCore.Qt.CursorShape.PointingHandCursor
                if available else QtCore.Qt.CursorShape.ArrowCursor
            )
            button.setToolTip(
                f"{self.tr(field)} [{METRICS[field]['unit']}]"
                if available
                else self.tr("metric_unavailable", metric=self.tr(field))
            )

    def _smooth_changed(self, value: int) -> None:
        self.smooth_value.setText(str(value))
        self._smooth_timer.start()

    def _apply_smoothing(self) -> None:
        if self.model:
            self._render_telemetry(self._current_region())

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        key = next((key for key, panel in self.graph_stack.panels.items()
                    if watched is panel.plot.viewport()), None) if hasattr(self, "graph_stack") else None
        if key is not None and key in self.graph_stack.visible_keys:
            if event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove}:
                self._activate_panel(key)
            event_type = event.type()
            if event_type == QtCore.QEvent.Type.Resize:
                QtCore.QTimer.singleShot(0, self._position_selection_toolbar)
            if event_type == QtCore.QEvent.Type.Leave:
                self.telemetry_plot.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
                self._hide_hover_feedback()
                return False
            if not self.model:
                return super().eventFilter(watched, event)
            mouse_types = {
                QtCore.QEvent.Type.MouseButtonPress,
                QtCore.QEvent.Type.MouseMove,
                QtCore.QEvent.Type.MouseButtonRelease,
            }
            if event_type in mouse_types:
                mouse_event = event
                scene_position = self.telemetry_plot.mapToScene(mouse_event.position().toPoint())  # type: ignore[attr-defined]
                if event_type == QtCore.QEvent.Type.MouseButtonPress:
                    if (
                        mouse_event.button() == QtCore.Qt.MouseButton.LeftButton  # type: ignore[attr-defined]
                        and self.telemetry_view_box.sceneBoundingRect().contains(scene_position)
                    ):
                        seconds = self._selection_time(scene_position)
                        self._selection_drag_start = seconds
                        self._hide_hover_feedback()
                        self._selection_drag_mode = self._selection_hit_mode(
                            scene_position, seconds
                        )
                        self.selection_toolbar.hide()
                        if self._selection_drag_mode == "create":
                            self._selection_drag_initial_region = None
                            self._selection_user_defined = True
                            self._set_selection_region(seconds, seconds)
                        else:
                            self._selection_drag_initial_region = self._current_region()
                        self.telemetry_plot.viewport().setCursor(
                            self._selection_cursor(self._selection_drag_mode, pressed=True)
                        )
                        return True
                elif self._selection_drag_start is not None:
                    if event_type == QtCore.QEvent.Type.MouseMove:
                        self._update_selection_drag(self._selection_time(scene_position))
                        return True
                    if (
                        event_type == QtCore.QEvent.Type.MouseButtonRelease
                        and mouse_event.button() == QtCore.Qt.MouseButton.LeftButton  # type: ignore[attr-defined]
                    ):
                        seconds = self._selection_time(scene_position)
                        self._update_selection_drag(seconds)
                        self._selection_drag_start = None
                        self._selection_drag_mode = None
                        self._selection_drag_initial_region = None
                        start, end = self._current_region()
                        self._selection_user_defined = end - start > 0.001
                        # Do not leave the crosshair/resize cursor behind after
                        # a completed drag; the old cursor produced a visible
                        # trail on some Qt/Windows combinations.
                        self.telemetry_plot.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
                        self._set_selection_region(start, end)
                        return True
                elif event_type == QtCore.QEvent.Type.MouseMove:
                    seconds = self._selection_time(scene_position)
                    self.telemetry_plot.viewport().setCursor(
                        self._selection_cursor(
                            self._selection_hit_mode(scene_position, seconds)
                        )
                    )
        return super().eventFilter(watched, event)

    def _selection_time(self, scene_position: QtCore.QPointF) -> float:
        duration = max(0.0, self._telemetry_duration if self.model else 0.0)
        seconds = float(self.telemetry_view_box.mapSceneToView(scene_position).x())
        return max(0.0, min(seconds, duration))

    def _set_selection_region(self, first: float, second: float) -> None:
        if not self._regions:
            return
        low, high = sorted((float(first), float(second)))
        for region in self._regions:
            region.setRegion((low, high))
            region.setVisible(self._selection_user_defined)
        self._region_changed()

    def _selection_is_movable_at(self, seconds: float) -> bool:
        """The middle of a real selection acts as its drag handle."""
        if not self.model or not self._regions:
            return False
        low, high = self._current_region()
        duration = max(0.0, self._telemetry_duration)
        epsilon = max(0.001, duration * 1e-6)
        is_full_range = low <= epsilon and high >= duration - epsilon
        return not is_full_range and high - low > epsilon and low <= seconds <= high

    def _selection_hit_mode(
        self, scene_position: QtCore.QPointF, seconds: float
    ) -> str:
        """Resolve edge resize, body move or new-selection mode in pixels."""
        if self._regions and self.model and self._selection_user_defined:
            low, high = self._current_region()
            left_x = self.telemetry_view_box.mapViewToScene(
                QtCore.QPointF(low, 0.0)
            ).x()
            right_x = self.telemetry_view_box.mapViewToScene(
                QtCore.QPointF(high, 0.0)
            ).x()
            left_distance = abs(scene_position.x() - left_x)
            right_distance = abs(scene_position.x() - right_x)
            edge_tolerance = 8.0
            if min(left_distance, right_distance) <= edge_tolerance:
                return "resize_left" if left_distance <= right_distance else "resize_right"
            if self._selection_is_movable_at(seconds):
                return "move"
        return "create"

    @staticmethod
    def _selection_cursor(mode: str, pressed: bool = False) -> QtCore.Qt.CursorShape:
        if mode in {"resize_left", "resize_right"}:
            return QtCore.Qt.CursorShape.SizeHorCursor
        if mode == "move":
            return (
                QtCore.Qt.CursorShape.ClosedHandCursor
                if pressed else QtCore.Qt.CursorShape.OpenHandCursor
            )
        return QtCore.Qt.CursorShape.CrossCursor

    def _update_selection_drag(self, seconds: float) -> None:
        if self._selection_drag_start is None:
            return
        if self._selection_drag_mode == "create" or self._selection_drag_initial_region is None:
            self._set_selection_region(self._selection_drag_start, seconds)
            return

        initial_low, initial_high = self._selection_drag_initial_region
        duration = max(0.0, self._telemetry_duration if self.model else 0.0)
        minimum_width = max(0.001, duration * 1e-6)
        if self._selection_drag_mode == "resize_left":
            low = max(0.0, min(seconds, initial_high - minimum_width))
            self._set_selection_region(low, initial_high)
            return
        if self._selection_drag_mode == "resize_right":
            high = min(duration, max(seconds, initial_low + minimum_width))
            self._set_selection_region(initial_low, high)
            return

        width = max(0.0, initial_high - initial_low)
        proposed_low = initial_low + (seconds - self._selection_drag_start)
        low = max(0.0, min(proposed_low, max(0.0, duration - width)))
        self._set_selection_region(low, min(duration, low + width))

    def _position_selection_toolbar(self, *_args: object) -> None:
        if not hasattr(self, "selection_toolbar"):
            return
        if (
            not self._selection_user_defined
            or not self._regions
            or self._selection_drag_start is not None
        ):
            self.selection_toolbar.hide()
            return
        start, end = self._current_region()
        if end - start <= 0.001:
            self.selection_toolbar.hide()
            return
        midpoint = (start + end) / 2.0
        scene_position = self.telemetry_view_box.mapViewToScene(
            QtCore.QPointF(midpoint, self.telemetry_view_box.viewRange()[1][1])
        )
        widget_position = self.telemetry_plot.mapFromScene(scene_position)
        viewport = self.telemetry_plot.viewport()
        local_position = viewport.mapFrom(self.telemetry_plot, widget_position)
        self.selection_toolbar.adjustSize()
        x = int(local_position.x() - self.selection_toolbar.width() / 2)
        x = max(8, min(x, viewport.width() - self.selection_toolbar.width() - 8))
        plot_top = self.telemetry_plot.mapFromScene(self.telemetry_view_box.sceneBoundingRect().topLeft()).y()
        self.selection_toolbar.move(x, max(8, plot_top+8))
        self.selection_toolbar.show()
        self.selection_toolbar.raise_()

    @staticmethod
    def _parse_time_text(value: str) -> float | None:
        parts = value.strip().split(":")
        try:
            numbers = [float(part.replace(",", ".")) for part in parts]
        except ValueError:
            return None
        if len(numbers) == 3:
            hours, minutes, seconds = numbers
        elif len(numbers) == 2:
            hours, minutes, seconds = 0.0, numbers[0], numbers[1]
        elif len(numbers) == 1:
            hours, minutes, seconds = 0.0, 0.0, numbers[0]
        else:
            return None
        if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
            return None
        return hours * 3600.0 + minutes * 60.0 + seconds

    def edit_selection_bounds(self) -> None:
        if not self.model or not self._regions:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("selection_edit_title"))
        layout = QtWidgets.QVBoxLayout(dialog)
        hint = QtWidgets.QLabel(self.tr("selection_time_hint"))
        hint.setObjectName("muted")
        layout.addWidget(hint)
        form = QtWidgets.QFormLayout()
        start, end = self._current_region()
        start_edit = QtWidgets.QLineEdit(fmt_time(start))
        end_edit = QtWidgets.QLineEdit(fmt_time(end))
        form.addRow(self.tr("selection_start"), start_edit)
        form.addRow(self.tr("selection_end"), end_edit)
        layout.addLayout(form)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        new_start = self._parse_time_text(start_edit.text())
        new_end = self._parse_time_text(end_edit.text())
        if (
            new_start is None
            or new_end is None
            or new_end <= new_start
            or new_start < 0.0
            or new_end > self._telemetry_duration
        ):
            QtWidgets.QMessageBox.warning(
                self, self.tr("selection_edit_title"), self.tr("selection_time_error")
            )
            return
        self._selection_user_defined = True
        self._set_selection_region(new_start, new_end)
        self._position_selection_toolbar()

    def _update_plot_labels(self) -> None:
        has_timing = any(
            getattr(document.model, "has_timing", True) for document in self.tracks
        )
        for key in self.graph_stack.visible_keys:
            panel = self.graph_stack.panels[key]
            title = "" if key == "combined" else f"{self.tr(key)} [{METRICS[key]['unit']}]"
            colour = "#9ba3af" if key == "combined" else str(METRICS[key]["colour"])
            panel.title.setText(title)
            panel.title.setStyleSheet(f"color:{colour}; font-size:11px; font-weight:600;")
            if key != "combined":
                panel.stats.setStyleSheet(
                    f"color:{colour}; font-size:11px; background:transparent;"
                )
            panel._position_header()
            panel.plot.getAxis("bottom").language = self.language
            panel.plot.getAxis("bottom").picture = None
            panel.plot.getAxis("bottom").update()
            is_bottom = key == self.graph_stack.visible_keys[-1]
            panel.plot.getAxis("bottom").setStyle(showValues=is_bottom and has_timing)
            panel.plot.getAxis("bottom").setHeight(44 if is_bottom and has_timing else 4)
            if is_bottom and has_timing:
                panel.plot.setLabel("bottom", self.tr("time_axis"), color="#858d98")
            else:
                panel.plot.setLabel("bottom", "")

    def _update_distance_axis(self) -> None:
        segments, names = distance_segments(self.tracks, self._record_indices, self.active_track_index)
        self._distance_reference_names = names
        panel = self.graph_stack.panels[self.graph_stack.visible_keys[0]]
        axis = panel.plot.getAxis("top")
        axis.set_segments(segments)
        if not segments:
            panel.plot.hideAxis("top")
            return
        panel.plot.showAxis("top")
        panel.plot.setLabel("top", "Дистанция, км" if self.language == "ru" else "Distance, km", color="#858d98")
        axis.setHeight(44)
        axis.setToolTip(
            ("По доступным данным. Для наложенных записей используется активный трек. Источники: "
             if self.language == "ru" else
             "Available recorded distance. Overlapping recordings use the active track. Sources: ")
            + ", ".join(names)
        )

    def _update_track_legend(self) -> None:
        # Track colour and filename now live directly on the map, where the
        # relationship is useful and no vertical chart space is consumed.
        if hasattr(self, "telemetry_track_names"):
            self.telemetry_track_names.clear()
            self.track_legend_scroll.setFixedHeight(0)
            self.track_legend_scroll.hide()

    def refresh_plots(self, reset_region: bool = False, fit_map: bool = False) -> None:
        if not self.model:
            return
        self._selection_refresh_timer.stop()
        self._smooth_timer.stop()
        self._smooth_cache.clear()
        model_ids = {id(document.model) for document in self.tracks}
        self._record_indices = {key: value for key, value in self._record_indices.items() if key in model_ids}
        for document in self.tracks:
            self._record_index(document)
        self._compute_timeline_layout()
        duration = max(0.0, self._telemetry_duration)
        if reset_region:
            old_region = (0.0, duration)
            self._selection_user_defined = False
        else:
            start, end = self._current_region()
            old_region = (max(0.0, min(start, duration)), max(0.0, min(end, duration)))
        self._update_metric_availability()
        self.refresh_map(fit=fit_map)
        self._render_telemetry(old_region, reset_view=reset_region)
        self._update_summary()

    def refresh_map(self, fit: bool = False) -> None:
        map_tracks: list[dict[str, object]] = []
        for index, document in enumerate(self.tracks):
            if not document.visible:
                continue
            longitude, latitude = self._record_index(document).route_coordinates(
                document.model.active
            )
            map_tracks.append({
                "lon": longitude,
                "lat": latitude,
                "colour": document.colour,
                "active": index == self.active_track_index,
                "name": document.model.path.name,
            })
        self.map_widget.set_tracks(map_tracks, fit=fit)
        self._update_map_selection()

    def _render_telemetry(self, region_values: tuple[float, float], reset_view: bool = False) -> None:
        if not self.model:
            return
        self._hide_hover_feedback()
        old_x_range = self.telemetry_view_box.viewRange()[0]
        fields = [field for field in METRICS if self.metric_checks[field].isChecked()]
        self._syncing_x = True
        self.graph_stack.prepare(fields, combined=self.chart_mode.currentIndex() == 1)
        self._activate_panel(self.graph_stack.visible_keys[0])
        self._regions.clear()
        self._telemetry_by_track.clear()
        self._telemetry_plot_by_track.clear()
        self._telemetry_gps_by_track.clear()
        ranges = {key: [] for key in self.graph_stack.visible_keys}
        raw_stats = {field: [] for field in fields}
        for track_index in sorted(self._timeline_order, key=lambda i: i == self.active_track_index):
            document = self.tracks[track_index]
            self._telemetry_by_track[track_index] = {}
            self._telemetry_plot_by_track[track_index] = {}
            for field, specification in METRICS.items():
                x, raw = self._global_times(document, field)
                raw = raw * float(specification["factor"])
                valid = np.isfinite(x) & np.isfinite(raw)
                if field in {"heart_rate", "cadence", "power"} and not (raw[valid] > 0).any():
                    valid[:] = False
                self._telemetry_by_track[track_index][field] = (x[valid], raw[valid])
                if field not in fields:
                    continue
                if not valid.any() or (field in {"heart_rate", "cadence", "power"} and
                                       not (raw[valid] > 0).any()):
                    continue
                key = "combined" if "combined" in ranges else field
                panel = self.graph_stack.panels[key]
                raw_stats[field].append(raw[valid])
                ranges[key].append(raw[valid])
                cache_key = (id(document.model), field, self.smooth_slider.value())
                if cache_key not in self._smooth_cache:
                    if len(self._smooth_cache) >= max(10, len(self.tracks)*len(METRICS)*2):
                        self._smooth_cache.clear()
                    self._smooth_cache[cache_key] = display_series(x, raw, self.smooth_slider.value())
                plot_x, plot_y = self._smooth_cache[cache_key]
                plot_valid = np.isfinite(plot_x) & np.isfinite(plot_y)
                colour = QtGui.QColor(str(specification["colour"]))
                active = track_index == self.active_track_index
                if not active:
                    colour.setAlpha(160)
                pen = pg.mkPen(colour, width=2.1 if active else 1.6)
                pen.setCapStyle(QtCore.Qt.RoundCap)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                curve = panel.plot.plot(plot_x, plot_y, pen=pen, connect="finite", antialias=True)
                curve.setClipToView(True)
                curve.setDownsampling(auto=True, method="peak")
                curve.curve.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.DeviceCoordinateCache)
                self._telemetry_plot_by_track[track_index][field] = (
                    plot_x[plot_valid], plot_y[plot_valid]
                )
            gps_time, latitude = self._global_times(document, "lat")
            _, longitude = self._global_times(document, "lon")
            valid = np.isfinite(gps_time) & np.isfinite(latitude) & np.isfinite(longitude)
            self._telemetry_gps_by_track[track_index] = (
                gps_time[valid], latitude[valid], longitude[valid]
            )
        self._telemetry_data = self._telemetry_by_track.get(self.active_track_index, {})
        self._telemetry_plot_data = self._telemetry_plot_by_track.get(self.active_track_index, {})
        self._telemetry_gps = self._telemetry_gps_by_track.get(
            self.active_track_index, (np.array([]), np.array([]), np.array([]))
        )
        duration = max(1.0, self._telemetry_duration)
        start, end = sorted(max(0.0, min(float(v), duration)) for v in region_values)
        for key in self.graph_stack.visible_keys:
            panel = self.graph_stack.panels[key]
            for separator in self._timeline_separators:
                panel.plot.addItem(pg.InfiniteLine(
                    pos=separator, angle=90, movable=False,
                    pen=pg.mkPen("#505866", width=1, style=QtCore.Qt.DashLine)
                ))
            region = pg.LinearRegionItem(
                values=(start, end), bounds=(0.0, duration), movable=False,
                brush=pg.mkBrush(77, 163, 255, 34), pen=pg.mkPen("#d7e8ff", width=1.2)
            )
            region.setZValue(10)
            region.setVisible(self._selection_user_defined)
            panel.plot.addItem(region)
            self._regions.append(region)
            panel.cursor_line = pg.InfiniteLine(
                angle=90, movable=False, pen=pg.mkPen("#a8b5c9", width=1)
            )
            panel.cursor_points = pg.ScatterPlotItem()
            for overlay in (panel.cursor_line, panel.cursor_points):
                overlay.setZValue(30)
                panel.plot.addItem(overlay)
                overlay.hide()
            if ranges[key]:
                values = np.concatenate(ranges[key])
                low, high = float(np.min(values)), float(np.max(values))
                padding = max(abs(high) * 0.01, 1.0, (high - low) * 0.08)
                panel.y_range = (low - padding, high + padding)
            else:
                panel.y_range = (0.0, 1.0)
            panel.view.setLimits(xMin=0.0, xMax=duration, minXRange=min(1.0, duration))
            panel.plot.setYRange(*panel.y_range, padding=0)
            panel.plot.setXRange(*( (0.0, duration) if reset_view else old_x_range ), padding=0)
            stats_fields = fields if key == "combined" else [key]
            rows = []
            for field in stats_fields:
                if not raw_stats[field]:
                    continue
                values = np.concatenate(raw_stats[field])
                labels = ("мин", "макс", "ср") if self.language == "ru" else ("min", "max", "avg")
                prefix = self.tr(field) + ": " if key == "combined" else ""
                text = (
                    f"{prefix}{labels[0]} {np.min(values):.1f} · "
                    f"{labels[1]} {np.max(values):.1f} · "
                    f"{labels[2]} {np.mean(values):.1f} {METRICS[field]['unit']}"
                )
                if key == "combined":
                    rows.append(
                        f"<span style='color:{METRICS[field]['colour']}'>{html.escape(text)}</span>"
                    )
                else:
                    rows.append(html.escape(text))
            panel.stats.setText("<br>".join(rows))
            panel.stats.setToolTip(
                "Исходные данные всех загруженных треков; сглаживание не меняет статистику."
                if self.language == "ru" else
                "Original samples of all loaded tracks; smoothing does not change statistics."
            )
            panel._position_header()
        self._cursor_line = self.graph_stack.panels[self._active_panel_key].cursor_line
        self._cursor_points = self.graph_stack.panels[self._active_panel_key].cursor_points
        self._syncing_x = False
        self._update_plot_labels()
        self._update_distance_axis()
        self._region_changed()
        self._update_track_legend()

    def reset_telemetry_view(self) -> None:
        if not self.model:
            return
        self._sync_x_range((0.0, self._telemetry_duration))

    def zoom_to_selection(self) -> None:
        start, end = self._current_region()
        if end > start:
            self._sync_x_range((start, end))

    def _telemetry_mouse_moved(self, event) -> None:
        if not self.model:
            return
        position = event[0] if isinstance(event, tuple) else event
        if not self.telemetry_view_box.sceneBoundingRect().contains(position):
            self._hide_hover_feedback()
            return
        seconds = float(self.telemetry_view_box.mapSceneToView(position).x())
        if seconds < 0 or seconds > self._telemetry_duration:
            self._hide_hover_feedback()
            return
        track_index = self._track_index_at_time(seconds)
        if track_index < 0:
            self._hide_hover_feedback()
            return
        document = self.tracks[track_index]
        track_data = self._telemetry_by_track.get(track_index, {})
        track_plot_data = self._telemetry_plot_by_track.get(track_index, {})

        values: list[str] = []
        bubble_rows: list[str] = []
        spots_by_panel = {key: [] for key in self.graph_stack.visible_keys}
        for field, specification in METRICS.items():
            if not self.metric_checks[field].isChecked():
                continue
            x, data = track_data.get(field, (np.array([]), np.array([])))
            if not len(x):
                continue
            index = self._nearest_index(x, seconds)
            value = data[index]
            if math.isfinite(value):
                colour = str(specification["colour"])
                values.append(
                    f"<span style='color:{colour}'>{self.tr(field)}: {value:.1f} {specification['unit']}</span>"
                )
                bubble_rows.append(
                    f"<span style='color:{colour}'>● <b>{html.escape(self.tr(field))}</b></span>"
                    f": {value:.1f} {specification['unit']}"
                )

            plotted_x, plotted_y = track_plot_data.get(
                field, (np.array([]), np.array([]))
            )
            if len(plotted_x):
                plotted_index = self._nearest_index(plotted_x, seconds)
                plotted_value = plotted_y[plotted_index]
                if math.isfinite(plotted_value):
                    key = "combined" if "combined" in spots_by_panel else field
                    spots_by_panel[key].append({
                        "pos": (float(plotted_x[plotted_index]), float(plotted_value)),
                        "size": 8,
                        "brush": pg.mkBrush(str(specification["colour"])),
                        "pen": pg.mkPen("#f7f9fc", width=1.2),
                    })

        details = " &nbsp; | &nbsp; ".join(values) if values else self.tr("no_values")
        self.telemetry_values.setText(f"{self.tr('cursor')}: {fmt_time_long(seconds, self.language)} &nbsp; {details}")

        for key, spots in spots_by_panel.items():
            panel = self.graph_stack.panels[key]
            if panel.cursor_line is not None:
                panel.cursor_line.setValue(seconds)
                panel.cursor_line.show()
            if panel.cursor_points is not None:
                panel.cursor_points.setData(spots=spots)
                panel.cursor_points.setVisible(bool(spots))

        track_name = document.model.path.name
        if len(track_name) > 42:
            track_name = track_name[:39] + "…"
        bubble_body = "<br>".join(bubble_rows) if bubble_rows else html.escape(self.tr("no_values"))
        self.telemetry_bubble.setText(
            f"<div style='color:#29313d'>"
            f"<b>{html.escape(track_name)}</b><br>"
            f"<span style='color:#697383'>{fmt_time_long(seconds, self.language)}</span><br>"
            f"{bubble_body}</div>"
        )
        self.telemetry_bubble.adjustSize()
        local_position = self.telemetry_plot.mapFromScene(position)
        bubble_x = local_position.x() + 14
        bubble_y = local_position.y() + 14
        viewport = self.telemetry_plot.viewport()
        if bubble_x + self.telemetry_bubble.width() > viewport.width() - 6:
            bubble_x = local_position.x() - self.telemetry_bubble.width() - 14
        if bubble_y + self.telemetry_bubble.height() > viewport.height() - 6:
            bubble_y = local_position.y() - self.telemetry_bubble.height() - 14
        bubble_x = max(6, min(bubble_x, viewport.width() - self.telemetry_bubble.width() - 6))
        bubble_y = max(6, min(bubble_y, viewport.height() - self.telemetry_bubble.height() - 6))
        self.telemetry_bubble.move(bubble_x, bubble_y)
        self.telemetry_bubble.show()
        self.telemetry_bubble.raise_()

        gps_time, gps_latitude, gps_longitude = self._telemetry_gps_by_track.get(
            track_index, (np.array([]), np.array([]), np.array([]))
        )
        if len(gps_time) and document.visible:
            gps_index = self._nearest_index(gps_time, seconds)
            self.map_widget.set_cursor_point(
                float(gps_latitude[gps_index]),
                float(gps_longitude[gps_index]),
                document.colour,
            )
        else:
            self.map_widget.clear_cursor_point()

    @staticmethod
    def _nearest_index(x: np.ndarray, seconds: float) -> int:
        index = int(np.searchsorted(x, seconds, side="left"))
        index = min(max(index, 0), len(x) - 1)
        if index > 0 and abs(x[index - 1] - seconds) < abs(x[index] - seconds):
            index -= 1
        return index

    def _hide_hover_feedback(self) -> None:
        if hasattr(self, "telemetry_values"):
            self.telemetry_values.setText(f"{self.tr('cursor')}: —")
        if hasattr(self, "telemetry_bubble"):
            self.telemetry_bubble.hide()
        if hasattr(self, "graph_stack"):
            for panel in self.graph_stack.panels.values():
                if panel.cursor_line is not None:
                    panel.cursor_line.hide()
                if panel.cursor_points is not None:
                    panel.cursor_points.setData([], [])
                    panel.cursor_points.hide()
                panel.plot.viewport().update()
        if hasattr(self, "telemetry_plot") and self._selection_drag_start is None:
            self.telemetry_plot.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        if hasattr(self, "map_widget"):
            self.map_widget.clear_cursor_point()

    def _update_summary(self) -> None:
        if not self.tracks:
            self.summary.clear()
            return
        masks = [(document, document.model.active.copy()) for document in self.tracks]
        total_points = sum(len(document.model.points) for document in self.tracks)
        self.summary.set_stats(self._stats_for_masks(masks, total_points))
        self.summary.setToolTip(
            "Порог движения: 0,5 м/с для велосипеда, 0,3 м/с для бега и ходьбы.<br>"
            "Удалённые участки и длинные паузы не учитываются."
            if self.language == "ru" else
            "Moving threshold: 0.5 m/s for cycling, 0.3 m/s for running/walking.<br>"
            "Removed sections and long gaps are excluded."
        )

    def _duration_for_masks(
        self, masks: list[tuple[TrackDocument, np.ndarray]],
    ) -> float:
        intervals: list[tuple[float, float]] = []
        for document, mask in masks:
            if not getattr(document.model, "has_timing", True):
                continue
            indices = np.flatnonzero(mask)
            if len(indices) < 2:
                continue
            times = self._record_index(document).times[indices]
            intervals.append((float(np.min(times))+document.timeline_offset,
                              float(np.max(times))+document.timeline_offset))
        if not intervals:
            return 0.0
        intervals.sort()
        total = 0.0
        current_start, current_end = intervals[0]
        for start, end in intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                total += current_end - current_start
                current_start, current_end = start, end
        return total + current_end - current_start

    def _stats_for_masks(self, masks, point_total: int) -> list[tuple[str, str, str, str]]:
        from .activity_stats import motion_totals, pace_text
        ru = self.language == "ru"
        sport = str(self.sport_mode.currentData())
        for document, _mask in masks:
            self._record_index(document)
        totals = motion_totals(masks, sport, self._record_indices)
        active_count = sum(int(mask.sum()) for _document, mask in masks)
        has_timing = any(
            getattr(document.model, "has_timing", True) and int(mask.sum()) >= 2
            for document, mask in masks
        )
        distance_text = f"{totals.distance / 1000:.2f} km" if totals.has_distance else "—"
        moving_text = fmt_time(totals.moving_seconds) if totals.has_motion else "—"
        stats = [
            ("clock", "#8DB8FF", "Общее время" if ru else "Elapsed time",
             fmt_time(self._duration_for_masks(masks)) if has_timing else "—"),
            ("clock", "#8DB8FF", "Время в движении" if ru else "Moving time", moving_text),
            ("distance", "#8DB8FF", self.tr("distance"), distance_text),
        ]
        elevation_gain = 0.0
        has_elevation_gain = False
        for document, mask in masks:
            data = self._record_index(document)
            altitude = data.values["altitude"]
            valid = (
                data.interval_mask(mask)
                & np.isfinite(altitude[:-1])
                & np.isfinite(altitude[1:])
            )
            if valid.any():
                elevation_gain += float(np.sum(np.maximum(0.0, np.diff(altitude)[valid])))
                has_elevation_gain = True
        if has_elevation_gain:
            stats.append((
                "altitude", "#50D890", "Набор высоты" if ru else "Elevation gain",
                f"{elevation_gain:.0f} m",
            ))
        stats.append(("points", "#8DB8FF", self.tr("records"), f"{active_count:,} / {point_total:,}"))
        if sport == "cycling":
            value = (f"{totals.moving_distance / totals.moving_seconds * 3.6:.1f} km/h"
                     if totals.moving_seconds > 0 else "—")
            caption = "Скорость в движении" if ru else "Moving speed"
        else:
            value = pace_text(totals.moving_distance, totals.moving_seconds,
                              "мин/км" if ru else "min/km")
            caption = "Темп в движении" if ru else "Moving pace"
        stats.append(("speed", "#4DA3FF", caption, value))
        for field, caption, suffix, icon in (
            ("heart_rate", self.tr("avg_hr"), " bpm", "heart"),
            ("power", self.tr("avg_power"), " W", "power"),
            ("cadence", "Средний каденс" if ru else "Average cadence", " rpm", "speed"),
        ):
            if field == "cadence" and sport != "cycling":
                continue  # Running cadence conventions differ between file producers.
            chunks = []
            for document, mask in masks:
                values = self._record_index(document).values[field][mask]
                values = values[np.isfinite(values)]
                if field == "heart_rate":
                    values = values[values > 0]
                if len(values):
                    chunks.append(values)
            if chunks:
                values = np.concatenate(chunks)
                if (values > 0).any():
                    stats.append((icon, str(METRICS[field]["colour"]), caption,
                                  f"{np.mean(values):.1f}{suffix}"))
        return stats

    def _update_selection_summary(self) -> None:
        if not self.tracks or not self._selection_user_defined:
            self.selection_summary.clear()
            self.selection_card.hide()
            return
        start, end = self._current_region()
        masks = [
            (document, self._global_selection_mask(document, start, end))
            for document in self.tracks
        ]
        total_active = sum(int(document.model.active.sum()) for document in self.tracks)
        self.selection_summary.set_stats(self._stats_for_masks(masks, total_active))
        self.selection_card.setVisible(self._selection_user_defined)

    def _apply_mask(self, model: ActivityModel, mask: np.ndarray) -> None:
        model.active = mask.copy()
        self.refresh_plots(reset_region=True, fit_map=True)

    def _push_mask_edit(self, after: np.ndarray, text_key: str) -> None:
        if self.model is None or np.array_equal(self.model.active, after):
            return
        self.undo_stack.push(MaskEditCommand(self, self.model, self.model.active, after, self.tr(text_key)))

    def _push_multi_mask_edit(
        self,
        changes: list[tuple[ActivityModel, np.ndarray, np.ndarray]],
        text_key: str,
    ) -> None:
        real_changes = [
            (model, before, after)
            for model, before, after in changes
            if not np.array_equal(before, after)
        ]
        if real_changes:
            self.undo_stack.push(MultiMaskEditCommand(self, real_changes, self.tr(text_key)))

    def delete_selected(self) -> None:
        if not self.model:
            return
        start, end = self._current_region()
        changes: list[tuple[ActivityModel, np.ndarray, np.ndarray]] = []
        remaining = 0
        for document in self.tracks:
            before = document.model.active.copy()
            after = before & ~self._global_selection_mask(document, start, end)
            changes.append((document.model, before, after))
            remaining += int(after.sum())
        if remaining == 0:
            QtWidgets.QMessageBox.warning(self, self.tr("delete_title"), self.tr("delete_all"))
            return
        self._push_multi_mask_edit(changes, "edit_delete")
        self.statusBar().showMessage(self.tr("deleted"))

    def crop_selected(self) -> None:
        if not self.model:
            return
        start, end = self._current_region()
        changes: list[tuple[ActivityModel, np.ndarray, np.ndarray]] = []
        retained = 0
        for document in self.tracks:
            before = document.model.active.copy()
            after = self._global_selection_mask(document, start, end)
            changes.append((document.model, before, after))
            retained += int(after.sum())
        if retained == 0:
            QtWidgets.QMessageBox.warning(self, self.tr("crop_title"), self.tr("crop_empty"))
            return
        self._push_multi_mask_edit(changes, "edit_crop")
        self.statusBar().showMessage(self.tr("cropped"))

    def undo(self) -> None:
        if self.undo_stack.canUndo():
            self.undo_stack.undo()
            self.statusBar().showMessage(self.tr("undo_done"))

    def redo(self) -> None:
        if self.undo_stack.canRedo():
            self.undo_stack.redo()
            self.statusBar().showMessage(self.tr("redo_done"))

    def check_gps_dialog(self) -> None:
        model = self.model
        if model is None:
            return
        if not getattr(model, "has_timing", True):
            self.map_widget.clear_anomaly_points()
            QtWidgets.QMessageBox.information(
                self, self.tr("gps_title"), self.tr("gps_no_timing")
            )
            return
        sport = str(self.sport_mode.currentData() or "cycling")
        anomalies = detect_gps_anomalies(model, sport)
        if not anomalies:
            self.map_widget.clear_anomaly_points()
            QtWidgets.QMessageBox.information(self, self.tr("gps_title"), self.tr("gps_none"))
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("gps_title"))
        dialog.resize(1080, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        explanation = QtWidgets.QLabel(self.tr("gps_found", count=len(anomalies)))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        marker_points = [
            (model.points[item.focus_index].lat, model.points[item.focus_index].lon)
            for item in anomalies
        ]
        review_map = MapWidget(dialog)
        review_map.set_theme(self.theme)
        review_map.set_language(self.language)
        review_map.set_provider(self.map_widget._provider.key)
        review_map.set_download_visible(False)
        document = self.tracks[self.active_track_index]
        longitude, latitude = self._record_index(document).route_coordinates(model.active)
        review_map.set_tracks([{
            "lon": longitude,
            "lat": latitude,
            "colour": document.colour,
            "active": True,
            "name": model.path.name,
        }], fit=True)
        review_map.set_anomaly_points(marker_points)
        review_map.setMinimumWidth(430)

        table = QtWidgets.QTableWidget(len(anomalies), 5)
        table.setHorizontalHeaderLabels(
            ["Время", "Тип", "Точек", "Скачок", "Скорость"]
            if self.language == "ru" else
            ["Time", "Type", "Points", "Jump", "Speed"]
        )
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for row, anomaly in enumerate(anomalies):
            point = model.points[anomaly.focus_index]
            time_item = QtWidgets.QTableWidgetItem(fmt_time(point.t))
            time_item.setFlags(time_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            time_item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if anomaly.recommended else QtCore.Qt.CheckState.Unchecked
            )
            type_text = self.tr({
                "excursion": "gps_excursion",
                "jump": "gps_jump",
                "speed": "gps_speed",
            }.get(anomaly.kind, "gps_jump"))
            values = (
                time_item,
                QtWidgets.QTableWidgetItem(type_text),
                QtWidgets.QTableWidgetItem(str(len(anomaly.point_indices))),
                QtWidgets.QTableWidgetItem(
                    "—" if anomaly.distance_m <= 0.0 else
                    f"{anomaly.distance_m / 1000.0:.2f} km"
                    if anomaly.distance_m >= 1000.0 else f"{anomaly.distance_m:.0f} m"
                ),
                QtWidgets.QTableWidgetItem(f"{anomaly.speed_kmh:.0f} km/h"),
            )
            for column, item in enumerate(values):
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        content = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        content.addWidget(review_map)
        content.addWidget(table)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)
        content.setSizes([630, 420])
        layout.addWidget(content, 1)

        buttons = QtWidgets.QDialogButtonBox()
        select_all_button = buttons.addButton(
            self.tr("gps_select_all"), QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
        )
        select_none_button = buttons.addButton(
            self.tr("gps_select_none"), QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
        )
        show_button = buttons.addButton(
            self.tr("gps_show"), QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
        )
        show_button.setIcon(line_icon("zoom"))
        remove_button = buttons.addButton(
            self.tr("gps_remove"), QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        close_button = buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close_button.clicked.connect(dialog.reject)
        layout.addWidget(buttons)

        def focus_row(row: int, _column: int = 0, *_unused: object) -> None:
            if not 0 <= row < len(anomalies):
                return
            review_map.set_anomaly_points(marker_points, row)
            point = model.points[anomalies[row].focus_index]
            review_map.centre_on(point.lat, point.lon)

        def show_on_chart(row: int | None = None, *_unused: object) -> None:
            target = table.currentRow() if row is None or isinstance(row, bool) else int(row)
            if not 0 <= target < len(anomalies):
                return
            dialog.accept()
            self._focus_gps_anomaly_on_chart(model, anomalies[target])

        def remove_checked() -> None:
            indices: set[int] = set()
            for row, anomaly in enumerate(anomalies):
                item = table.item(row, 0)
                if item is not None and item.checkState() == QtCore.Qt.CheckState.Checked:
                    indices.update(anomaly.point_indices)
            indices = {index for index in indices if bool(model.active[index])}
            if not indices:
                QtWidgets.QMessageBox.information(
                    dialog, self.tr("gps_title"), self.tr("gps_nothing_selected")
                )
                return
            after = model.active.copy()
            after[list(indices)] = False
            if not after.any():
                QtWidgets.QMessageBox.warning(dialog, self.tr("gps_title"), self.tr("delete_all"))
                return
            self._push_mask_edit(after, "gps_title")
            self.statusBar().showMessage(self.tr("gps_removed", count=len(indices)))
            dialog.accept()

        def set_all_checked(checked: bool) -> None:
            state = QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)

        table.currentCellChanged.connect(focus_row)
        table.cellDoubleClicked.connect(show_on_chart)
        review_map.anomalyClicked.connect(show_on_chart)
        select_all_button.clicked.connect(lambda: set_all_checked(True))
        select_none_button.clicked.connect(lambda: set_all_checked(False))
        show_button.clicked.connect(show_on_chart)
        remove_button.clicked.connect(remove_checked)
        table.selectRow(0)
        focus_row(0)
        dialog.exec()
        self.map_widget.clear_anomaly_points()

    def _focus_gps_anomaly_on_chart(
        self, model: ActivityModel, anomaly: GPSAnomaly
    ) -> None:
        if model is not self.model or not 0 <= self.active_track_index < len(self.tracks):
            return
        document = self.tracks[self.active_track_index]
        indices = [
            index for index in anomaly.point_indices
            if 0 <= index < len(model.points)
        ] or [anomaly.focus_index]
        local_times = [float(model.points[index].t) for index in indices]
        focus_time = float(model.points[anomaly.focus_index].t) + document.timeline_offset
        start = min(local_times) + document.timeline_offset
        end = max(local_times) + document.timeline_offset
        margin = max(5.0, min(20.0, self._telemetry_duration * 0.005))
        start = max(document.timeline_start, start - margin)
        end = min(document.timeline_end, end + margin)
        if end - start < 2.0:
            start = max(document.timeline_start, focus_time - 5.0)
            end = min(document.timeline_end, focus_time + 5.0)

        self._selection_user_defined = True
        self._set_selection_region(start, end)
        context = max(60.0, min(300.0, (end - start) * 6.0))
        view_start = max(0.0, focus_time - context / 2.0)
        view_end = min(self._telemetry_duration, view_start + context)
        view_start = max(0.0, view_end - context)
        self._sync_x_range((view_start, view_end))
        if "speed" in self.graph_stack.visible_keys:
            self._activate_panel("speed")
            self.graph_stack.ensureWidgetVisible(self.graph_stack.panels["speed"])
        available = max(1, sum(self.content_splitter.sizes()))
        self.content_splitter.setSizes([max(180, int(available * 0.28)), max(360, int(available * 0.72))])
        point = model.points[anomaly.focus_index]
        self.map_widget.centre_on(point.lat, point.lon)
        self._position_selection_toolbar()
        self.statusBar().showMessage(self.tr("gps_chart_focus", time=fmt_time(focus_time)))

    def download_map_dialog(self) -> None:
        zoom = int(self.map_widget._zoom)
        ranges = [
            (zoom, zoom),
            (zoom, min(19, zoom + 1)),
            (max(2, zoom - 1), min(19, zoom + 2)),
        ]
        plans = [self.map_widget.route_cache_plan(low, high) for low, high in ranges]
        if (
            not any(plans)
            and not self.map_widget._track_routes
            and not self.map_widget._draft_route
            and not self.map_widget._waypoints
        ):
            QtWidgets.QMessageBox.information(
                self, self.tr("offline_title"), self.tr("offline_no_route")
            )
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("offline_title"))
        dialog.setMinimumWidth(520)
        layout = QtWidgets.QVBoxLayout(dialog)
        description = QtWidgets.QLabel(self.tr("offline_text"))
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QtWidgets.QFormLayout()
        detail_combo = QtWidgets.QComboBox()
        detail_combo.addItem(self.tr("offline_fast", count=len(plans[0])), 0)
        detail_combo.addItem(self.tr("offline_standard", count=len(plans[1])), 1)
        detail_combo.addItem(self.tr("offline_detailed", count=len(plans[2])), 2)
        form.addRow(self.tr("offline_level"), detail_combo)
        layout.addLayout(form)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        plan = plans[int(detail_combo.currentData())]
        if len(plan) > 2500:
            QtWidgets.QMessageBox.warning(
                self, self.tr("offline_title"), self.tr("offline_too_large", count=len(plan))
            )
            return
        if not plan:
            QtWidgets.QMessageBox.information(
                self, self.tr("offline_title"), self.tr("offline_cached")
            )
            return
        self.offline_map_action.setEnabled(False)
        self.map_widget.start_route_cache_download(plan)

    def _cache_download_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(self.tr("offline_progress", done=done, total=total))

    def _cache_download_finished(self, succeeded: int, failed: int) -> None:
        self.offline_map_action.setEnabled(True)
        self._update_cache_size_label()
        if failed:
            message = self.tr("offline_done_errors", count=succeeded, failed=failed)
            QtWidgets.QMessageBox.warning(self, self.tr("offline_title"), message)
        else:
            message = self.tr("offline_done", count=succeeded)
            QtWidgets.QMessageBox.information(self, self.tr("offline_title"), message)
        self.statusBar().showMessage(message)

    def convert_dialog(self) -> None:
        if not self.model or not self.model.active.any():
            return
        source_suffix = self.model.path.suffix.lower()
        target_suffix = ".tcx" if source_suffix == ".gpx" else ".gpx"
        default = self.model.path.with_name(self.model.path.stem + "_converted" + target_suffix)
        destination, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("convert_title"),
            str(default),
            self.tr("convert_filter"),
        )
        if not destination:
            return
        path = Path(destination)
        if not path.suffix:
            path = path.with_suffix(".tcx" if selected_filter.startswith("TCX") else ".gpx")
        if path.suffix.lower() == source_suffix:
            QtWidgets.QMessageBox.warning(self, self.tr("convert_title"), self.tr("convert_same"))
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            self.model.export_as(path)
            target_format = path.suffix[1:].upper()
            QtWidgets.QMessageBox.information(
                self, self.tr("saved"), self.tr("convert_ok", format=target_format)
            )
            self.statusBar().showMessage(self.tr("saved_status", path=path))
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, self.tr("save_error"), str(error))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def save_dialog(self) -> None:
        if not self.model:
            return
        if len(self.tracks) == 1:
            self._save_active_dialog()
            return

        chooser = QtWidgets.QMessageBox(self)
        chooser.setIcon(QtWidgets.QMessageBox.Icon.Question)
        chooser.setWindowTitle(self.tr("save_scope_title"))
        chooser.setText(self.tr("save_scope_text"))
        chooser.setInformativeText(self.tr("save_scope_info"))
        active_button = chooser.addButton(
            self.tr("save_active", name=self.model.path.name),
            QtWidgets.QMessageBox.ButtonRole.ActionRole,
        )
        combined_button = chooser.addButton(
            self.tr("save_combined"), QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        separate_button = chooser.addButton(
            self.tr("save_separate"), QtWidgets.QMessageBox.ButtonRole.ActionRole
        )
        chooser.addButton(
            self.tr("save_cancel"), QtWidgets.QMessageBox.ButtonRole.RejectRole
        )
        chooser.exec()
        clicked = chooser.clickedButton()
        if clicked is active_button:
            self._save_active_dialog()
        elif clicked is combined_button:
            self._save_combined_dialog()
        elif clicked is separate_button:
            self._save_separate_dialog()

    def _save_active_dialog(self) -> None:
        if not self.model:
            return
        if not self.model.active.any():
            QtWidgets.QMessageBox.warning(
                self, self.tr("save_scope_title"), self.tr("save_none")
            )
            return
        extension = self.model.path.suffix.lower()
        default = self.model.path.with_name(self.model.path.stem + "_edited" + extension)
        destination, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("save_title"),
            str(default),
            self.tr("save_filter", ext=extension[1:].upper()),
        )
        if not destination:
            return
        if not Path(destination).suffix:
            destination += extension
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            ok, message = self.model.export(destination)
            if ok:
                QtWidgets.QMessageBox.information(
                    self,
                    self.tr("saved"),
                    self.tr("saved_ok", format=extension[1:].upper()),
                )
                self.statusBar().showMessage(self.tr("saved_status", path=destination))
            else:
                QtWidgets.QMessageBox.warning(self, self.tr("validation"), message)
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, self.tr("save_error"), str(error))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _save_combined_dialog(self) -> None:
        available = [
            self.tracks[index]
            for index in (self._timeline_order or list(range(len(self.tracks))))
            if self.tracks[index].model.active.any()
        ]
        if not available:
            QtWidgets.QMessageBox.warning(
                self, self.tr("save_scope_title"), self.tr("save_none")
            )
            return
        default_parent = self.model.path.parent if self.model else Path.cwd()
        destination, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("save_combined_title"),
            str(default_parent / "combined_route.gpx"),
            "GPX (*.gpx)",
        )
        if not destination:
            return
        if Path(destination).suffix.lower() != ".gpx":
            destination += ".gpx"
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            export_combined_gpx(
                [(document.model, document.timeline_offset) for document in available],
                destination,
            )
            QtWidgets.QMessageBox.information(
                self, self.tr("saved"), self.tr("save_combined_ok")
            )
            self.statusBar().showMessage(self.tr("saved_status", path=destination))
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, self.tr("save_error"), str(error))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    @staticmethod
    def _unused_destination(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _save_separate_dialog(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("save_separate_title"),
            str(self.model.path.parent if self.model else Path.cwd()),
        )
        if not folder:
            return
        saved_count = 0
        errors: list[str] = []
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            for document in self.tracks:
                if not document.model.active.any():
                    continue
                extension = document.model.path.suffix.lower()
                target = self._unused_destination(
                    Path(folder) / f"{document.model.path.stem}_edited{extension}"
                )
                try:
                    ok, message = document.model.export(target)
                    if ok:
                        saved_count += 1
                    else:
                        errors.append(f"{document.model.path.name}: {message}")
                except Exception as error:
                    errors.append(f"{document.model.path.name}: {error}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if saved_count:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("saved"),
                self.tr("save_separate_ok", count=saved_count),
            )
            self.statusBar().showMessage(
                self.tr("save_separate_status", count=saved_count, path=folder)
            )
        if errors:
            QtWidgets.QMessageBox.warning(
                self, self.tr("validation"), "\n".join(errors)
            )

    def show_about(self) -> None:
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle(self.tr("about_title"))
        dialog.setText(f"<b>{APP_NAME} v{__version__}</b>")
        dialog.setInformativeText(
            f"{self.tr('about')}\n\n{self.tr('about_easter_egg')}\n\n"
            "generated by VJ Ostrov"
        )
        icon_path = resource_path("assets/app_icon.png")
        if icon_path.is_file():
            dialog.setIconPixmap(QtGui.QPixmap(str(icon_path)).scaled(
                64, 64,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            ))
        dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        dialog.exec()

    def _confirm_application_exit(self) -> bool:
        return QtWidgets.QMessageBox.question(
            self,
            self.tr("exit_confirm_title"),
            self.tr("exit_confirm_text"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        ) == QtWidgets.QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._route_panel is not None:
            self._route_panel.close_mode()
            event.ignore()
            return
        if event.spontaneous():
            if not self._confirm_application_exit():
                event.ignore()
                return
        if (
            hasattr(self, "local_stop_on_exit_check")
            and self.local_stop_on_exit_check.isChecked()
        ):
            self.local_graphhopper.shutdown()
        super().closeEvent(event)


def run() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("VJ Ostrov")
    icon_path = resource_path("assets/app_icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))
    app.setStyle("Fusion")
    pg.setConfigOptions(antialias=True)
    window = MainWindow()
    window.show()
    return app.exec()
