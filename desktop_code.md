# RG_Tag_Mapper.py — fixed context menus, anchor priority, Z in meters on add, multi_id only with extras
import sys, math, json, base64, os, copy, posixpath, zlib
import paramiko
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsLineItem, QMenu, QTreeWidget,
    QTreeWidgetItem, QDockWidget, QFileDialog, QToolBar, QMessageBox, QDialog,
    QFormLayout, QDialogButtonBox, QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox,
    QLabel, QInputDialog, QCheckBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGroupBox, QStyle, QTextBrowser, QHeaderView, QAbstractItemView, QProgressDialog
)
from PySide6.QtGui import (
    QAction, QPainter, QPen, QBrush, QColor, QPixmap, QPainterPath, QFont,
    QPdfWriter, QPageSize, QCursor, QKeySequence, QIcon, QPalette
)
from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, QBuffer, QByteArray, QTimer, QPoint, QSize, QSettings
from datetime import datetime
from mutagen.mp3 import MP3


def find_default_ssh_key(base_dir: str) -> str | None:
    try:
        entries = os.listdir(base_dir)
    except OSError:
        return None

    preferred_names = {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_ecdsa_sk",
        "id_ed25519_sk",
    }
    for name in preferred_names:
        path = os.path.join(base_dir, name)
        if os.path.isfile(path):
            return path

    allowed_suffixes = (".pem", ".key", ".rsa", ".ppk")
    for entry in sorted(entries):
        if entry.lower().endswith(allowed_suffixes):
            path = os.path.join(base_dir, entry)
            if os.path.isfile(path):
                return path

    return None

def fix_negative_zero(val):
    return 0.0 if abs(val) < 1e-9 else val


SETTINGS_ORG = "RG"
SETTINGS_APP = "RG_Tag_Mapper"
SETTINGS_LAST_DIR = "paths/last_dir"


def app_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def get_last_used_directory(default: str | None = None) -> str:
    settings = app_settings()
    stored = settings.value(SETTINGS_LAST_DIR, "", type=str)
    if isinstance(stored, str) and stored and os.path.isdir(stored):
        return stored
    if default and os.path.isdir(default):
        return default
    return os.getcwd()


def remember_last_used_path(path: str | None):
    if not path:
        return
    normalized = os.path.dirname(path) if os.path.isfile(path) else path
    if normalized and os.path.isdir(normalized):
        app_settings().setValue(SETTINGS_LAST_DIR, os.path.abspath(normalized))


def choose_open_file(parent, title: str, directory: str = "", filter_text: str = ""):
    start_dir = directory if directory else get_last_used_directory()
    file_path, selected_filter = QFileDialog.getOpenFileName(parent, title, start_dir, filter_text)
    if file_path:
        remember_last_used_path(file_path)
    return file_path, selected_filter


def choose_save_file(parent, title: str, directory: str = "", filter_text: str = ""):
    start_dir = directory if directory else get_last_used_directory()
    file_path, selected_filter = QFileDialog.getSaveFileName(parent, title, start_dir, filter_text)
    if file_path:
        remember_last_used_path(file_path)
    return file_path, selected_filter


def choose_directory(parent, title: str, directory: str = ""):
    start_dir = directory if directory else get_last_used_directory()
    folder = QFileDialog.getExistingDirectory(parent, title, start_dir)
    if folder:
        remember_last_used_path(folder)
    return folder

# ---------------------------------------------------------------------------
# Audio helpers and widgets
# ---------------------------------------------------------------------------
def extract_track_id(filename: str) -> int:
    name = os.path.splitext(os.path.basename(filename))[0]
    digits = ''.join(ch for ch in name if ch.isdigit())
    return int(digits) if digits else 0


def parse_additional_ids(text: str):
    ids = []
    for token in text.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids


def normalize_int_list(values) -> list[int]:
    if values is None:
        return []
    if isinstance(values, str):
        return parse_additional_ids(values)

    result: list[int] = []
    if isinstance(values, (list, tuple, set)):
        for value in values:
            try:
                result.append(int(value))
            except (TypeError, ValueError):
                continue
    return result


def load_audio_file_info(path: str):
    try:
        audio = MP3(path)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    duration_ms = int(round(audio.info.length * 1000)) if audio.info.length else 0
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        size_bytes = 0
    with open(path, 'rb') as fh:
        encoded = base64.b64encode(fh.read()).decode('ascii')
    return {
        'filename': os.path.basename(path),
        'data': encoded,
        'duration_ms': duration_ms,
        'size': size_bytes
    }


def format_audio_menu_line(info) -> str | None:
    if not isinstance(info, dict):
        return None
    filename = info.get('filename') or "(без названия)"
    audio_line = f"Аудиотрек: {filename}"
    duration_ms = int(info.get('duration_ms') or 0)
    if duration_ms > 0:
        total_seconds = max(duration_ms // 1000, 0)
        minutes, seconds = divmod(total_seconds, 60)
        audio_line += f" ({minutes:02d}:{seconds:02d})"
    return audio_line


class AudioTrackWidget(QWidget):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.main_file_info = None
        self.secondary_file_info = None
        self.display_name = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Аудио трек")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        main_row = QWidget()
        main_row_layout = QHBoxLayout(main_row)
        main_row_layout.setContentsMargins(0, 0, 0, 0)
        main_row_layout.addWidget(QLabel("Файл:"))
        self.main_file_label = QLabel("Не выбран")
        main_row_layout.addWidget(self.main_file_label)
        main_row_layout.addStretch(1)
        self.select_button = QPushButton("Выбрать MP3…")
        self.select_button.clicked.connect(self._select_main_file)
        main_row_layout.addWidget(self.select_button)
        self.clear_main_button = QPushButton("Очистить")
        self.clear_main_button.clicked.connect(self._clear_main_file)
        main_row_layout.addWidget(self.clear_main_button)
        layout.addWidget(main_row)

        self.settings_container = QGroupBox()
        self.settings_container.setTitle("")
        self.settings_layout = QFormLayout(self.settings_container)
        self.settings_layout.setContentsMargins(0, 0, 0, 0)
        self.track_id_label = QLabel("-")
        self.settings_layout.addRow("ID трека:", self.track_id_label)

        sec_widget = QWidget()
        sec_layout = QHBoxLayout(sec_widget)
        sec_layout.setContentsMargins(0, 0, 0, 0)
        self.secondary_label = QLabel("Не выбран")
        sec_layout.addWidget(self.secondary_label)
        sec_layout.addStretch(1)
        self.secondary_button = QPushButton("Добавить MP3…")
        self.secondary_button.clicked.connect(self._select_secondary_file)
        sec_layout.addWidget(self.secondary_button)
        self.clear_secondary_button = QPushButton("Очистить")
        self.clear_secondary_button.clicked.connect(self._clear_secondary_file)
        sec_layout.addWidget(self.clear_secondary_button)
        self.settings_layout.addRow("Доп. аудиотрек:", sec_widget)

        self.extra_ids_edit = QLineEdit()
        self.extra_ids_edit.setPlaceholderText("Например: 101, 131")
        self.settings_layout.addRow("Дополнительные ID:", self.extra_ids_edit)

        self.interruptible_box = QCheckBox("Прерываемый")
        self.interruptible_box.setChecked(True)
        self.reset_box = QCheckBox("Сброс")
        self.play_once_box = QCheckBox("Играть единожды")
        flags_widget = QWidget()
        flags_layout = QHBoxLayout(flags_widget)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.addWidget(self.interruptible_box)
        flags_layout.addWidget(self.reset_box)
        flags_layout.addWidget(self.play_once_box)
        flags_layout.addStretch(1)
        self.settings_layout.addRow(flags_widget)

        layout.addWidget(self.settings_container)

        self._update_state()
        if data:
            self.set_data(data)

    def set_data(self, data):
        if not data:
            self._clear_main_file()
            return
        self.main_file_info = {
            'filename': data.get('filename'),
            'data': data.get('data'),
            'duration_ms': data.get('duration_ms', 0),
            'size': data.get('size', 0)
        }
        self.display_name = data.get('display_name', "") if isinstance(data, dict) else ""
        self.secondary_file_info = None
        if data.get('secondary'):
            sec = data['secondary']
            self.secondary_file_info = {
                'filename': sec.get('filename'),
                'data': sec.get('data'),
                'duration_ms': sec.get('duration_ms', 0),
                'size': sec.get('size', 0)
            }
        self.extra_ids_edit.setText(', '.join(str(x) for x in data.get('extra_ids', [])))
        self.interruptible_box.setChecked(data.get('interruptible', True))
        self.reset_box.setChecked(data.get('reset', False))
        self.play_once_box.setChecked(data.get('play_once', False))
        self._update_state()

    def get_data(self):
        if not self.main_file_info:
            return None
        result = {
            'filename': self.main_file_info['filename'],
            'data': self.main_file_info['data'],
            'duration_ms': self.main_file_info.get('duration_ms', 0),
            'size': self.main_file_info.get('size', 0),
            'extra_ids': parse_additional_ids(self.extra_ids_edit.text()),
            'interruptible': self.interruptible_box.isChecked(),
            'reset': self.reset_box.isChecked(),
            'play_once': self.play_once_box.isChecked()
        }
        name_text = (self.display_name or "").strip()
        if name_text:
            result['display_name'] = name_text
        if self.secondary_file_info:
            result['secondary'] = {
                'filename': self.secondary_file_info['filename'],
                'data': self.secondary_file_info['data'],
                'duration_ms': self.secondary_file_info.get('duration_ms', 0),
                'size': self.secondary_file_info.get('size', 0)
            }
        return result

    def _select_main_file(self):
        path, _ = choose_open_file(self, "Выбрать аудио", get_last_used_directory(), "MP3 файлы (*.mp3)")
        if not path:
            return
        try:
            info = load_audio_file_info(path)
        except ValueError as err:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить аудио:\n{err}")
            return
        self.main_file_info = info
        self.display_name = ""
        if not self.interruptible_box.isChecked():
            self.interruptible_box.setChecked(True)
        self._update_state()

    def _select_secondary_file(self):
        path, _ = choose_open_file(self, "Выбрать дополнительный аудио", get_last_used_directory(), "MP3 файлы (*.mp3)")
        if not path:
            return
        try:
            info = load_audio_file_info(path)
        except ValueError as err:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить аудио:\n{err}")
            return
        self.secondary_file_info = info
        self._update_state()

    def _clear_main_file(self):
        self.main_file_info = None
        self.secondary_file_info = None
        self.display_name = ""
        self.extra_ids_edit.clear()
        self.interruptible_box.setChecked(True)
        self.reset_box.setChecked(False)
        self.play_once_box.setChecked(False)
        self._update_state()

    def _clear_secondary_file(self):
        self.secondary_file_info = None
        self._update_state()

    def _update_state(self):
        has_main = self.main_file_info is not None
        self.clear_main_button.setEnabled(has_main)
        self.settings_container.setVisible(has_main)
        self.secondary_button.setEnabled(has_main)
        self.clear_secondary_button.setEnabled(has_main and self.secondary_file_info is not None)
        if has_main:
            filename = self.main_file_info.get('filename', 'Не выбран')
            self.main_file_label.setText(filename)
            self.track_id_label.setText(filename)
        else:
            self.main_file_label.setText("Не выбран")
            self.track_id_label.setText("-")
        if self.secondary_file_info:
            self.secondary_label.setText(self.secondary_file_info.get('filename', ''))
        else:
            self.secondary_label.setText("Не выбран")

# ---------------------------------------------------------------------------
# Track list dock
# ---------------------------------------------------------------------------
class TracksListWidget(QWidget):
    HEADER_LABELS = [
        "Зал / Трек",
        "Аудиофайл",
        "Играть единожды",
        "Сброс",
        "Прерываемый",
        "Номер зала",
        "Доп. ID",
        "Имя",
    ]

    def __init__(self, mainwindow):
        super().__init__(mainwindow)
        self.mainwindow = mainwindow
        self._updating = False
        self._pending_snapshot = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(len(self.HEADER_LABELS))
        self.tree.setHeaderLabels(self.HEADER_LABELS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setStyleSheet(
            """
            QTreeWidget { background-color: transparent; }
            QTreeWidget QLineEdit {
                background-color: #ffffff;
                color: #000000;
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            """
        )

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(24)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Interactive)

        self._adjust_audio_column_width()
        self._adjust_name_column_width()

        layout.addWidget(self.tree)

    def refresh(self):
        if not hasattr(self.mainwindow, "halls"):
            return
        self._updating = True
        try:
            self.tree.clear()
            halls = sorted(
                self.mainwindow.halls,
                key=lambda h: self._normalize_sort_key(getattr(h, "number", 0))
            )
            for hall in halls:
                hall_title = f"Зал {hall.number}"
                if hall.name:
                    hall_title += f" — {hall.name}"
                hall_item = QTreeWidgetItem([hall_title])
                hall_item.setData(0, Qt.UserRole, {"type": "hall", "hall": hall.number})
                hall_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tree.addTopLevelItem(hall_item)
                hall_item.setFirstColumnSpanned(True)
                hall_item.setExpanded(True)

                if hall.audio_settings:
                    self._add_track_item(hall_item, hall, hall.audio_settings, True, None)

                for track_id, info in self._sorted_track_items(hall.zone_audio_tracks):
                    self._add_track_item(hall_item, hall, info, False, track_id)

            proximity_tracks = [pz for pz in getattr(self.mainwindow, "proximity_zones", []) if isinstance(getattr(pz, "audio_info", None), dict)]
            if proximity_tracks:
                proximity_root = QTreeWidgetItem(["Зоны по приближению"])
                proximity_root.setData(0, Qt.UserRole, {"type": "proximity_root"})
                proximity_root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tree.addTopLevelItem(proximity_root)
                proximity_root.setFirstColumnSpanned(True)
                proximity_root.setExpanded(True)

                proximity_tracks.sort(key=lambda z: self._normalize_sort_key(getattr(z, "zone_num", 0)))
                for pz in proximity_tracks:
                    self._add_proximity_track_item(proximity_root, pz)
        finally:
            self._updating = False
        self._adjust_name_column_width()

    @staticmethod
    def _normalize_sort_key(value):
        try:
            return 0, int(value)
        except (TypeError, ValueError):
            return 1, str(value)

    def _sorted_track_items(self, track_map):
        if not track_map:
            return []
        try:
            items = list(track_map.items())
        except AttributeError:
            return []
        items.sort(key=lambda item: self._normalize_sort_key(item[0]))
        return items

    def _add_proximity_track_item(self, parent_item, proximity_zone):
        info = getattr(proximity_zone, "audio_info", None)
        if not isinstance(info, dict):
            return
        item = QTreeWidgetItem(parent_item)
        item.setText(0, f"Зона по приближению {proximity_zone.zone_num}")
        item.setText(1, str(info.get('filename', '') or ''))
        item.setText(2, "")
        item.setText(3, "")
        item.setText(4, "")
        hall_numbers = [h for h in (proximity_zone.halls or []) if isinstance(h, int)]
        hall_text = ", ".join(str(x) for x in sorted(set(hall_numbers)))
        if not hall_text and proximity_zone.anchor and isinstance(proximity_zone.anchor.main_hall_number, int):
            hall_text = str(proximity_zone.anchor.main_hall_number)
        item.setText(5, hall_text)
        extras = info.get('extra_ids') if isinstance(info.get('extra_ids'), list) else []
        item.setText(6, ", ".join(str(x) for x in extras))
        item.setText(7, str(info.get('display_name', '') or ''))

        item.setCheckState(2, Qt.Checked if info.get('play_once') else Qt.Unchecked)
        item.setCheckState(3, Qt.Checked if info.get('reset') else Qt.Unchecked)
        item.setCheckState(4, Qt.Checked if info.get('interruptible', True) else Qt.Unchecked)

        item.setData(0, Qt.UserRole, {"type": "proximity_track", "zone_num": proximity_zone.zone_num, "anchor_id": proximity_zone.anchor.number if proximity_zone.anchor else None})
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsUserCheckable)

    def _add_track_item(self, parent_item, hall, info, is_hall_track, track_id):
        if not isinstance(info, dict):
            return
        item = QTreeWidgetItem(parent_item)
        title = f"Зал {hall.number}: основной трек" if is_hall_track else f"Зона {track_id}"
        item.setText(0, title)
        item.setText(1, str(info.get('filename', '') or ''))
        item.setText(2, "")
        item.setText(3, "")
        item.setText(4, "")
        item.setText(5, str(hall.number))
        item.setText(6, "")
        item.setText(7, str(info.get('display_name', '') or ''))

        extras = info.get('extra_ids') if isinstance(info.get('extra_ids'), list) else []
        extras_text = ", ".join(str(x) for x in extras)
        item.setText(6, extras_text)

        item.setCheckState(2, Qt.Checked if info.get('play_once') else Qt.Unchecked)
        item.setCheckState(3, Qt.Checked if info.get('reset') else Qt.Unchecked)
        item.setCheckState(4, Qt.Checked if info.get('interruptible', True) else Qt.Unchecked)

        payload = {
            "type": "track",
            "hall": hall.number,
            "is_hall_track": is_hall_track
        }
        if not is_hall_track:
            payload["track_id"] = track_id
        item.setData(0, Qt.UserRole, payload)
        item.setData(5, Qt.UserRole, hall.number)

        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsUserCheckable
        item.setFlags(flags)

    def _resolve_track(self, payload):
        if payload.get("type") == "proximity_track":
            zone_num = payload.get("zone_num")
            anchor_id = payload.get("anchor_id")
            for zone in getattr(self.mainwindow, "proximity_zones", []):
                if getattr(zone, "zone_num", None) != zone_num:
                    continue
                zone_anchor = getattr(zone, "anchor", None)
                zone_anchor_id = zone_anchor.number if zone_anchor else None
                if zone_anchor_id == anchor_id:
                    return zone, zone.audio_info, None
            return None, None, None

        hall_number = payload.get("hall")
        hall = next((h for h in self.mainwindow.halls if h.number == hall_number), None)
        if hall is None:
            return None, None, None
        if payload.get("is_hall_track"):
            return hall, hall.audio_settings, None
        track_id = payload.get("track_id")
        return hall, hall.zone_audio_tracks.get(track_id), track_id

    def _ensure_snapshot(self):
        if self._pending_snapshot is None:
            self._pending_snapshot = self.mainwindow.capture_state()

    def _commit_snapshot(self):
        if self._pending_snapshot is None:
            return
        self.mainwindow.push_undo_state(self._pending_snapshot)
        self._pending_snapshot = None

    def _on_item_changed(self, item, column):
        if self._updating:
            return
        payload = item.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            return
        if payload.get("type") not in ("track", "proximity_track"):
            return

        if column == 1:
            changed = self._handle_filename_change(payload, item.text(1))
        elif column == 2:
            changed = self._handle_flag_change(payload, 'play_once', item.checkState(2), False)
        elif column == 3:
            changed = self._handle_flag_change(payload, 'reset', item.checkState(3), False)
        elif column == 4:
            changed = self._handle_flag_change(payload, 'interruptible', item.checkState(4), True)
        elif column == 5:
            changed = self._handle_hall_number_change(payload, item.text(5))
        elif column == 6:
            changed = self._handle_extra_ids_change(payload, item.text(6))
        elif column == 7:
            changed = self._handle_display_name_change(payload, item.text(7))
        else:
            changed = False

        self.refresh()
        if changed:
            self._commit_snapshot()
        else:
            self._pending_snapshot = None

    def _adjust_audio_column_width(self):
        header = self.tree.header()
        metrics = header.fontMetrics()
        label = self.HEADER_LABELS[1]
        width = metrics.horizontalAdvance(label) + 20
        header.resizeSection(1, width)

    def _adjust_name_column_width(self):
        header = self.tree.header()
        metrics = header.fontMetrics()
        label_width = metrics.horizontalAdvance(self.HEADER_LABELS[-1]) + 20

        max_text_width = 0

        def _iterate(item):
            nonlocal max_text_width
            max_text_width = max(max_text_width, metrics.horizontalAdvance(item.text(7)))
            for idx in range(item.childCount()):
                _iterate(item.child(idx))

        for index in range(self.tree.topLevelItemCount()):
            _iterate(self.tree.topLevelItem(index))

        base_width = max(label_width, int(metrics.averageCharWidth() * 18))
        if max_text_width:
            base_width = max(base_width, max_text_width + 20)
        header.resizeSection(7, base_width)

    def _handle_filename_change(self, payload, new_value):
        hall, info, _ = self._resolve_track(payload)
        if info is None:
            return False
        new_name = (new_value or "").strip()
        current = info.get('filename', '') or ''
        if not new_name:
            QMessageBox.warning(self, "Ошибка", "Название аудиофайла не может быть пустым.")
            return False
        if new_name == current:
            return False
        self._ensure_snapshot()
        info['filename'] = new_name
        return True

    def _handle_display_name_change(self, payload, new_value):
        hall, info, _ = self._resolve_track(payload)
        if info is None:
            return False
        new_name = (new_value or "").strip()
        current = info.get('display_name', '') or ''
        if new_name == current:
            return False
        self._ensure_snapshot()
        if new_name:
            info['display_name'] = new_name
        elif 'display_name' in info:
            info.pop('display_name', None)
        return True

    def _handle_flag_change(self, payload, key, state, default):
        hall, info, _ = self._resolve_track(payload)
        if info is None:
            return False
        new_value = state == Qt.Checked
        current_value = info.get(key, default)
        if bool(current_value) == new_value and (key in info or new_value == default):
            return False
        self._ensure_snapshot()
        info[key] = new_value
        return True

    def _handle_hall_number_change(self, payload, value):
        if payload.get("type") == "proximity_track":
            QMessageBox.warning(self, "Ошибка", "Для треков зон по приближению изменение номера зала в этом списке недоступно.")
            return False
        hall, info, track_id = self._resolve_track(payload)
        if hall is None or info is None:
            return False
        try:
            new_hall_number = int(str(value).strip())
        except (TypeError, ValueError):
            QMessageBox.warning(self, "Ошибка", "Номер зала должен быть числом.")
            return False
        if new_hall_number == hall.number:
            return False
        target = next((h for h in self.mainwindow.halls if h.number == new_hall_number), None)
        if target is None:
            QMessageBox.warning(self, "Ошибка", f"Зал с номером {new_hall_number} не найден.")
            return False
        self._ensure_snapshot()
        if payload.get('is_hall_track'):
            hall.audio_settings = None
            target.audio_settings = info
        else:
            hall.zone_audio_tracks.pop(track_id, None)
            target.zone_audio_tracks[track_id] = info
        return True

    def _handle_extra_ids_change(self, payload, text):
        hall, info, _ = self._resolve_track(payload)
        if info is None:
            return False
        parsed = parse_additional_ids(text or "")
        current = info.get('extra_ids', [])
        if parsed == current:
            return False
        self._ensure_snapshot()
        info['extra_ids'] = parsed
        return True

# ---------------------------------------------------------------------------
# Universal parameter dialog
# ---------------------------------------------------------------------------
class ParamDialog(QDialog):
    def __init__(self, title, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.widgets = {}
        layout = QFormLayout(self)
        for f in fields:
            lbl, t, d = f["label"], f["type"], f.get("default")
            if t == "int":
                w = QSpinBox()
                w.setRange(f.get("min", 0), f.get("max", 10000))
                w.setValue(d or 0)
            elif t == "float":
                w = QDoubleSpinBox()
                w.setRange(f.get("min", 0.0), f.get("max", 10000.0))
                w.setDecimals(f.get("decimals", 1))
                w.setValue(d or 0.0)
            elif t == "string":
                w = QLineEdit()
                if d is not None:
                    w.setText(str(d))
            elif t == "combo":
                w = QComboBox()
                for o in f.get("options", []):
                    w.addItem(o)
                if d in f.get("options", []):
                    w.setCurrentIndex(f["options"].index(d))
            elif t == "bool":
                w = QCheckBox()
                w.setChecked(bool(d))
            else:
                w = QLineEdit()
            self.widgets[lbl] = w
            layout.addRow(QLabel(lbl), w)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def getValues(self):
        out = {}
        for lbl, w in self.widgets.items():
            if isinstance(w, (QSpinBox, QDoubleSpinBox)):
                out[lbl] = w.value()
            elif isinstance(w, QLineEdit):
                out[lbl] = w.text()
            elif isinstance(w, QComboBox):
                out[lbl] = w.currentText()
            elif isinstance(w, QCheckBox):
                out[lbl] = w.isChecked()
            else:
                out[lbl] = w.text()
        return out

# ---------------------------------------------------------------------------
# Dialog to lock objects
# ---------------------------------------------------------------------------
class LockDialog(QDialog):
    def __init__(self, lh, lz, la, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Закрепить объекты")
        layout = QFormLayout(self)
        self.cb_h = QCheckBox("Закрепить залы"); self.cb_h.setChecked(lh)
        self.cb_z = QCheckBox("Закрепить зоны"); self.cb_z.setChecked(lz)
        self.cb_a = QCheckBox("Закрепить якоря"); self.cb_a.setChecked(la)
        layout.addRow(self.cb_h); layout.addRow(self.cb_z); layout.addRow(self.cb_a)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self):
        return self.cb_h.isChecked(), self.cb_z.isChecked(), self.cb_a.isChecked()

# ---------------------------------------------------------------------------
# Initial parameter getters
# ---------------------------------------------------------------------------
def getHallParameters(default_num=1, default_name="", default_w=1.0, default_h=1.0, scene=None):
    fields = [
        {"label": "Номер зала", "type": "int", "default": default_num, "min": 0, "max": 10000},
        {"label": "Название зала", "type": "string", "default": default_name},
        {"label": "Ширина (м)", "type": "float", "default": default_w, "min": 0.1, "max": 1000.0, "decimals":1},
        {"label": "Высота (м)", "type": "float", "default": default_h, "min": 0.1, "max": 1000.0, "decimals":1}
    ]
    dlg = ParamDialog("Введите параметры зала", fields)
    if dlg.exec() == QDialog.Accepted:
        v = dlg.getValues()
        return v["Номер зала"], v["Название зала"], v["Ширина (м)"], v["Высота (м)"]
    return None

# Z ВВОДИМ В МЕТРАХ
def getAnchorParameters(default_num=1, default_z_m=0.0, default_extras="", default_bound=False):
    fields = [
        {"label": "Номер якоря", "type": "int", "default": default_num, "min": 0, "max": 10000},
        {"label": "Координата Z (м)", "type": "float", "default": default_z_m, "min": -100.0, "max": 100.0, "decimals": 1},
        {"label": "Дополнительные залы (через запятую)", "type": "string", "default": default_extras},
        {"label": "Переходный", "type": "bool", "default": default_bound}
    ]
    dlg = ParamDialog("Введите параметры якоря", fields)
    if dlg.exec() == QDialog.Accepted:
        v = dlg.getValues()
        extras = [int(tok) for tok in v["Дополнительные залы (через запятую)"].split(",") if tok.strip().isdigit()]
        return v["Номер якоря"], float(v["Координата Z (м)"]), extras, v["Переходный"]
    return None

def getZoneParameters(default_num=1, default_type="Входная зона", default_angle=0):
    dt = default_type.replace(" зона", "")
    fields = [
        {"label": "Номер зоны", "type": "int", "default": default_num, "min": 0, "max": 10000},
        {"label": "Тип зоны", "type": "combo", "default": dt, "options": ["Входная", "Выходная", "Переходная"]},
        {"label": "Угол поворота (°)", "type": "int", "default": default_angle, "min": -90, "max": 90}
    ]
    dlg = ParamDialog("Введите параметры зоны", fields)
    if dlg.exec() == QDialog.Accepted:
        v = dlg.getValues()
        zt = v["Тип зоны"]
        full = {"Входная":"Входная зона","Выходная":"Выходная зона","Переходная":"Переходная"}[zt]
        return v["Номер зоны"], full, v["Угол поворота (°)"]
    return None

# ---------------------------------------------------------------------------
# Edit dialogs with audio controls
# ---------------------------------------------------------------------------
class HallEditDialog(QDialog):
    def __init__(self, hall_item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать зал")
        layout = QVBoxLayout(self)

        form = QFormLayout()
        layout.addLayout(form)

        self.num_spin = QSpinBox()
        self.num_spin.setRange(0, 10000)
        self.num_spin.setValue(hall_item.number)
        form.addRow("Номер зала", self.num_spin)

        self.name_edit = QLineEdit()
        self.name_edit.setText(hall_item.name)
        form.addRow("Название зала", self.name_edit)

        ppcm = hall_item.scene().pixel_per_cm_x if hall_item.scene() else 1.0
        width_m = hall_item.rect().width()/(ppcm*100)
        height_m = hall_item.rect().height()/(ppcm*100)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setDecimals(1)
        self.width_spin.setRange(0.1, 1000.0)
        self.width_spin.setValue(width_m)
        form.addRow("Ширина (м)", self.width_spin)

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setDecimals(1)
        self.height_spin.setRange(0.1, 1000.0)
        self.height_spin.setValue(height_m)
        form.addRow("Высота (м)", self.height_spin)

        self.extra_tracks_edit = QLineEdit()
        self.extra_tracks_edit.setPlaceholderText("Например: 101, 102, 103")
        current_extra_tracks = getattr(hall_item, "extra_tracks", []) or []
        self.extra_tracks_edit.setText(", ".join(str(x) for x in current_extra_tracks if isinstance(x, int)))
        form.addRow("Треки с ручным вводом", self.extra_tracks_edit)

        self.audio_widget = AudioTrackWidget(self, hall_item.audio_settings)
        layout.addWidget(self.audio_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {
            'number': self.num_spin.value(),
            'name': self.name_edit.text(),
            'width': self.width_spin.value(),
            'height': self.height_spin.value(),
            'extra_tracks': parse_additional_ids(self.extra_tracks_edit.text()),
            'audio': self.audio_widget.get_data()
        }


class ZoneEditDialog(QDialog):
    def __init__(self, zone_item, audio_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать зону")
        layout = QVBoxLayout(self)

        form = QFormLayout()
        layout.addLayout(form)

        self.num_spin = QSpinBox()
        self.num_spin.setRange(0, 10000)
        self.num_spin.setValue(zone_item.zone_num)
        form.addRow("Номер зоны", self.num_spin)

        self.type_combo = QComboBox()
        options = ["Входная", "Выходная", "Переходная"]
        for opt in options:
            self.type_combo.addItem(opt)
        current = zone_item.zone_type.replace(" зона", "")
        if current in options:
            self.type_combo.setCurrentIndex(options.index(current))
        form.addRow("Тип зоны", self.type_combo)

        data = zone_item.get_export_data() or {"x":0.0,"y":0.0,"w":0.0,"h":0.0,"angle":0}

        self.x_spin = QDoubleSpinBox()
        self.x_spin.setDecimals(1)
        self.x_spin.setRange(-1000.0, 1000.0)
        self.x_spin.setValue(data['x'])

        self.y_spin = QDoubleSpinBox()
        self.y_spin.setDecimals(1)
        self.y_spin.setRange(-1000.0, 1000.0)
        self.y_spin.setValue(data['y'])

        self.w_spin = QDoubleSpinBox()
        self.w_spin.setDecimals(1)
        self.w_spin.setRange(0.0, 1000.0)
        self.w_spin.setValue(data['w'])

        self.h_spin = QDoubleSpinBox()
        self.h_spin.setDecimals(1)
        self.h_spin.setRange(0.0, 1000.0)
        self.h_spin.setValue(data['h'])

        form.addRow("Координата X (м)", self.x_spin)
        form.addRow("Координата Y (м)", self.y_spin)
        form.addRow("Ширина (м)", self.w_spin)
        form.addRow("Высота (м)", self.h_spin)

        self.angle_spin = QSpinBox()
        self.angle_spin.setRange(-90, 90)
        self.angle_spin.setValue(int(data['angle']))
        form.addRow("Угол поворота (°)", self.angle_spin)

        self._stored_audio_data = copy.deepcopy(audio_data) if audio_data else None
        self.audio_widget = AudioTrackWidget(self, audio_data)
        layout.addWidget(self.audio_widget)

        self._audio_controls_enabled = False
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self._on_type_changed(self.type_combo.currentText())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        full_type = {"Входная": "Входная зона", "Выходная": "Выходная зона", "Переходная": "Переходная"}[self.type_combo.currentText()]
        audio_data = self.audio_widget.get_data() if self._audio_controls_enabled else self._stored_audio_data
        if audio_data:
            audio_data = copy.deepcopy(audio_data)
            self._stored_audio_data = copy.deepcopy(audio_data)
        else:
            self._stored_audio_data = None
        return {
            'zone_num': self.num_spin.value(),
            'zone_type': full_type,
            'x': self.x_spin.value(),
            'y': self.y_spin.value(),
            'w': self.w_spin.value(),
            'h': self.h_spin.value(),
            'angle': self.angle_spin.value(),
            'audio': audio_data
        }

    def _on_type_changed(self, text: str):
        is_entry_zone = text == "Входная"
        if is_entry_zone:
            if not self._audio_controls_enabled:
                if self._stored_audio_data:
                    self.audio_widget.set_data(copy.deepcopy(self._stored_audio_data))
                else:
                    self.audio_widget.set_data(None)
            self.audio_widget.setVisible(True)
            self.audio_widget.setEnabled(True)
            self._audio_controls_enabled = True
        else:
            if self._audio_controls_enabled:
                self._stored_audio_data = self.audio_widget.get_data()
            self.audio_widget.setVisible(False)
            self.audio_widget.setEnabled(False)
            self._audio_controls_enabled = False


class ProximityZoneDialog(QDialog):
    def __init__(self, anchor_id: int, zone_num: int = 1, dist_in: float = 1.0, dist_out: float = 0.0,
                 bound: bool = False, halls: str = "", blist: str = "", audio_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Зона по приближению")
        layout = QVBoxLayout(self)

        form = QFormLayout()
        layout.addLayout(form)

        anchor_label = QLabel(str(anchor_id))
        form.addRow("Якорь", anchor_label)

        self.num_spin = QSpinBox()
        self.num_spin.setRange(0, 10000)
        self.num_spin.setValue(zone_num)
        form.addRow("Номер зоны", self.num_spin)

        self.dist_in_spin = QDoubleSpinBox()
        self.dist_in_spin.setDecimals(1)
        self.dist_in_spin.setSingleStep(0.1)
        self.dist_in_spin.setRange(0.0, 1000.0)
        self.dist_in_spin.setValue(max(0.0, dist_in))
        form.addRow("Дистанция входа (м)", self.dist_in_spin)

        self.dist_out_spin = QDoubleSpinBox()
        self.dist_out_spin.setDecimals(1)
        self.dist_out_spin.setSingleStep(0.1)
        self.dist_out_spin.setRange(0.0, 1000.0)
        self.dist_out_spin.setValue(max(0.0, dist_out))
        form.addRow("Дистанция выхода (м)", self.dist_out_spin)

        self.bound_box = QCheckBox("Переходная зона")
        self.bound_box.setChecked(bool(bound))
        form.addRow(self.bound_box)

        self.halls_edit = QLineEdit(halls)
        self.halls_edit.setPlaceholderText("Например: 1, 2, 5")
        form.addRow("Залы", self.halls_edit)

        self.blist_edit = QLineEdit(blist)
        self.blist_edit.setPlaceholderText("Например: 1, 3, 10")
        form.addRow("Чёрный список", self.blist_edit)

        self.audio_widget = AudioTrackWidget(self, audio_data)
        layout.addWidget(self.audio_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _parse_numbers(self, text: str) -> list[int]:
        values: list[int] = []
        for token in text.split(','):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(int(token))
            except ValueError:
                continue
        return values

    def values(self) -> dict:
        return {
            'zone_num': self.num_spin.value(),
            'dist_in': round(self.dist_in_spin.value(), 1),
            'dist_out': round(self.dist_out_spin.value(), 1),
            'bound': self.bound_box.isChecked(),
            'halls': self._parse_numbers(self.halls_edit.text()),
            'blist': self._parse_numbers(self.blist_edit.text()),
            'audio': copy.deepcopy(self.audio_widget.get_data())
        }

# ---------------------------------------------------------------------------
# HallItem
# ---------------------------------------------------------------------------
class HallItem(QGraphicsRectItem):
    def __init__(self, x, y, w_px, h_px, name="", number=0, scene=None):
        super().__init__(0, 0, w_px, h_px)
        self.setPos(x, y)
        self.name, self.number = name, number
        self.scene_ref = scene
        self.setPen(QPen(QColor(0,0,255),2)); self.setBrush(QColor(0,0,255,50))
        self.setFlags(QGraphicsItem.ItemIsMovable|QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(-w_px*h_px); self.tree_item = None
        self.audio_settings = None
        self.extra_tracks: list[int] = []
        self.zone_audio_tracks = {}
        self._undo_snapshot = None
        self._undo_initial_pos = None

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.save()
        font = QFont(); font.setBold(True); painter.setFont(font)
        fill = self.pen().color(); outline = QColor(180,180,180)
        rect = self.rect()
        pos = rect.bottomLeft() + QPointF(2,-2)
        path = QPainterPath(); path.addText(pos, font, str(self.number))
        painter.setPen(QPen(outline,2)); painter.drawPath(path); painter.fillPath(path, fill)
        painter.restore()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new = QPointF(value)
            sr = self.scene().sceneRect(); r = self.rect()
            new.setX(max(sr.left(), min(new.x(), sr.right()-r.width())))
            new.setY(max(sr.top(), min(new.y(), sr.bottom()-r.height())))
            step = self.scene().pixel_per_cm_x * self.scene().grid_step_cm
            if step>0:
                new.setX(round(new.x()/step)*step)
                new.setY(round(new.y()/step)*step)
            delta = new - self.pos()
            if not delta.isNull():
                scene = self.scene()
                if scene:
                    mw = getattr(scene, "mainwindow", None)
                    if mw:
                        for anchor in mw.anchors:
                            if anchor.main_hall_number == self.number or self.number in anchor.extra_halls:
                                anchor.moveBy(delta.x(), delta.y())
            return new
        return super().itemChange(change, value)

    # Unified menu
    def open_menu(self, global_pos: QPoint):
        if not self.scene(): return
        mw = self.scene().mainwindow
        ppcm = self.scene().pixel_per_cm_x
        menu = QMenu()
        hall_title = f"Зал {self.number}"
        if self.name:
            hall_title += f" — {self.name}"
        header = menu.addAction(hall_title); header.setEnabled(False)
        audio_info_text = self._get_audio_info_text()
        if audio_info_text:
            audio_line = menu.addAction(audio_info_text)
            audio_line.setEnabled(False)
        edit = menu.addAction("Редактировать зал")
        delete = menu.addAction("Удалить зал")
        act = menu.exec(global_pos)
        if act == edit:
            dlg = HallEditDialog(self, mw)
            if dlg.exec() == QDialog.Accepted:
                prev_state = mw.capture_state()
                values = dlg.values()
                new_num = values['number']
                new_name = values['name']
                new_w_m = values['width']
                new_h_m = values['height']
                self.extra_tracks = values.get('extra_tracks', [])
                self.audio_settings = values['audio']
                old = self.number
                for a in mw.anchors:
                    if a.main_hall_number == old:
                        a.main_hall_number = new_num
                    a.extra_halls = [new_num if x==old else x for x in a.extra_halls]
                self.number, self.name = new_num, new_name
                w_px = new_w_m * ppcm * 100
                h_px = new_h_m * ppcm * 100
                self.prepareGeometryChange()
                self.setRect(0, 0, w_px, h_px)
                self.setZValue(-w_px*h_px)
                mw.last_selected_items = []
                mw.populate_tree()
                mw.push_undo_state(prev_state)
        elif act == delete:
            anchors_rel = [a for a in mw.anchors if a.main_hall_number==self.number or self.number in a.extra_halls]
            zones_rel = [z for z in self.childItems() if isinstance(z, RectZoneItem)]
            if anchors_rel or zones_rel:
                cnt_a, cnt_z = len(anchors_rel), len(zones_rel)
                resp = QMessageBox.question(mw, "Подтвердить",
                                            f"В зале {self.number} {cnt_a} якорей и {cnt_z} зон.\nУдалить?",
                                            QMessageBox.Yes|QMessageBox.No)
                if resp != QMessageBox.Yes:
                    return
            prev_state = mw.capture_state()
            for z in zones_rel:
                z.scene().removeItem(z)
            for a in anchors_rel:
                if a.main_hall_number == self.number:
                    if a.extra_halls:
                        a.main_hall_number = a.extra_halls.pop(0)
                    else:
                        mw.anchors.remove(a); a.scene().removeItem(a)
                else:
                    a.extra_halls.remove(self.number)
            mw.halls.remove(self); self.scene().removeItem(self)
            mw.last_selected_items = []; mw.populate_tree()
            mw.push_undo_state(prev_state)

    def _get_audio_info_text(self) -> str | None:
        return format_audio_menu_line(self.audio_settings)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.scene():
            anchor = _top_anchor(self.scene(), event.scenePos())
            if anchor:
                event.ignore()
                return
            zone = _smallest_zone(self.scene(), event.scenePos())
            if zone:
                event.ignore()
                return
            mw = self.scene().mainwindow
            if mw and not getattr(mw, "_restoring_state", False):
                self._undo_initial_pos = QPointF(self.pos())
                self._undo_snapshot = mw.capture_state()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.scene():
            anchor = _top_anchor(self.scene(), event.scenePos())
            if anchor:
                anchor.open_menu(event.screenPos())
                event.accept()
                return
            zone = _smallest_zone(self.scene(), event.scenePos())
            if zone:
                zone.open_menu(event.screenPos())
                event.accept()
                return
        self.open_menu(event.screenPos())
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self.scene():
            if self._undo_snapshot is not None and self._undo_initial_pos is not None:
                if self.pos() != self._undo_initial_pos:
                    mw = self.scene().mainwindow
                    if mw:
                        mw.push_undo_state(self._undo_snapshot)
        self._undo_snapshot = None
        self._undo_initial_pos = None

    def contextMenuEvent(self, event):
        # ПКМ: приоритет — якорь, затем (внутренняя) зона, затем зал
        if self.scene():
            anchor = _top_anchor(self.scene(), event.scenePos())
            if anchor:
                anchor.open_menu(event.screenPos())
                event.accept()
                return
            zone = _smallest_zone(self.scene(), event.scenePos())
            if zone:
                zone.open_menu(event.screenPos())
                event.accept()
                return
        self.open_menu(event.screenPos())
        event.accept()

# ---------------------------------------------------------------------------
# AnchorItem
# ---------------------------------------------------------------------------
class AnchorItem(QGraphicsEllipseItem):
    def __init__(self, x, y, number=0, main_hall_number=None, scene=None):
        r = 3
        super().__init__(-r,-r,2*r,2*r)
        self.setPos(x,y); self.number = number; self.z = 0
        self.main_hall_number = main_hall_number; self.extra_halls = []
        self.bound = False
        self.bound_explicit = False
        self.setPen(QPen(QColor(255,0,0),2)); self.setBrush(QBrush(QColor(255,0,0)))
        self.setFlags(QGraphicsItem.ItemIsMovable|QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemSendsGeometryChanges)
        self.tree_item = None
        self.update_zvalue()
        self._undo_snapshot = None
        self._undo_initial_pos = None

    def update_zvalue(self):
        anchor_number = float(self.number) if isinstance(self.number, (int, float)) else 0.0
        self.setZValue(10000.0 + anchor_number * 0.001)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.save()
        font = QFont(); font.setBold(True); painter.setFont(font)
        fill = self.pen().color(); outline = QColor(180,180,180)
        br = self.boundingRect()
        pos = QPointF(br.center().x()-br.width()/2, br.top()-4)
        path = QPainterPath(); path.addText(pos, font, str(self.number))
        painter.setPen(QPen(outline,2)); painter.drawPath(path); painter.fillPath(path, fill)
        painter.restore()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new = QPointF(value)
            step = self.scene().pixel_per_cm_x * self.scene().grid_step_cm
            if step>0:
                new.setX(round(new.x()/step)*step)
                new.setY(round(new.y()/step)*step)
            return new
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.update_zvalue()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            mw = scene.mainwindow if scene else None
            if mw and mw.add_mode == "proximity_zone":
                params = mw.get_proximity_zone_parameters(self)
                mw.add_mode = None
                mw.statusBar().clearMessage()
                if not params:
                    event.accept()
                    return
                prev_state = mw.capture_state()
                values = params
                if not values['halls'] and self.main_hall_number is not None:
                    values['halls'] = [self.main_hall_number]
                zone = ProximityZoneItem(
                    self,
                    values['zone_num'],
                    values['dist_in'],
                    values['dist_out'],
                    values['bound'],
                    values['halls'],
                    values['blist'],
                    values.get('audio'),
                )
                mw.proximity_zones.append(zone)
                mw.populate_tree()
                mw.push_undo_state(prev_state)
                event.accept()
                return

            self.update_zvalue()
            if scene and not (event.modifiers() & Qt.ControlModifier):
                scene.clearSelection()
            self.setSelected(True)
            if scene and mw and not getattr(mw, "_restoring_state", False):
                self._undo_initial_pos = QPointF(self.scenePos())
                self._undo_snapshot = mw.capture_state()
        super().mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.update_zvalue()
        super().mouseMoveEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.update_zvalue()
        if event.button() == Qt.LeftButton and self.scene():
            if self._undo_snapshot is not None and self._undo_initial_pos is not None:
                if self.scenePos() != self._undo_initial_pos:
                    mw = self.scene().mainwindow
                    if mw:
                        mw.push_undo_state(self._undo_snapshot)
        self._undo_snapshot = None
        self._undo_initial_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # Всегда открываем меню якоря при двойном клике по якорю
        self.update_zvalue()
        self.open_menu(event.screenPos())
        event.accept()

    def contextMenuEvent(self, event):
        # ПКМ на якоре — его же меню, даже если он перекрыт другими
        self.update_zvalue()
        self.open_menu(event.screenPos())
        event.accept()

    def open_menu(self, global_pos: QPoint):
        if not self.scene(): return
        mw = self.scene().mainwindow
        hall = next((h for h in mw.halls if h.number==self.main_hall_number), None)
        if not hall: return
        ppcm = self.scene().pixel_per_cm_x
        local = hall.mapFromScene(self.scenePos())
        x_m = round(local.x()/(ppcm*100),1)
        y_m = round((hall.rect().height()-local.y())/(ppcm*100),1)
        z_m = round(self.z/100.0,1)
        ids = [str(self.main_hall_number)] + [str(x) for x in self.extra_halls]
        halls_str = ("зал "+ids[0] if len(ids)==1 else "залы "+",".join(ids))

        menu = QMenu()
        header = menu.addAction(f"Якорь {self.number} ({halls_str})"); header.setEnabled(False)
        edit = menu.addAction("Редактировать"); delete = menu.addAction("Удалить")
        act = menu.exec(global_pos)
        if act == edit:
            fields = [
                {"label": "Номер якоря", "type": "int", "default": self.number, "min": 0, "max": 10000},
                {"label":"Координата X (м)","type":"float","default":x_m,"min":-1000.0,"max":10000,"decimals":1},
                {"label":"Координата Y (м)","type":"float","default":y_m,"min":-1000.0,"max":10000,"decimals":1},
                {"label":"Координата Z (м)","type":"float","default":z_m,"min":-100,"max":100,"decimals":1},
                {"label":"Доп. залы","type":"string","default":",".join(str(x) for x in self.extra_halls)},
                {"label":"Переходный","type":"bool","default":self.bound}
            ]
            dlg = ParamDialog("Редактировать якорь", fields, mw)
            if dlg.exec() == QDialog.Accepted:
                prev_state = mw.capture_state()
                v = dlg.getValues()
                self.number = v["Номер якоря"]
                x2, y2, z2 = v["Координата X (м)"], v["Координата Y (м)"], v["Координата Z (м)"]
                self.bound = v["Переходный"]
                self.bound_explicit = self.bound
                self.extra_halls = [int(tok) for tok in v["Доп. залы"].split(",") if tok.strip().isdigit()]
                self.z = int(round(z2*100))
                px = x2 * ppcm * 100
                py = hall.rect().height() - y2 * ppcm * 100
                self.setPos(hall.mapToScene(QPointF(px, py)))
                self.update_zvalue()
                mw.last_selected_items = []; mw.populate_tree()
                mw.push_undo_state(prev_state)
        elif act == delete:
            confirm = QMessageBox.question(
                mw,
                "Подтвердить",
                f"Удалить якорь {self.number} ({halls_str})?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirm != QMessageBox.Yes:
                return
            prev_state = mw.capture_state()
            for zone in list(getattr(mw, 'proximity_zones', [])):
                if zone.anchor is self:
                    mw.proximity_zones.remove(zone)
                    zone.scene().removeItem(zone)
            mw.anchors.remove(self); self.scene().removeItem(self)
            mw.last_selected_items = []; mw.populate_tree()
            mw.push_undo_state(prev_state)

# ---------------------------------------------------------------------------
# ZoneItem
# ---------------------------------------------------------------------------
class RectZoneItem(QGraphicsRectItem):
    _ZONE_RGB = {
        "Входная зона": (0, 128, 0),
        "Входная": (0, 128, 0),
        "Выходная зона": (128, 0, 128),
        "Выходная": (128, 0, 128),
        "Переходная": (0, 102, 204),
        "Переходная зона": (0, 102, 204),
    }

    def __init__(self, bl, w, h, zone_num=0, zone_type="Входная зона", angle=0, parent_hall=None):
        super().__init__(0, -h, w, h, parent_hall)
        self.zone_num, self.zone_type, self.zone_angle = zone_num, zone_type, angle
        self.setTransformOriginPoint(0,0); self.setRotation(-angle); self.setPos(bl)
        self._apply_zone_palette()
        self.setFlags(QGraphicsItem.ItemIsMovable|QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemSendsGeometryChanges)
        self.tree_item = None
        self.update_zvalue()
        self._undo_snapshot = None
        self._undo_initial_pos = None

    def update_zvalue(self):
        hall = self.parentItem()
        hall_number = hall.number if isinstance(hall, HallItem) and hasattr(hall, 'number') else 0
        zone_number = self.zone_num if isinstance(self.zone_num, (int, float)) else 0
        self.setZValue(5000.0 + float(hall_number) * 0.1 + float(zone_number) * 0.001)

    def _apply_zone_palette(self):
        rgb = self._ZONE_RGB.get(self.zone_type)
        if not rgb:
            rgb = self._ZONE_RGB["Входная зона"]
        base_color = QColor(*rgb)
        self.setPen(QPen(base_color, 2))
        fill_color = QColor(base_color)
        fill_color.setAlpha(50)
        self.setBrush(QBrush(fill_color))

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.save()
        font = QFont(); font.setBold(True); painter.setFont(font)
        fill = self.pen().color(); outline = QColor(180,180,180)
        rect = self.rect()
        pos = rect.bottomLeft() + QPointF(2,-2)
        path = QPainterPath(); path.addText(pos, font, str(self.zone_num))
        painter.setPen(QPen(outline,2)); painter.drawPath(path); painter.fillPath(path, fill)
        painter.restore()

    def get_display_type(self):
        return {"Входная зона":"входная","Выходная зона":"выходная","Переходная":"переходная"}[self.zone_type]

    def get_export_data(self):
        scene = self.scene(); hall = self.parentItem()
        if not scene or not hall: return None
        ppcm = scene.pixel_per_cm_x
        pos = self.pos(); hh = hall.rect().height()
        return {
            "x": fix_negative_zero(round(pos.x()/(ppcm*100),1)),
            "y": fix_negative_zero(round((hh-pos.y())/(ppcm*100),1)),
            "w": fix_negative_zero(round(self.rect().width()/(ppcm*100),1)),
            "h": fix_negative_zero(round(self.rect().height()/(ppcm*100),1)),
            "angle": fix_negative_zero(round(self.zone_angle,1))
        }

    def open_menu(self, global_pos: QPoint):
        scene = self.scene(); 
        if not scene: return
        mw = scene.mainwindow
        data = self.get_export_data()
        if data is None: return
        menu = QMenu()
        hall = self.parentItem()
        hall_suffix = ""
        if isinstance(hall, HallItem):
            hall_suffix = f" — зал {hall.number}"
        header = menu.addAction(f"Зона {self.zone_num} ({self.get_display_type()}){hall_suffix}"); header.setEnabled(False)
        audio_info = None
        if isinstance(hall, HallItem):
            audio_info = hall.zone_audio_tracks.get(self.zone_num)
        if (
            not audio_info
            and self.zone_type in ("Переходная", "Переходная зона")
            and mw
        ):
            for candidate in mw.halls:
                same_number = candidate.number == self.zone_num
                if not same_number:
                    try:
                        same_number = int(candidate.number) == int(self.zone_num)
                    except (TypeError, ValueError):
                        same_number = False
                if same_number and candidate.audio_settings:
                    audio_info = candidate.audio_settings
                    break
        if audio_info:
            audio_line = format_audio_menu_line(audio_info)
            if audio_line:
                track_action = menu.addAction(audio_line)
                track_action.setEnabled(False)
        edit = menu.addAction("Редактировать"); delete = menu.addAction("Удалить")
        act = menu.exec(global_pos)
        if act == edit:
            hall = self.parentItem()
            if not hall:
                return
            current_audio = hall.zone_audio_tracks.get(self.zone_num) if hall else None
            dlg = ZoneEditDialog(self, current_audio, mw)
            if dlg.exec() == QDialog.Accepted:
                prev_state = mw.capture_state()
                values = dlg.values()
                old_num = self.zone_num
                self.zone_num = values['zone_num']
                self.zone_type = values['zone_type']
                self.zone_angle = values['angle']
                self.update_zvalue()
                self._apply_zone_palette()
                ppcm = scene.pixel_per_cm_x
                w_px = values['w'] * ppcm * 100
                h_px = values['h'] * ppcm * 100
                self.prepareGeometryChange()
                self.setRect(0, -h_px, w_px, h_px)
                self.setTransformOriginPoint(0,0)
                self.setRotation(-self.zone_angle)
                px = values['x'] * ppcm * 100
                py = hall.rect().height() - values['y'] * ppcm * 100
                self.setPos(QPointF(px, py))
                self.update_zvalue()
                audio_data = values['audio']
                if audio_data:
                    hall.zone_audio_tracks[self.zone_num] = audio_data
                else:
                    hall.zone_audio_tracks.pop(self.zone_num, None)
                if old_num != self.zone_num:
                    others = [z for z in hall.childItems() if isinstance(z, RectZoneItem) and z.zone_num == old_num and z is not self]
                    if not others:
                        hall.zone_audio_tracks.pop(old_num, None)
                mw.last_selected_items = []
                mw.populate_tree()
                mw.push_undo_state(prev_state)
        elif act == delete:
            confirm = QMessageBox.question(
                mw,
                "Подтвердить",
                f"Удалить зону {self.zone_num} ({self.get_display_type()})?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirm != QMessageBox.Yes:
                return
            prev_state = mw.capture_state()
            hall = self.parentItem()
            if hall:
                others = [z for z in hall.childItems() if isinstance(z, RectZoneItem) and z.zone_num == self.zone_num and z is not self]
                if not others:
                    hall.zone_audio_tracks.pop(self.zone_num, None)
            scene.removeItem(self)
            mw.last_selected_items = []; mw.populate_tree()
            mw.push_undo_state(prev_state)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.scene():
            anchor = _top_anchor(self.scene(), event.scenePos())
            if anchor:
                event.ignore()
                return
            smaller = _smallest_zone(self.scene(), event.scenePos(), exclude=self, max_area=_zone_area(self))
            if smaller:
                event.ignore()
                return
            mw = self.scene().mainwindow
            if mw and not getattr(mw, "_restoring_state", False):
                self._undo_initial_pos = QPointF(self.scenePos())
                self._undo_snapshot = mw.capture_state()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        scene = self.scene()
        if scene:
            anchor = _top_anchor(scene, event.scenePos())
            if anchor:
                anchor.open_menu(event.screenPos())
                event.accept()
                return
            smaller = _smallest_zone(scene, event.scenePos(), exclude=self, max_area=_zone_area(self))
            if smaller:
                smaller.open_menu(event.screenPos())
                event.accept()
                return
        self.open_menu(event.screenPos())
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self.scene():
            if self._undo_snapshot is not None and self._undo_initial_pos is not None:
                if self.scenePos() != self._undo_initial_pos:
                    mw = self.scene().mainwindow
                    if mw:
                        mw.push_undo_state(self._undo_snapshot)
        self._undo_snapshot = None
        self._undo_initial_pos = None

    def contextMenuEvent(self, event):
        # ПКМ: приоритет — якорь → меньшая зона → текущая зона
        scene = self.scene()
        if scene:
            anchor = _top_anchor(scene, event.scenePos())
            if anchor:
                anchor.open_menu(event.screenPos())
                event.accept()
                return
            smaller = _smallest_zone(scene, event.scenePos(), exclude=self, max_area=_zone_area(self))
            if smaller:
                smaller.open_menu(event.screenPos())
                event.accept()
                return
        self.open_menu(event.screenPos())
        event.accept()


class ProximityZoneItem(QGraphicsItem):
    def __init__(self, anchor: AnchorItem, zone_num: int, dist_in: float, dist_out: float,
                 bound: bool = False, halls: list[int] | None = None, blist: list[int] | None = None,
                 audio: dict | None = None):
        super().__init__(anchor)
        self.anchor = anchor
        self.zone_num = zone_num
        self.dist_in = max(0.0, dist_in)
        self.dist_out = max(0.0, dist_out)
        self.bound = bool(bound)
        self.halls = halls or []
        self.blacklist = blist or []
        self.audio_info = copy.deepcopy(audio) if audio else None
        self.tree_item = None
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.update_zvalue()

    def _radius_px(self, meters: float) -> float:
        if not self.scene():
            return 0.0
        return max(0.0, meters * self.scene().pixel_per_cm_x * 100)

    def boundingRect(self):
        r = max(self._radius_px(self.dist_in), self._radius_px(self.dist_out))
        return QRectF(-r, -r, r * 2, r * 2)

    def shape(self):
        path = QPainterPath()
        r = max(self._radius_px(self.dist_in), self._radius_px(self.dist_out))
        if r <= 0:
            return path
        path.addEllipse(self.boundingRect())
        return path

    def paint(self, painter, option, widget=None):
        if not self.scene():
            return
        painter.save()
        r_in = self._radius_px(self.dist_in)
        r_out = self._radius_px(self.dist_out)
        if self.bound:
            color_in = QColor(*RectZoneItem._ZONE_RGB["Переходная"])
            color_out = QColor(*RectZoneItem._ZONE_RGB["Переходная"])
        else:
            color_in = QColor(*RectZoneItem._ZONE_RGB["Входная зона"])
            color_out = QColor(*RectZoneItem._ZONE_RGB["Выходная зона"])

        fill_radius = max(r_in, r_out)
        if fill_radius > 0:
            if self.bound:
                fill_base = color_out
            else:
                fill_base = color_out if r_out >= r_in else color_in
            fill_color = QColor(fill_base)
            fill_color.setAlpha(50)
            painter.setBrush(QBrush(fill_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(0, 0), fill_radius, fill_radius)

        if r_in > 0:
            pen = QPen(color_in, 2)
            painter.setPen(pen)
            painter.drawEllipse(QPointF(0, 0), r_in, r_in)
        if r_out > 0:
            pen = QPen(color_out, 2)
            painter.setPen(pen)
            painter.drawEllipse(QPointF(0, 0), r_out, r_out)

        font = QFont()
        font.setBold(True)
        painter.setFont(font)
        outline = QColor(180, 180, 180)
        metrics = painter.fontMetrics()
        text = str(self.zone_num)
        text_width = metrics.horizontalAdvance(text)
        x = -text_width / 2
        y = fill_radius - metrics.descent() - 2
        text_pos = QPointF(x, y)
        path = QPainterPath()
        path.addText(text_pos, font, text)
        painter.setPen(QPen(outline, 2))
        painter.drawPath(path)
        painter.fillPath(path, color_in if r_in > 0 else color_out)
        painter.restore()

    def update_zvalue(self):
        anchor_number = float(self.anchor.number) if isinstance(self.anchor.number, (int, float)) else 0.0
        zone_number = float(self.zone_num) if isinstance(self.zone_num, (int, float)) else 0.0
        self.setZValue(8000.0 + anchor_number * 0.1 + zone_number * 0.001)

    def _default_halls_text(self) -> str:
        return ", ".join(str(h) for h in self.halls)

    def _open_edit_dialog(self, mw):
        dlg = ProximityZoneDialog(
            anchor_id=self.anchor.number,
            zone_num=self.zone_num,
            dist_in=self.dist_in,
            dist_out=self.dist_out,
            bound=self.bound,
            halls=self._default_halls_text(),
            blist=", ".join(str(x) for x in self.blacklist),
            audio_data=self.audio_info,
            parent=mw,
        )
        if dlg.exec() != QDialog.Accepted:
            return None
        return dlg.values()

    def open_menu(self, global_pos: QPoint):
        scene = self.scene()
        mw = scene.mainwindow if scene else None
        if not mw:
            return
        menu = QMenu()
        header = menu.addAction(f"Зона {self.zone_num} — якорь {self.anchor.number}")
        header.setEnabled(False)
        audio_line = format_audio_menu_line(self.audio_info)
        if audio_line:
            track_action = menu.addAction(audio_line)
            track_action.setEnabled(False)
        edit = menu.addAction("Редактировать")
        delete = menu.addAction("Удалить")
        act = menu.exec(global_pos)
        if act == edit:
            prev_state = mw.capture_state()
            values = self._open_edit_dialog(mw)
            if values is None:
                return
            if not values['halls'] and self.anchor and self.anchor.main_hall_number is not None:
                values['halls'] = [self.anchor.main_hall_number]
            self.zone_num = values['zone_num']
            self.dist_in = values['dist_in']
            self.dist_out = values['dist_out']
            self.bound = values['bound']
            self.halls = values['halls']
            self.blacklist = values['blist']
            self.audio_info = copy.deepcopy(values.get('audio')) if values.get('audio') else None
            self.update_zvalue()
            mw.populate_tree()
            mw.push_undo_state(prev_state)
            self.update()
        elif act == delete:
            confirm = QMessageBox.question(
                mw,
                "Подтвердить",
                f"Удалить зону {self.zone_num}, привязанную к якорю {self.anchor.number}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            prev_state = mw.capture_state()
            mw.proximity_zones.remove(self)
            scene.removeItem(self)
            mw.populate_tree()
            mw.push_undo_state(prev_state)

    def _hit_anchor(self, event) -> bool:
        if not self.anchor:
            return False
        anchor_pos = self.mapToParent(event.pos())
        return self.anchor.shape().contains(anchor_pos)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._hit_anchor(event):
            event.ignore()
            return
        scene = self.scene()
        mw = scene.mainwindow if scene else None
        if mw:
            self.open_menu(event.screenPos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._hit_anchor(event):
            event.ignore()
            return
        super().mousePressEvent(event)


def _zone_area(zone):
    rect = zone.boundingRect()
    return abs(rect.width() * rect.height())

def _top_anchor(scene, pos):
    if scene is None:
        return None
    # Точное попадание по форме якоря; возьмем верхний по Z
    for item in scene.items(pos, Qt.ContainsItemShape):
        if isinstance(item, AnchorItem):
            return item
    return None

def _smallest_zone(scene, pos, exclude=None, max_area=None):
    if scene is None:
        return None
    best = None
    best_area = None
    for item in scene.items(pos, Qt.IntersectsItemShape):
        if isinstance(item, (RectZoneItem, ProximityZoneItem)) and item is not exclude:
            rect = item.boundingRect()
            area = abs(rect.width() * rect.height())
            if max_area is not None and area >= max_area:
                continue
            if best is None or area < best_area:
                best = item
                best_area = area
    return best

# ---------------------------------------------------------------------------
# Custom view and scene
# ---------------------------------------------------------------------------
class MyGraphicsView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self._panning = False
        self._pan_start = QPoint()
        self.viewport().setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        scene = self.scene()
        mw = scene.mainwindow if scene else None
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            should_pan = False
            if event.button() == Qt.MiddleButton:
                should_pan = True
            elif event.button() == Qt.LeftButton:
                if not (mw and mw.add_mode):
                    point = event.position().toPoint()
                    if self.itemAt(point) is None:
                        should_pan = True
            if should_pan:
                self._panning = True
                self._pan_start = event.position().toPoint()
                self.viewport().setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            pos = event.position().toPoint()
            delta = pos - self._pan_start
            self._pan_start = pos
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        try:
            QTimer.singleShot(0, self.scene().mainwindow.update_tree_selection)
        except:
            pass

class PlanGraphicsScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.mainwindow=None; self.pixmap=None
        self.pixel_per_cm_x=1.0; self.pixel_per_cm_y=1.0
        self.grid_step_cm=20.0; self.temp_item=None

    def set_background_image(self, pix):
        self.pixmap = pix
        self.setSceneRect(0, 0, pix.width(), pix.height())
        if self.mainwindow:
            self.mainwindow._reset_background_cache()

    def drawBackground(self, painter, rect):
        if self.pixmap:
            painter.drawPixmap(0, 0, self.pixmap)
        step = self.pixel_per_cm_x * self.grid_step_cm
        if step <= 0:
            return
        left = int(rect.left()) - (int(rect.left()) % int(step))
        top = int(rect.top()) - (int(rect.top()) % int(step))
        right = int(rect.right()); bottom = int(rect.bottom())
        pen = QPen(QColor(0,0,0,50)); pen.setWidth(0)
        painter.setPen(pen)
        x = left
        while x <= right:
            painter.drawLine(x, top, x, bottom)
            x += step
        y = top
        while y <= bottom:
            painter.drawLine(left, y, right, y)
            y += step

    def finishCalibration(self, start, end):
        mw = self.mainwindow
        if not mw:
            return
        prev_state = mw.capture_state()
        diff = math.hypot(end.x()-start.x(), end.y()-start.y())
        length_cm, ok = QInputDialog.getDouble(
            mw, "Калибровка масштаба",
            "Введите длину отрезка (см):", 100.0, 0.1, 10000.0, 1
        )
        if ok and length_cm:
            scale = diff / length_cm
            self.pixel_per_cm_x = self.pixel_per_cm_y = scale
        mw.add_mode = None; mw.temp_start_point = None
        if self.temp_item:
            self.removeItem(self.temp_item); self.temp_item = None
        mw.statusBar().showMessage("Калибровка завершена."); mw.grid_calibrated = True
        step, ok = QInputDialog.getInt(
            mw, "Шаг сетки", "Укажите шаг (см):", 10, 1, 1000
        )
        if ok: self.grid_step_cm = float(step)
        mw.resnap_objects(); self.update()
        mw.push_undo_state(prev_state)

    def mousePressEvent(self, event):
        mw = self.mainwindow; pos = event.scenePos()
        if mw and mw.add_mode:
            m = mw.add_mode
            if m == "calibrate":
                if not mw.temp_start_point:
                    mw.temp_start_point = pos
                    self.temp_item = QGraphicsLineItem()
                    pen = QPen(QColor(255,0,0),2)
                    self.temp_item.setPen(pen); self.addItem(self.temp_item)
                    self.temp_item.setLine(pos.x(), pos.y(), pos.x(), pos.y())
                else:
                    QTimer.singleShot(0, lambda: self.finishCalibration(mw.temp_start_point, pos))
                return
            if m == "hall":
                if not mw.temp_start_point:
                    mw.temp_start_point = pos
                    self.temp_item = QGraphicsRectItem()
                    pen = QPen(QColor(0,0,255),2); pen.setStyle(Qt.DashLine)
                    self.temp_item.setPen(pen); self.temp_item.setBrush(QColor(0,0,0,0))
                    self.addItem(self.temp_item)
                    self.temp_item.setRect(QRectF(pos, QSizeF(0,0)))
                return
            if m == "zone":
                if not mw.temp_start_point:
                    hall = next((h for h in mw.halls if h.contains(h.mapFromScene(pos))), None)
                    if not hall: return
                    mw.current_hall_for_zone = hall; mw.temp_start_point = pos
                    self.temp_item = QGraphicsRectItem()
                    pen = QPen(QColor(0,128,0),2); pen.setStyle(Qt.DashLine)
                    self.temp_item.setPen(pen); self.temp_item.setBrush(QColor(0,0,0,0))
                    self.addItem(self.temp_item)
                    self.temp_item.setRect(QRectF(pos, QSizeF(0,0)))
                return
            if m == "anchor":
                hall = next((h for h in mw.halls if h.contains(h.mapFromScene(pos))), None)
                if not hall:
                    QMessageBox.warning(mw, "Ошибка", "Не найден зал для якоря."); return
                params = mw.get_anchor_parameters()
                if not params:
                    mw.add_mode=None; mw.statusBar().clearMessage(); return
                prev_state = mw.capture_state()
                num, z_m, extras, bound = params  # z в метрах
                a = AnchorItem(pos.x(), pos.y(), num, main_hall_number=hall.number, scene=self)
                a.z = int(round(z_m * 100))       # храним в см
                a.extra_halls, a.bound = extras, bound
                a.bound_explicit = bound
                self.addItem(a); mw.anchors.append(a)
                mw.add_mode=None; mw.statusBar().clearMessage(); mw.populate_tree()
                mw.push_undo_state(prev_state)
                return
            if m == "proximity_zone":
                anchor = _top_anchor(self, pos)
                if not anchor:
                    QMessageBox.warning(mw, "Ошибка", "Укажите существующий якорь для зоны.")
                    mw.add_mode=None; mw.statusBar().clearMessage(); return
                params = mw.get_proximity_zone_parameters(anchor)
                if not params:
                    mw.add_mode=None; mw.statusBar().clearMessage(); return
                prev_state = mw.capture_state()
                values = params
                if not values['halls'] and anchor.main_hall_number is not None:
                    values['halls'] = [anchor.main_hall_number]
                zone = ProximityZoneItem(
                    anchor,
                    values['zone_num'],
                    values['dist_in'],
                    values['dist_out'],
                    values['bound'],
                    values['halls'],
                    values['blist'],
                    values.get('audio'),
                )
                mw.proximity_zones.append(zone)
                mw.add_mode=None; mw.statusBar().clearMessage(); mw.populate_tree(); mw.push_undo_state(prev_state)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        mw = self.mainwindow
        if mw and mw.add_mode in ("hall","zone") and mw.temp_start_point:
            start = mw.temp_start_point; pos = event.scenePos()
            if mw.add_mode == "zone" and mw.current_hall_for_zone:
                hall = mw.current_hall_for_zone
                local = hall.mapFromScene(pos)
                local.setX(max(0,min(local.x(), hall.rect().width())))
                local.setY(max(0,min(local.y(), hall.rect().height())))
                pos = hall.mapToScene(local)
            if self.temp_item:
                self.temp_item.setRect(QRectF(start, pos).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        mw = self.mainwindow; pos = event.scenePos()
        if mw and mw.add_mode == "hall" and mw.temp_start_point:
            start, end = mw.temp_start_point, pos
            rect = QRectF(start, end).normalized()
            step = self.pixel_per_cm_x * self.grid_step_cm
            x0,y0,x1,y1 = rect.left(),rect.top(),rect.right(),rect.bottom()
            if step>0:
                x0,y0=round(x0/step)*step,round(y0/step)*step
                x1,y1=round(x1/step)*step,round(y1/step)*step
            if x1==x0: x1=x0+step
            if y1==y0: y1=y0+step
            w_px, h_px = x1-x0, y1-y0
            prev_state = mw.capture_state()
            hall = HallItem(x0, y0, w_px, h_px, "", 0, scene=self)
            self.addItem(hall); mw.halls.append(hall)
            # prompt parameters
            w_m = w_px/(self.pixel_per_cm_x*100)
            h_m = h_px/(self.pixel_per_cm_x*100)
            params = getHallParameters(1, "", w_m, h_m, self)
            if not params:
                self.removeItem(hall); mw.halls.remove(hall)
            else:
                num, name, new_w_m, new_h_m = params
                hall.number, hall.name = num, name
                # resize if needed
                w2_px = new_w_m * self.pixel_per_cm_x * 100
                h2_px = new_h_m * self.pixel_per_cm_x * 100
                hall.prepareGeometryChange()
                hall.setRect(0,0,w2_px,h2_px)
                hall.setZValue(-w2_px*h2_px)
                mw.push_undo_state(prev_state)
            mw.last_selected_items=[]; mw.populate_tree()
            mw.temp_start_point=None; mw.add_mode=None
            if self.temp_item: self.removeItem(self.temp_item); self.temp_item=None
            return

        if mw and mw.add_mode == "zone" and mw.temp_start_point:
            hall = mw.current_hall_for_zone
            if not hall:
                mw.temp_start_point=None; mw.add_mode=None
                if self.temp_item: self.removeItem(self.temp_item); self.temp_item=None
                return
            lr = QRectF(hall.mapFromScene(mw.temp_start_point), hall.mapFromScene(pos)).normalized()
            step = self.pixel_per_cm_x * self.grid_step_cm
            x0,y0,x1,y1 = lr.left(),lr.top(),lr.right(),lr.bottom()
            if step>0:
                x0,y0=round(x0/step)*step,round(y0/step)*step
                x1,y1=round(x1/step)*step,round(y1/step)*step
            if x1==x0: x1=x0+step
            if y1==y0: y1=y0+step
            bl = QPointF(min(x0,x1), max(y0,y1))
            w_pix, h_pix = abs(x1-x0), abs(y1-y0)
            params = getZoneParameters(1, "Входная зона", 0)
            if not params:
                if self.temp_item: self.removeItem(self.temp_item); self.temp_item=None
                mw.temp_start_point=None; mw.add_mode=None
                return
            prev_state = mw.capture_state()
            num, zt, ang = params
            RectZoneItem(bl, w_pix, h_pix, num, zt, ang, hall)
            mw.last_selected_items=[]; mw.populate_tree()
            mw.temp_start_point=None; mw.add_mode=None; mw.current_hall_for_zone=None
            if self.temp_item: self.removeItem(self.temp_item); self.temp_item=None
            mw.push_undo_state(prev_state)
            return

        super().mouseReleaseEvent(event)
        try:
            mw.populate_tree()
            handled = False
            if (event.button() == Qt.LeftButton and mw and not mw.add_mode):
                down = event.buttonDownScenePos(Qt.LeftButton) if hasattr(event, "buttonDownScenePos") else pos
                diff = pos - down
                if abs(diff.x()) < 2 and abs(diff.y()) < 2:
                    items_at = [it for it in self.items(pos, Qt.IntersectsItemShape)
                                 if it.flags() & QGraphicsItem.ItemIsSelectable]
                    if items_at:
                        def item_area(it):
                            if isinstance(it, QGraphicsRectItem):
                                rect = it.rect()
                                return abs(rect.width()*rect.height())
                            br = it.boundingRect()
                            return abs(br.width()*br.height())
                        def priority(it):
                            return 0 if isinstance(it, (AnchorItem, RectZoneItem)) else 1
                        chosen = min(items_at, key=lambda it: (item_area(it), priority(it)))
                        if not (event.modifiers() & Qt.ControlModifier):
                            for selected in list(self.selectedItems()):
                                if selected is not chosen:
                                    selected.setSelected(False)
                        chosen.setSelected(True)
                        mw.last_selected_items = list(self.selectedItems()) or [chosen]
                        mw.on_scene_selection_changed()
                        handled = True
            if not handled and not self.selectedItems():
                clicked = self.itemAt(pos, self.views()[0].transform())
                if clicked:
                    clicked.setSelected(True)
                    mw.last_selected_items=[clicked]; mw.on_scene_selection_changed()
        except: pass

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class PlanEditorMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project_name: str = ""
        self.project_root_dir: str | None = None
        self.project_content_dir: str | None = None
        self._update_window_title()
        self.resize(1200,800)

        self._icons_dir = os.path.join(os.path.dirname(__file__), "icons")
        self._apply_app_icon()

        dark_color = QColor("#e3e3e3")
        palette = self.palette()
        palette.setColor(QPalette.Window, dark_color)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self._readme_path = os.path.join(os.path.dirname(__file__), "readme.md")
        self._cached_readme_text = None
        self._cached_version = None

        self.scene = PlanGraphicsScene(); self.scene.mainwindow=self
        self.scene.selectionChanged.connect(self.on_scene_selection_changed)
        self.view = MyGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        central_widget = QWidget()
        central_widget.setObjectName("centralContainer")
        central_layout = QVBoxLayout(central_widget)
        margin = 8
        central_layout.setContentsMargins(margin, margin, margin, margin)

        central_frame = QWidget()
        central_frame.setObjectName("centralFrame")
        frame_layout = QVBoxLayout(central_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.view)

        central_widget.setStyleSheet(
            """
            QWidget#centralContainer {
                background-color: rgba(255, 255, 255, 25);
            }
            QWidget#centralFrame {
                border: none;
                border-radius: 8px;
                background-color: rgba(255, 255, 255, 235);
            }
            QWidget#centralFrame > * {
                background-color: transparent;
            }
            """
        )
        central_layout.addWidget(central_frame)
        self.setCentralWidget(central_widget)

        self.tree = QTreeWidget(); self.tree.setHeaderLabel("Объекты"); self.tree.setWordWrap(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_context_menu)
        self.tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)

        dock_container = QWidget()
        dock_container.setObjectName("dockContainer")
        dock_layout = QVBoxLayout(dock_container)
        dock_layout.setContentsMargins(margin, margin, margin, margin)

        dock_frame = QWidget()
        dock_frame.setObjectName("dockFrame")
        dock_frame_layout = QVBoxLayout(dock_frame)
        dock_frame_layout.setContentsMargins(0, 0, 0, 0)
        dock_frame_layout.addWidget(self.tree)

        dock_container.setStyleSheet(
            """
            QWidget#dockContainer {
                background-color: rgba(255, 255, 255, 25);
            }
            QWidget#dockFrame {
                border: none;
                border-radius: 8px;
                background-color: rgba(255, 255, 255, 235);
            }
            QWidget#dockFrame > * {
                background-color: transparent;
            }
            QTreeWidget {
                background-color: transparent;
            }
            """
        )
        dock_layout.addWidget(dock_frame)

        dock = QDockWidget("Список объектов", self); dock.setWidget(dock_container)
        dock.setObjectName("objectsDock")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.objects_dock = dock

        self.tracks_panel = TracksListWidget(self)

        tracks_container = QWidget()
        tracks_container.setObjectName("tracksDockContainer")
        tracks_layout = QVBoxLayout(tracks_container)
        tracks_layout.setContentsMargins(margin, margin, margin, margin)

        tracks_frame = QWidget()
        tracks_frame.setObjectName("tracksDockFrame")
        tracks_frame_layout = QVBoxLayout(tracks_frame)
        tracks_frame_layout.setContentsMargins(0, 0, 0, 0)
        tracks_frame_layout.addWidget(self.tracks_panel)

        tracks_container.setStyleSheet(
            """
            QWidget#tracksDockContainer {
                background-color: rgba(255, 255, 255, 25);
            }
            QWidget#tracksDockFrame {
                border: none;
                border-radius: 8px;
                background-color: rgba(255, 255, 255, 235);
            }
            QWidget#tracksDockFrame > * {
                background-color: transparent;
            }
            QTreeWidget {
                background-color: transparent;
            }
            """
        )
        tracks_layout.addWidget(tracks_frame)

        tracks_dock = QDockWidget("Список треков", self)
        tracks_dock.setObjectName("tracksDock")
        tracks_dock.setWidget(tracks_container)
        tracks_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        tracks_dock.setAllowedAreas(Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.TopDockWidgetArea, tracks_dock)
        tracks_dock.hide()
        self.tracks_dock = tracks_dock

        self._create_actions()
        self._create_menus()
        self._create_toolbars()

        self.objects_dock.visibilityChanged.connect(self._on_objects_dock_visibility_changed)
        self.tracks_dock.visibilityChanged.connect(self._on_tracks_dock_visibility_changed)

        self.add_mode = None; self.temp_start_point = None
        self.current_hall_for_zone = None
        self.halls = []; self.anchors = []; self.proximity_zones = []
        self.grid_calibrated = False
        self.lock_halls = False; self.lock_zones = False; self.lock_anchors = False
        self.last_selected_items = []
        self.current_project_file = None
        self.unmatched_audio_files = {}
        self.undo_stack = []
        self._undo_limit = 30
        self._restoring_state = False
        self._undo_bg_cache_key = None
        self._undo_bg_image = ""
        self._saved_state_snapshot = None

        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.wheelEvent = self.handle_wheel_event
        self.statusBar().setMinimumHeight(30)
        self.statusBar().showMessage("Загрузите изображение для начала работы.")
        self.update_undo_action()
        self.populate_tracks_table()
        self._restore_window_preferences()

    def _save_window_preferences(self):
        settings = app_settings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        settings.setValue("window/objects_dock_visible", self.objects_dock.isVisible())
        settings.setValue("window/tracks_dock_visible", self.tracks_dock.isVisible())

    def _restore_window_preferences(self):
        settings = app_settings()
        geometry = settings.value("window/geometry")
        state = settings.value("window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

        objects_visible = settings.value("window/objects_dock_visible", True, type=bool)
        tracks_visible = settings.value("window/tracks_dock_visible", False, type=bool)
        self.objects_dock.setVisible(bool(objects_visible))
        self.tracks_dock.setVisible(bool(tracks_visible))

    def _apply_app_icon(self):
        icon_path = os.path.join(self._icons_dir, "app.png")
        if not os.path.exists(icon_path):
            return
        icon = QIcon(icon_path)
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)

    @staticmethod
    def _sanitize_name_for_folder(name: str) -> str:
        sanitized_chars = []
        for ch in name:
            if ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
                sanitized_chars.append("_")
            elif ch.isspace():
                sanitized_chars.append("_")
            else:
                sanitized_chars.append(ch)
        sanitized = "".join(sanitized_chars).strip("_")
        return sanitized

    def _build_remote_export_folder_name(self) -> str:
        timestamp = datetime.now().strftime("%y%m%d_%H%M")
        candidates: list[str] = []
        project_name = getattr(self, "project_name", "")
        if isinstance(project_name, str) and project_name.strip():
            candidates.append(project_name.strip())
        if isinstance(self.current_project_file, str) and self.current_project_file:
            candidates.append(os.path.splitext(os.path.basename(self.current_project_file))[0])

        for name in candidates:
            sanitized = self._sanitize_name_for_folder(name)
            if sanitized:
                return f"{sanitized}_{timestamp}"
        return timestamp

    def _update_window_title(self):
        base_title = "RG Tags Mapper"
        name = self.project_name.strip()
        if name:
            self.setWindowTitle(f"{base_title} — {name}")
        else:
            self.setWindowTitle(base_title)
    def _ensure_project_paths(self, project_file: str):
        project_file_abs = os.path.abspath(project_file)
        project_dir = os.path.dirname(project_file_abs)
        project_base_name = os.path.splitext(os.path.basename(project_file_abs))[0]
        project_folder_name = self._sanitize_name_for_folder(project_base_name) or project_base_name
        root_dir = os.path.join(project_dir, project_folder_name)
        content_dir = os.path.join(root_dir, "content")

        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)
        os.makedirs(content_dir, exist_ok=True)

        self.project_root_dir = root_dir
        self.project_content_dir = content_dir

    def _ensure_project_layout_for_current_file(self):
        if not self.current_project_file:
            return False
        try:
            self._ensure_project_paths(self.current_project_file)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось подготовить структуру проекта:\n{exc}")
            return False

    def _get_effective_project_root_dir(self):
        if self.project_root_dir and os.path.isdir(self.project_root_dir):
            return self.project_root_dir
        if self.current_project_file:
            project_file_abs = os.path.abspath(self.current_project_file)
            project_dir = os.path.dirname(project_file_abs)
            project_base_name = os.path.splitext(os.path.basename(project_file_abs))[0]
            project_folder_name = self._sanitize_name_for_folder(project_base_name) or project_base_name
            return os.path.join(project_dir, project_folder_name)
        return None

    def _get_effective_content_dir(self):
        if self.project_content_dir and os.path.isdir(self.project_content_dir):
            return self.project_content_dir
        root_dir = self._get_effective_project_root_dir()
        if not root_dir:
            return None
        return os.path.join(root_dir, "content")

    def _rooms_json_path(self):
        if not self.current_project_file:
            return None
        project_file_abs = os.path.abspath(self.current_project_file)
        project_dir = os.path.dirname(project_file_abs)
        return os.path.join(project_dir, "rooms.json")

    def _tracks_json_path(self):
        content_dir = self._get_effective_content_dir()
        if not content_dir:
            return None
        return os.path.join(content_dir, "tracks.json")

    def _write_auxiliary_configs(self, rooms_json_text: str, tracks_data: dict):
        if not self._ensure_project_layout_for_current_file():
            return False
        rooms_path = self._rooms_json_path()
        tracks_path = self._tracks_json_path()
        if not rooms_path or not tracks_path:
            return False
        self._recalculate_tracks_files_metadata(tracks_data)
        try:
            with open(rooms_path, "w", encoding="utf-8") as rooms_file:
                rooms_file.write(rooms_json_text)
            with open(tracks_path, "w", encoding="utf-8") as tracks_file:
                json.dump(tracks_data, tracks_file, ensure_ascii=False, indent=4)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить rooms/tracks:\n{exc}")
            return False
        return True

    def _sync_auxiliary_configs_from_current_state(self, show_errors: bool = True) -> bool:
        if not self.current_project_file:
            return False
        rooms_json_text, tracks_data = self._prepare_export_payload()
        self._merge_unmatched_audio_files_into_tracks_data(tracks_data)
        self._merge_existing_tracks_metadata(tracks_data)
        if self._write_auxiliary_configs(rooms_json_text, tracks_data):
            return True
        if not show_errors:
            self.statusBar().showMessage("Не удалось синхронизировать rooms/tracks с текущим состоянием проекта.", 5000)
        return False

    @staticmethod
    def _merge_audio_info_preserving_track_settings(existing_info: dict | None, incoming_info: dict | None) -> dict | None:
        if not isinstance(incoming_info, dict):
            return copy.deepcopy(existing_info) if isinstance(existing_info, dict) else None
        merged = copy.deepcopy(existing_info) if isinstance(existing_info, dict) else {}
        merged.update(copy.deepcopy(incoming_info))

        def _preserve_bool(key: str, default: bool):
            if isinstance(existing_info, dict) and key in existing_info:
                merged[key] = bool(existing_info.get(key, default))
            elif key in merged:
                merged[key] = bool(merged.get(key, default))
            else:
                merged[key] = default

        _preserve_bool("interruptible", True)
        _preserve_bool("reset", False)
        _preserve_bool("play_once", False)

        if isinstance(existing_info, dict) and "extra_ids" in existing_info:
            merged["extra_ids"] = normalize_int_list(existing_info.get("extra_ids"))
        else:
            merged["extra_ids"] = normalize_int_list(merged.get("extra_ids"))

        if isinstance(existing_info, dict) and "display_name" in existing_info:
            name = (existing_info.get("display_name") or "").strip()
            if name:
                merged["display_name"] = name
            else:
                merged.pop("display_name", None)
        elif "display_name" in merged:
            merged_name = (merged.get("display_name") or "").strip()
            if merged_name:
                merged["display_name"] = merged_name
            else:
                merged.pop("display_name", None)

        if isinstance(existing_info, dict) and isinstance(existing_info.get("secondary"), dict):
            merged["secondary"] = copy.deepcopy(existing_info["secondary"])

        return merged

    def _iter_project_audio_files(self):
        content_dir = self._get_effective_content_dir()
        if not content_dir or not os.path.isdir(content_dir):
            return []
        results = []
        for entry in sorted(os.listdir(content_dir)):
            lower_name = entry.lower()
            if not lower_name.endswith('.mp3'):
                continue
            full_path = os.path.join(content_dir, entry)
            if os.path.isfile(full_path):
                results.append(full_path)
        return results

    def _recalculate_tracks_files_metadata(self, tracks_data: dict):
        if not isinstance(tracks_data, dict):
            return
        files_section = tracks_data.get("files")
        if not isinstance(files_section, list):
            return
        content_dir = self._get_effective_content_dir()
        if not content_dir or not os.path.isdir(content_dir):
            return

        for entry in files_section:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            file_path = os.path.join(content_dir, name)
            if not os.path.isfile(file_path):
                continue

            try:
                size_bytes = os.path.getsize(file_path)
            except OSError:
                continue

            crc = 0
            try:
                with open(file_path, "rb") as file_handle:
                    while True:
                        chunk = file_handle.read(4096)
                        if not chunk:
                            break
                        crc = zlib.crc32(chunk, crc)
            except OSError:
                continue

            entry["size"] = int(max(size_bytes, 0))
            entry["crc32"] = f"{crc & 0xFFFFFFFF:08x}"


    def _create_actions(self):
        def load_icon(filename: str, fallback: QStyle.StandardPixmap | None = None):
            path = os.path.join(self._icons_dir, filename)
            if os.path.exists(path):
                return QIcon(path)
            if fallback is not None:
                return self.style().standardIcon(fallback)
            return QIcon()

        self.action_open = QAction(
            load_icon("open.png", QStyle.SP_DialogOpenButton),
            "Новый проект",
            self,
        )
        self.action_open.triggered.connect(self.open_image)

        self.action_save = QAction(
            load_icon("save.png", QStyle.SP_DialogSaveButton),
            "Сохранить проект",
            self,
        )
        self.action_save.triggered.connect(self.save_project)

        self.action_save_as = QAction(
            load_icon("save.png", QStyle.SP_DialogSaveButton),
            "Сохранить проект как…",
            self,
        )
        self.action_save_as.triggered.connect(self.save_project_as)

        self.action_project_properties = QAction(
            "Свойства проекта",
            self,
        )
        self.action_project_properties.triggered.connect(self.show_project_properties_dialog)

        self.action_load = QAction(
            load_icon("load.png", QStyle.SP_DialogOpenButton),
            "Загрузить проект",
            self,
        )
        self.action_load.triggered.connect(self.load_project)

        self.action_import = QAction(
            load_icon("import.png", QStyle.SP_DialogOpenButton),
            "Импорт конфигурации",
            self,
        )
        self.action_import.triggered.connect(self.show_import_menu)

        self.action_export = QAction(
            load_icon("export.png", QStyle.SP_DialogSaveButton),
            "Экспорт конфигурации",
            self,
        )
        self.action_export.triggered.connect(self.show_export_menu)

        self.action_refresh_audio = QAction(
            load_icon("audio.png", QStyle.SP_BrowserReload),
            "Обновить аудио",
            self,
        )
        self.action_refresh_audio.triggered.connect(self.refresh_audio_from_content)

        self.action_upload = QAction(
            load_icon("server.png", QStyle.SP_ArrowUp),
            "Выгрузить на сервер",
            self,
        )
        self.action_upload.triggered.connect(self.upload_config_to_server)

        self.action_pdf = QAction(
            load_icon("pdf.png", QStyle.SP_FileDialogDetailedView),
            "Сохранить в PDF",
            self,
        )
        self.action_pdf.triggered.connect(self.save_to_pdf)

        self.action_calibrate = QAction(
            load_icon("calibration.png", QStyle.SP_ComputerIcon),
            "Выполнить калибровку",
            self,
        )
        self.action_calibrate.triggered.connect(self.perform_calibration)

        self.action_add_hall = QAction(
            load_icon("hall.png", QStyle.SP_FileDialogNewFolder),
            "Добавить зал",
            self,
        )
        self.action_add_hall.triggered.connect(lambda: self.set_mode("hall"))

        self.action_add_anchor = QAction(
            load_icon("anchor.png", QStyle.SP_FileDialogNewFolder),
            "Добавить якорь",
            self,
        )
        self.action_add_anchor.triggered.connect(lambda: self.set_mode("anchor"))

        self.action_add_zone = QAction(
            load_icon("zone.png", QStyle.SP_FileDialogNewFolder),
            "Добавить зону",
            self,
        )
        self.action_add_zone.triggered.connect(lambda: self.set_mode("zone"))

        self.action_add_proximity_zone = QAction(
            load_icon("zone2.png", QStyle.SP_FileDialogNewFolder),
            "Добавить зону по приближению",
            self,
        )
        self.action_add_proximity_zone.triggered.connect(lambda: self.set_mode("proximity_zone"))

        self.act_lock = QAction(
            load_icon("lock.png", QStyle.SP_DialogCloseButton),
            "Закрепить объекты",
            self,
        )
        self.act_lock.triggered.connect(self.lock_objects)

        self.undo_action = QAction(
            load_icon("undo.png", QStyle.SP_ArrowBack),
            "Отменить",
            self,
        )
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self.undo_last_action)

        self.action_help = QAction("Справка по RG Tags Mapper", self)
        self.action_help.triggered.connect(self.show_help_contents)

        self.action_about = QAction("О приложении...", self)
        self.action_about.triggered.connect(self.show_about_dialog)

        self.action_toggle_objects_dock = QAction("Окно \"Список объектов\"", self)
        self.action_toggle_objects_dock.setCheckable(True)
        self.action_toggle_objects_dock.setChecked(True)
        self.action_toggle_objects_dock.toggled.connect(self._toggle_objects_dock)

        self.action_toggle_tracks_dock = QAction("Окно \"Список треков\"", self)
        self.action_toggle_tracks_dock.setCheckable(True)
        self.action_toggle_tracks_dock.setChecked(False)
        self.action_toggle_tracks_dock.toggled.connect(self._toggle_tracks_dock)

    def _create_menus(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("Файл")
        file_menu.addAction(self.action_open)
        file_menu.addSeparator()
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addAction(self.action_project_properties)
        file_menu.addAction(self.action_load)
        file_menu.addSeparator()
        file_menu.addAction(self.action_import)
        file_menu.addAction(self.action_export)
        file_menu.addAction(self.action_refresh_audio)
        file_menu.addAction(self.action_upload)
        file_menu.addAction(self.action_pdf)

        edit_menu = menu_bar.addMenu("Правка")
        edit_menu.addAction(self.undo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_lock)

        tools_menu = menu_bar.addMenu("Инструменты")
        tools_menu.addAction(self.action_calibrate)
        tools_menu.addSeparator()
        tools_menu.addAction(self.action_add_hall)
        tools_menu.addAction(self.action_add_anchor)
        tools_menu.addAction(self.action_add_zone)
        tools_menu.addAction(self.action_add_proximity_zone)

        view_menu = menu_bar.addMenu("Вид")
        view_menu.addAction(self.action_toggle_objects_dock)
        view_menu.addAction(self.action_toggle_tracks_dock)

        help_menu = menu_bar.addMenu("Справка")
        help_menu.addAction(self.action_help)
        help_menu.addSeparator()
        help_menu.addAction(self.action_about)

        menu_bar.setStyleSheet(
            """
            QMenuBar {
                background-color: rgba(255, 255, 255, 235);
                border-bottom: 1px solid #b8b8b8;
                padding: 4px 6px;
            }
            QMenuBar::item {
                padding: 4px 10px;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background-color: rgba(240, 240, 240, 220);
            }
            """
        )

    def _create_toolbars(self):
        base_icon_size = QSize(48, 48)
        scale_factor = 1.2
        icon_size = QSize(
            int(round(base_icon_size.width() * scale_factor)),
            int(round(base_icon_size.height() * scale_factor)),
        )

        file_toolbar = QToolBar("Файл", self)
        file_toolbar.setObjectName("fileToolbar")
        file_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        file_toolbar.setIconSize(icon_size)
        file_toolbar.addAction(self.action_open)
        self._add_toolbar_group_separator(file_toolbar)
        file_toolbar.addAction(self.action_save)
        file_toolbar.addAction(self.action_load)
        self._add_toolbar_group_separator(file_toolbar)
        file_toolbar.addAction(self.action_import)
        file_toolbar.addAction(self.action_export)
        file_toolbar.addAction(self.action_upload)
        file_toolbar.addAction(self.action_pdf)
        self.addToolBar(file_toolbar)
        self.file_toolbar = file_toolbar

        tools_toolbar = QToolBar("Инструменты", self)
        tools_toolbar.setObjectName("toolsToolbar")
        tools_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        tools_toolbar.setIconSize(icon_size)
        tools_toolbar.addAction(self.action_calibrate)
        tools_toolbar.addAction(self.action_refresh_audio)
        self._add_toolbar_group_separator(tools_toolbar)
        tools_toolbar.addAction(self.action_add_hall)
        tools_toolbar.addAction(self.action_add_anchor)
        tools_toolbar.addAction(self.action_add_zone)
        tools_toolbar.addAction(self.action_add_proximity_zone)
        self._add_toolbar_group_separator(tools_toolbar)
        tools_toolbar.addAction(self.act_lock)
        self._add_toolbar_group_separator(tools_toolbar)
        tools_toolbar.addAction(self.undo_action)
        self.addToolBar(tools_toolbar)
        self.tools_toolbar = tools_toolbar

        toolbar_stylesheet = (
            """
            QToolBar {
                background-color: rgba(255, 255, 255, 235);
                border-top: 1px solid #c6c6c6;
                border-bottom: 1px solid #a9a9a9;
                padding: 3px 8px;
            }
            QToolBar::separator {
                width: 1px;
                background-color: #b5b5b5;
                margin: 0 6px;
            }
            QToolBar QToolButton {
                margin: 2px 4px;
                padding: 2px 4px;
                border-radius: 4px;
            }
            QToolBar QToolButton:hover {
                background-color: rgba(240, 240, 240, 220);
            }
            QToolBar QToolButton:pressed {
                background-color: rgba(225, 225, 225, 220);
            }
            """
        )
        self._toolbar_stylesheet = toolbar_stylesheet

    def _toggle_objects_dock(self, visible: bool):
        if getattr(self, "objects_dock", None) is None:
            return
        self.objects_dock.setVisible(visible)

    def _on_objects_dock_visibility_changed(self, visible: bool):
        if getattr(self, "action_toggle_objects_dock", None) is None:
            return
        self.action_toggle_objects_dock.blockSignals(True)
        self.action_toggle_objects_dock.setChecked(visible)
        self.action_toggle_objects_dock.blockSignals(False)

        for toolbar in (getattr(self, "file_toolbar", None), getattr(self, "tools_toolbar", None)):
            if toolbar is None:
                continue
            toolbar.setMovable(False)
            toolbar.setContentsMargins(6, 3, 6, 3)
            if toolbar.layout():
                toolbar.layout().setSpacing(8)
            toolbar.setStyleSheet(getattr(self, "_toolbar_stylesheet", ""))

    def _toggle_tracks_dock(self, visible: bool):
        if getattr(self, "tracks_dock", None) is None:
            return
        self.tracks_dock.setVisible(visible)

    def _on_tracks_dock_visibility_changed(self, visible: bool):
        if getattr(self, "action_toggle_tracks_dock", None) is None:
            return
        self.action_toggle_tracks_dock.blockSignals(True)
        self.action_toggle_tracks_dock.setChecked(visible)
        self.action_toggle_tracks_dock.blockSignals(False)

    def _load_readme_text(self) -> str | None:
        if self._cached_readme_text is not None:
            return self._cached_readme_text
        if not os.path.exists(self._readme_path):
            return None
        try:
            with open(self._readme_path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return None
        self._cached_readme_text = text
        return text

    def _get_app_version(self) -> str:
        if self._cached_version is not None:
            return self._cached_version
        if not os.path.exists(self._readme_path):
            self._cached_version = "неизвестна"
            return self._cached_version
        try:
            with open(self._readme_path, "r", encoding="utf-8") as fh:
                first_line = fh.readline().strip()
        except OSError:
            first_line = ""
        self._cached_version = first_line or "неизвестна"
        return self._cached_version

    def show_help_contents(self):
        text = self._load_readme_text()
        if text is None:
            QMessageBox.warning(self, "Справка", "Не удалось загрузить файл справки.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Справка по RG Tags Mapper")
        layout = QVBoxLayout(dialog)

        browser = QTextBrowser(dialog)
        if hasattr(browser, "setMarkdown"):
            browser.setMarkdown(text)
        else:
            browser.setPlainText(text)
        browser.setOpenExternalLinks(True)
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.resize(700, 500)
        dialog.exec()

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("О приложении")
        layout = QVBoxLayout(dialog)

        icon_path = os.path.join(self._icons_dir, "app.png")
        if os.path.exists(icon_path):
            logo_label = QLabel(dialog)
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                logo_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(logo_label)

        title_label = QLabel("RG Tags Mapper", dialog)
        title_font = QFont(title_label.font())
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        version_label = QLabel(f"Версия {self._get_app_version()}", dialog)
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        copyright_label = QLabel("Copyright (C) 2026, RadioGuide LLC", dialog)
        copyright_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(copyright_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.resize(400, 300)
        dialog.exec()

    def _toolbar_group_spacing(self, toolbar: QToolBar) -> int:
        base_spacing = toolbar.style().pixelMetric(QStyle.PM_ToolBarItemSpacing, None, toolbar)
        if base_spacing <= 0:
            base_spacing = max(8, toolbar.iconSize().width() // 4)
        return base_spacing

    def _add_toolbar_group_separator(self, toolbar: QToolBar):
        toolbar.addSeparator()
        spacer = QWidget(toolbar)
        spacer.setFixedWidth(self._toolbar_group_spacing(toolbar))
        spacer.setAttribute(Qt.WA_TransparentForMouseEvents)
        spacer.setFocusPolicy(Qt.NoFocus)
        toolbar.addWidget(spacer)

    def _reset_background_cache(self):
        self._undo_bg_cache_key = None
        self._undo_bg_image = ""

    def capture_state(self):
        data = {
            "image_data": "",
            "pixel_per_cm_x": self.scene.pixel_per_cm_x,
            "pixel_per_cm_y": self.scene.pixel_per_cm_y,
            "grid_step_cm": self.scene.grid_step_cm,
            "grid_calibrated": self.grid_calibrated,
            "lock_halls": self.lock_halls,
            "lock_zones": self.lock_zones,
            "lock_anchors": self.lock_anchors,
            "project_name": self.project_name,
            "current_project_file": self.current_project_file,
            "project_root_dir": self.project_root_dir,
            "project_content_dir": self.project_content_dir,
            "unmatched_audio_files": copy.deepcopy(self.unmatched_audio_files),
            "halls": [],
            "anchors": [],
            "proximity_zones": [],
        }
        if self.scene.pixmap:
            cache_key = self.scene.pixmap.cacheKey()
            if self._undo_bg_cache_key == cache_key and self._undo_bg_image:
                data["image_data"] = self._undo_bg_image
            else:
                buf = QBuffer(); buf.open(QBuffer.WriteOnly)
                self.scene.pixmap.save(buf, "PNG")
                encoded = buf.data().toBase64().data().decode()
                data["image_data"] = encoded
                self._undo_bg_cache_key = cache_key
                self._undo_bg_image = encoded
        else:
            self._reset_background_cache()
        for hall in self.halls:
            hall_data = {
                "num": hall.number,
                "name": hall.name,
                "x_px": hall.pos().x(),
                "y_px": hall.pos().y(),
                "w_px": hall.rect().width(),
                "h_px": hall.rect().height(),
                "audio": copy.deepcopy(hall.audio_settings) if hall.audio_settings else None,
                "extra_tracks": list(hall.extra_tracks),
                "zone_audio": {str(k): copy.deepcopy(v) for k, v in hall.zone_audio_tracks.items()}
            }
            zones = []
            for child in hall.childItems():
                if isinstance(child, RectZoneItem):
                    zones.append({
                        "zone_num": child.zone_num,
                        "zone_type": child.zone_type,
                        "zone_angle": child.zone_angle,
                        "bottom_left_x": child.pos().x(),
                        "bottom_left_y": child.pos().y(),
                        "w_px": child.rect().width(),
                        "h_px": child.rect().height()
                    })
            hall_data["zones"] = zones
            data["halls"].append(hall_data)
        for anchor in self.anchors:
            anchor_data = {
                "number": anchor.number,
                "z": anchor.z,
                "x": anchor.scenePos().x(),
                "y": anchor.scenePos().y(),
                "main_hall": anchor.main_hall_number,
                "extra_halls": list(anchor.extra_halls),
                "bound": anchor.bound_explicit
            }
            data["anchors"].append(anchor_data)
        for zone in self.proximity_zones:
            zone_data = {
                "zone_num": zone.zone_num,
                "anchor_id": zone.anchor.number,
                "dist_in": zone.dist_in,
                "dist_out": zone.dist_out,
                "bound": zone.bound,
                "halls": list(zone.halls),
                "blacklist": list(zone.blacklist),
                "audio": copy.deepcopy(zone.audio_info) if zone.audio_info else None,
            }
            data["proximity_zones"].append(zone_data)
        return data

    def restore_state(self, state):
        if not state:
            return
        self._restoring_state = True
        try:
            self.scene.clear()
            self.scene.temp_item = None
            self.halls.clear()
            self.anchors.clear()
            self.proximity_zones.clear()
            image_data = state.get("image_data") or ""
            if image_data:
                ba = QByteArray.fromBase64(image_data.encode())
                pix = QPixmap()
                pix.loadFromData(ba, "PNG")
                self.scene.set_background_image(pix)
            else:
                self.scene.pixmap = None
                self.scene.setSceneRect(0, 0, 1000, 1000)
                self._reset_background_cache()
            self.scene.pixel_per_cm_x = state.get("pixel_per_cm_x", 1.0)
            self.scene.pixel_per_cm_y = state.get("pixel_per_cm_y", 1.0)
            self.scene.grid_step_cm = state.get("grid_step_cm", 20.0)
            self.grid_calibrated = state.get("grid_calibrated", False)
            self.lock_halls = state.get("lock_halls", False)
            self.lock_zones = state.get("lock_zones", False)
            self.lock_anchors = state.get("lock_anchors", False)
            self.current_project_file = state.get("current_project_file")
            self.project_name = state.get("project_name", "") if isinstance(state.get("project_name", ""), str) else ""
            self.project_root_dir = state.get("project_root_dir")
            self.project_content_dir = state.get("project_content_dir")
            self.unmatched_audio_files = self._normalize_unmatched_audio_files(state.get("unmatched_audio_files"))
            self._update_window_title()
            for hall_data in state.get("halls", []):
                hall = HallItem(
                    hall_data.get("x_px", 0.0),
                    hall_data.get("y_px", 0.0),
                    hall_data.get("w_px", 0.0),
                    hall_data.get("h_px", 0.0),
                    hall_data.get("name", ""),
                    hall_data.get("num", 0),
                    scene=self.scene
                )
                hall.audio_settings = copy.deepcopy(hall_data.get("audio")) if hall_data.get("audio") else None
                hall.extra_tracks = normalize_int_list(hall_data.get("extra_tracks"))
                zone_audio_raw = hall_data.get("zone_audio") or {}
                hall.zone_audio_tracks = {}
                for k, v in zone_audio_raw.items():
                    try:
                        hall.zone_audio_tracks[int(k)] = copy.deepcopy(v)
                    except (TypeError, ValueError):
                        continue
                self.scene.addItem(hall)
                self.halls.append(hall)
                for zone_data in hall_data.get("zones", []):
                    bl = QPointF(zone_data.get("bottom_left_x", 0.0), zone_data.get("bottom_left_y", 0.0))
                    RectZoneItem(
                        bl,
                        zone_data.get("w_px", 0.0),
                        zone_data.get("h_px", 0.0),
                        zone_data.get("zone_num", 0),
                        zone_data.get("zone_type", "Входная зона"),
                        zone_data.get("zone_angle", 0.0),
                        hall
                    )
            anchor_map = {}
            for anchor_data in state.get("anchors", []):
                anchor = AnchorItem(
                    anchor_data.get("x", 0.0),
                    anchor_data.get("y", 0.0),
                    anchor_data.get("number", 0),
                    main_hall_number=anchor_data.get("main_hall"),
                    scene=self.scene
                )
                anchor.z = anchor_data.get("z", 0)
                anchor.extra_halls = list(anchor_data.get("extra_halls", []))
                anchor.bound = bool(anchor_data.get("bound", False))
                anchor.bound_explicit = anchor.bound
                self.scene.addItem(anchor)
                self.anchors.append(anchor)
                anchor_map[anchor.number] = anchor
            for zone_data in state.get("proximity_zones", []):
                anchor = anchor_map.get(zone_data.get("anchor_id"))
                if not anchor:
                    continue
                zone = ProximityZoneItem(
                    anchor,
                    zone_data.get("zone_num", 0),
                    float(zone_data.get("dist_in", 0.0)),
                    float(zone_data.get("dist_out", 0.0)),
                    bool(zone_data.get("bound", False)),
                    list(zone_data.get("halls", [])),
                    list(zone_data.get("blacklist", [])),
                    copy.deepcopy(zone_data.get("audio")) if zone_data.get("audio") else None,
                )
                self.proximity_zones.append(zone)
            if not image_data:
                rect = self.scene.itemsBoundingRect()
                if rect.isValid():
                    margin = 100
                    self.scene.setSceneRect(rect.adjusted(-margin, -margin, margin, margin))
            self.add_mode = None
            self.temp_start_point = None
            self.current_hall_for_zone = None
            self.apply_lock_flags()
            self.populate_tree()
            self.statusBar().clearMessage()
        finally:
            self._restoring_state = False

    def push_undo_state(self, state=None):
        if self._restoring_state:
            return
        snapshot = state if state is not None else self.capture_state()
        if snapshot is None:
            return
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self._undo_limit:
            self.undo_stack.pop(0)
        self.update_undo_action()

    def undo_last_action(self):
        if not self.undo_stack:
            return
        state = self.undo_stack.pop()
        self.restore_state(state)
        self.update_undo_action()
        self.statusBar().showMessage("Последнее действие отменено.", 3000)

    def update_undo_action(self):
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self.undo_stack))

    # Parameter getters...
    def get_anchor_parameters(self):
        default = 1 if not self.anchors else max(a.number for a in self.anchors)+1
        return getAnchorParameters(default, 0.0, "", False)  # Z по умолчанию в метрах
    def get_zone_parameters(self):
        default = 1
        if self.current_hall_for_zone:
            zs = [ch for ch in self.current_hall_for_zone.childItems() if isinstance(ch,RectZoneItem)]
            if zs: default = max(z.zone_num for z in zs)+1
        return getZoneParameters(default, "Входная зона", 0)

    def get_proximity_zone_parameters(self, anchor: AnchorItem):
        default = 1 if not self.proximity_zones else max(z.zone_num for z in self.proximity_zones)+1
        halls_text = str(anchor.main_hall_number) if anchor.main_hall_number is not None else ""
        dlg = ProximityZoneDialog(
            anchor_id=anchor.number,
            zone_num=default,
            dist_in=1.0,
            dist_out=0.0,
            bound=anchor.bound_explicit,
            halls=halls_text,
            blist="",
            audio_data=None,
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            return dlg.values()
        return None

    # Locking
    def lock_objects(self):
        dlg = LockDialog(self.lock_halls, self.lock_zones, self.lock_anchors, self)
        if dlg.exec() == QDialog.Accepted:
            prev_state = self.capture_state()
            self.lock_halls, self.lock_zones, self.lock_anchors = dlg.values()
            self.apply_lock_flags()
            self.push_undo_state(prev_state)
    def apply_lock_flags(self):
        for h in self.halls: h.setFlag(QGraphicsItem.ItemIsMovable, not self.lock_halls)
        for h in self.halls:
            for ch in h.childItems():
                if isinstance(ch,RectZoneItem):
                    ch.setFlag(QGraphicsItem.ItemIsMovable, not self.lock_zones)
        for a in self.anchors: a.setFlag(QGraphicsItem.ItemIsMovable, not self.lock_anchors)

    # PDF export
    def save_to_pdf(self):
        fp,_ = choose_save_file(self, "Сохранить в PDF", get_last_used_directory(), "PDF files (*.pdf)")
        if not fp: return
        writer = QPdfWriter(fp); writer.setPageSize(QPageSize(QPageSize.A4)); writer.setResolution(300)
        painter = QPainter(writer); self.scene.render(painter); painter.end()
        QMessageBox.information(self, "PDF сохранён", "PDF успешно сохранён.")

    # Calibration
    def perform_calibration(self):
        if not self.scene.pixmap:
            QMessageBox.warning(self, "Ошибка", "Сначала загрузите изображение!"); return
        confirm_text = (
            "Для калибровки  координатной сетки необходимо будет указать на плане 2 точки, "
            "обозначив отрезок известной длины. После этого задать реальную длину отрезка в см. "
            "Продолжить?"
        )
        reply = QMessageBox.question(
            self,
            "Калибровка",
            confirm_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self.set_mode("calibrate")
        self.statusBar().showMessage("Укажите 2 точки на плане для обозначения отрезка известной длины")
    def resnap_objects(self):
        step = self.scene.pixel_per_cm_x * self.scene.grid_step_cm
        for h in self.halls:
            p = h.pos(); h.setPos(round(p.x()/step)*step, round(p.y()/step)*step)
        for a in self.anchors:
            p = a.scenePos(); a.setPos(round(p.x()/step)*step, round(p.y()/step)*step)
        self.populate_tree(); self.statusBar().showMessage("Координаты пересчитаны.")

    # Selection sync
    def on_scene_selection_changed(self):
        try: items = self.scene.selectedItems()
        except: return
        if items:
            self.last_selected_items = items
            for it in items:
                if hasattr(it, 'tree_item') and it.tree_item:
                    it.tree_item.setSelected(True)
        else:
            for it in self.last_selected_items:
                if hasattr(it, 'tree_item') and it.tree_item:
                    it.tree_item.setSelected(True)

    def update_tree_selection(self):
        try: items = [i for i in self.scene.items() if i.isSelected()]
        except: return
        if items:
            self.last_selected_items = items
            def clear(n):
                n.setSelected(False)
                for i in range(n.childCount()): clear(n.child(i))
            for i in range(self.tree.topLevelItemCount()): clear(self.tree.topLevelItem(i))
            for it in items:
                if hasattr(it, 'tree_item') and it.tree_item:
                    it.tree_item.setSelected(True)
        else:
            for it in self.last_selected_items:
                if hasattr(it, 'tree_item') and it.tree_item:
                    it.tree_item.setSelected(True)

    # Tree context/double click handlers
    def on_tree_context_menu(self, point: QPoint):
        item = self.tree.itemAt(point)
        if not item: return
        self.handle_tree_item_action(item, self.tree.viewport().mapToGlobal(point))

    def on_tree_item_double_clicked(self, item: QTreeWidgetItem, col: int):
        self.handle_tree_item_action(item, QCursor.pos())

    def handle_tree_item_action(self, item: QTreeWidgetItem, global_pos: QPoint):
        data = item.data(0, Qt.UserRole)
        if not data: return
        tp = data.get("type")
        if tp == "hall":
            hall = data["ref"]
            if hall and hall.scene(): hall.open_menu(global_pos)
        elif tp == "anchor":
            anchor = data["ref"]
            if anchor and anchor.scene(): anchor.open_menu(global_pos)
        elif tp == "zone_group":
            zones = data["ref"]  # list of RectZoneItem
            zones = [z for z in zones if z.scene() is not None]
            if not zones: return
            if len(zones) == 1:
                zones[0].open_menu(global_pos)
                return
            # submenu to choose which zone in group
            menu = QMenu()
            for z in zones:
                label = f'Зона {z.zone_num} ({z.get_display_type()})'
                act = menu.addAction(label)
                act.triggered.connect(lambda checked=False, z=z: z.open_menu(global_pos))
            menu.exec(global_pos)
        elif tp == "proximity_zone":
            zone = data.get("ref")
            if zone and hasattr(zone, 'open_menu'):
                zone.open_menu(global_pos)

    # Misc
    def handle_wheel_event(self, event):
        factor = 1.2 if event.angleDelta().y()>0 else 1/1.2
        self.view.scale(factor, factor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            items = list(self.scene.selectedItems())
            if not items:
                return
            prev_state = self.capture_state()
            changed = False
            for it in items:
                if isinstance(it, RectZoneItem):
                    hall = it.parentItem()
                    if hall:
                        others = [z for z in hall.childItems() if isinstance(z, RectZoneItem) and z.zone_num == it.zone_num and z is not it]
                        if not others:
                            hall.zone_audio_tracks.pop(it.zone_num, None)
                if isinstance(it,HallItem) and it in self.halls:
                    self.halls.remove(it)
                    changed = True
                elif isinstance(it, AnchorItem) and it in self.anchors:
                    for zone in list(self.proximity_zones):
                        if zone.anchor is it:
                            self.proximity_zones.remove(zone)
                            self.scene.removeItem(zone)
                    self.anchors.remove(it)
                    changed = True
                elif isinstance(it, ProximityZoneItem) and it in self.proximity_zones:
                    self.proximity_zones.remove(it)
                    changed = True
                else:
                    changed = changed or isinstance(it, RectZoneItem)
                self.scene.removeItem(it)
            if changed:
                self.populate_tree()
                self.push_undo_state(prev_state)
            return
        else:
            super().keyPressEvent(event)

    def populate_tracks_table(self):
        panel = getattr(self, "tracks_panel", None)
        if panel is None:
            return
        panel.refresh()

    def populate_tree(self):
        self.last_selected_items = []
        self.tree.clear()
        # halls
        for h in self.halls:
            wm = h.rect().width()/(self.scene.pixel_per_cm_x*100)
            hm = h.rect().height()/(self.scene.pixel_per_cm_x*100)
            rt = (f'Зал {h.number} "{h.name}" ({wm:.1f} x {hm:.1f} м)'
                  if h.name.strip() else f'Зал {h.number} ({wm:.1f} x {hm:.1f} м)')
            hi = QTreeWidgetItem([rt]); h.tree_item = hi; self.tree.addTopLevelItem(hi)
            hi.setData(0, Qt.UserRole, {"type":"hall","ref":h})

            # anchors under hall
            for a in self.anchors:
                if a.main_hall_number==h.number or h.number in a.extra_halls:
                    lp = h.mapFromScene(a.scenePos())
                    xm = fix_negative_zero(round(lp.x()/(self.scene.pixel_per_cm_x*100),1))
                    ym = fix_negative_zero(round((h.rect().height()-lp.y())/(self.scene.pixel_per_cm_x*100),1))
                    at = f'Якорь {a.number} (x={xm} м, y={ym} м, z={fix_negative_zero(round(a.z/100,1))} м)'
                    ai = QTreeWidgetItem([at]); a.tree_item = ai; hi.addChild(ai)
                    ai.setData(0, Qt.UserRole, {"type":"anchor","ref":a})

            for z in self.proximity_zones:
                halls = z.halls or ([z.anchor.main_hall_number] if z.anchor else [])
                if h.number not in halls:
                    continue
                info = f"Зона {z.zone_num} (якорь {z.anchor.number}, вход {z.dist_in} м, выход {z.dist_out} м)"
                if z.bound:
                    info += " [переходная]"
                if z.blacklist:
                    info += f"; ЧС: {', '.join(str(x) for x in z.blacklist)}"
                zi = QTreeWidgetItem([info]); z.tree_item = zi; hi.addChild(zi)
                zi.setData(0, Qt.UserRole, {"type": "proximity_zone", "ref": z})

            # zones grouped by num
            zones_by_num = {}
            for ch in h.childItems():
                if isinstance(ch,RectZoneItem):
                    zones_by_num.setdefault(ch.zone_num, []).append(ch)

            for num, zlist in zones_by_num.items():
                # compose one-line text as before
                default = {"x":0,"y":0,"w":0,"h":0,"angle":0}
                enter = default.copy(); exitz = default.copy(); bound = False
                for z in zlist:
                    data = z.get_export_data()
                    if z.zone_type in ("Входная зона","Переходная"):
                        enter = data
                    if z.zone_type == "Выходная зона":
                        exitz = data
                    if z.zone_type == "Переходная":
                        bound = True
                zt = (f"Зона {num}: enter: x = {enter['x']} м, y = {enter['y']} м, "
                      f"w = {enter['w']} м, h = {enter['h']} м, angle = {enter['angle']}°; "
                      f"exit: x = {exitz['x']} м, y = {exitz['y']} м, "
                      f"w = {exitz['w']} м, h = {exitz['h']} м, angle = {exitz['angle']}°")
                zi = QTreeWidgetItem([zt]); hi.addChild(zi)
                # link every zone to the same item? Keep mapping via UserRole
                zi.setData(0, Qt.UserRole, {"type":"zone_group","ref":zlist})
                # also set back-reference for sync highlighting (any zone in this group will highlight this row)
                for z in zlist: z.tree_item = zi

            hi.setExpanded(True)

        self.populate_tracks_table()

    def set_mode(self, mode):
        if not self.grid_calibrated and mode!="calibrate":
            QMessageBox.information(self,"Внимание","Сначала выполните калибровку!"); return
        self.add_mode = mode; self.temp_start_point = None; self.current_hall_for_zone = None
        msgs = {
            "hall":"Выделите зал.",
            "anchor":"Кликните в зал.",
            "zone":"Выделите зону.",
            "proximity_zone": "Укажите якорь для привязки зоны.",
            "calibrate":"Укажите 2 точки."
        }
        self.statusBar().showMessage(msgs.get(mode,""))

    def _has_active_project(self) -> bool:
        pixmap = getattr(self.scene, "pixmap", None)
        if pixmap is not None and not pixmap.isNull():
            return True
        return bool(self.halls or self.anchors)

    def _has_unsaved_changes(self) -> bool:
        if not self._has_active_project():
            return False
        current_state = self.capture_state()
        if self._saved_state_snapshot is None:
            return bool(
                current_state.get("image_data")
                or current_state.get("halls")
                or current_state.get("anchors")
            )
        return current_state != self._saved_state_snapshot

    def _mark_state_as_saved(self):
        self._saved_state_snapshot = self.capture_state()

    def restore_saved_project_snapshot(self) -> bool:
        if self._saved_state_snapshot is None:
            return True
        try:
            self.restore_state(copy.deepcopy(self._saved_state_snapshot))
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось восстановить последнее сохранённое состояние:\n{exc}")
            return False

    def _confirm_save_discard(self, question: str) -> bool:
        if not self._has_unsaved_changes():
            return True
        reply = QMessageBox.question(
            self,
            "Сохранить проект",
            question,
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Save:
            return self.save_project()
        discarded = self.restore_saved_project_snapshot()
        if discarded:
            self._sync_auxiliary_configs_from_current_state(show_errors=False)
        return discarded

    def _confirm_save_before_new_project(self) -> bool:
        if not self._has_active_project():
            return True
        return self._confirm_save_discard("Сохранить текущий проект перед созданием нового?")

    def _confirm_save_before_load(self) -> bool:
        if not self._has_active_project():
            return True
        return self._confirm_save_discard("Сохранить текущий проект перед загрузкой другого?")

    def _request_new_project_destination(self):
        default_name = self.project_name.strip() or "project"
        name, ok = QInputDialog.getText(
            self,
            "Новый проект",
            "Введите имя проекта:",
            text=default_name,
        )
        if not ok:
            return None
        project_name = name.strip()
        if not project_name:
            QMessageBox.warning(self, "Новый проект", "Имя проекта не может быть пустым.")
            return None

        folder = choose_directory(
            self,
            "Выберите папку для сохранения проекта",
            os.path.dirname(self.current_project_file) if self.current_project_file else get_last_used_directory(),
        )
        if not folder:
            return None

        project_file = os.path.join(folder, f"{project_name}.proj")
        return project_name, project_file

    def open_image(self):
        if not self._confirm_save_before_new_project():
            return

        requested = self._request_new_project_destination()
        if not requested:
            return
        project_name, project_file = requested

        message = (
            "Для создания нового проекта загрузите план помещения в формате jpg, png, bmp, "
            "после чего выполните калибровку координатной сетки, указав на плане 2 точки, "
            "образующие отрезок известной длины. Продолжить?"
        )
        reply = QMessageBox.question(
            self,
            "Новый проект",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        fp, _ = choose_open_file(
            self,
            "Выбор плана помещения",
            get_last_used_directory(),
            "Изображения (*.png *.jpg *.bmp)",
        )
        if not fp:
            return
        pix = QPixmap(fp)
        if pix.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить.")
            return

        try:
            self._ensure_project_paths(project_file)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось подготовить структуру проекта:\n{exc}")
            return

        prev_state = self.capture_state()
        self.scene.clear(); self.halls.clear(); self.anchors.clear(); self.proximity_zones.clear()
        self.unmatched_audio_files = {}
        self.scene.pixmap = None
        self._reset_background_cache()
        self.scene.set_background_image(pix)
        self.grid_calibrated = False
        self.current_project_file = os.path.abspath(project_file)
        remember_last_used_path(self.current_project_file)
        self.project_name = project_name
        self._update_window_title()
        self._saved_state_snapshot = None
        self.statusBar().showMessage("Калибровка: укажите 2 точки")
        self.set_mode("calibrate")
        self.push_undo_state(prev_state)

    def _collect_project_data(self):
        def strip_audio_binary(audio_info):
            if not isinstance(audio_info, dict):
                return None
            cleaned = {}
            for key, value in audio_info.items():
                if key == "data":
                    continue
                if key == "secondary":
                    cleaned[key] = strip_audio_binary(value)
                else:
                    cleaned[key] = copy.deepcopy(value)
            return cleaned

        buf_data = ""
        if self.scene.pixmap:
            buf = QBuffer(); buf.open(QBuffer.WriteOnly)
            self.scene.pixmap.save(buf,"PNG")
            buf_data = buf.data().toBase64().data().decode()
        data = {
            "project_name": self.project_name,
            "image_data": buf_data,
            "pixel_per_cm_x": self.scene.pixel_per_cm_x,
            "pixel_per_cm_y": self.scene.pixel_per_cm_y,
            "grid_step_cm": self.scene.grid_step_cm,
            "lock_halls": self.lock_halls,
            "lock_zones": self.lock_zones,
            "lock_anchors": self.lock_anchors,
            "unmatched_audio_files": copy.deepcopy(self.unmatched_audio_files),
            "halls": [], "anchors": [], "proximity_zones": []
        }
        for h in self.halls:
            hd = {
                "num": h.number, "name": h.name,
                "x_px": h.pos().x(), "y_px": h.pos().y(),
                "w_px": h.rect().width(), "h_px": h.rect().height(),
                "extra_tracks": list(h.extra_tracks),
            }
            if h.audio_settings:
                hd["audio"] = strip_audio_binary(h.audio_settings)
            if h.zone_audio_tracks:
                hd["zone_audio"] = {str(k): strip_audio_binary(v) for k, v in h.zone_audio_tracks.items()}
            zs = []
            for ch in h.childItems():
                if isinstance(ch,RectZoneItem):
                    zs.append({
                        "zone_num": ch.zone_num,
                        "zone_type": ch.zone_type,
                        "zone_angle": ch.zone_angle,
                        "bottom_left_x": ch.pos().x(),
                        "bottom_left_y": ch.pos().y(),
                        "w_px": ch.rect().width(),
                        "h_px": ch.rect().height()
                    })
            hd["zones"] = zs; data["halls"].append(hd)
        for a in self.anchors:
            ad = {
                "number": a.number, "z": a.z,
                "x": a.scenePos().x(), "y": a.scenePos().y(),
                "main_hall": a.main_hall_number,
                "extra_halls": a.extra_halls
            }
            if a.bound_explicit:
                ad["bound"] = True
            data["anchors"].append(ad)
        for z in self.proximity_zones:
            zd = {
                "zone_num": z.zone_num,
                "anchor_id": z.anchor.number,
                "dist_in": z.dist_in,
                "dist_out": z.dist_out,
                "bound": z.bound,
                "halls": z.halls,
                "blacklist": z.blacklist,
                "audio": strip_audio_binary(z.audio_info) if z.audio_info else None,
            }
            data["proximity_zones"].append(zd)
        return data

    def _save_project_file(self, fp, data):
        try:
            self._ensure_project_paths(fp)
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
            return False

        self.current_project_file = os.path.abspath(fp)
        remember_last_used_path(self.current_project_file)
        rooms_json_text, tracks_data = self._prepare_export_payload()
        self._merge_unmatched_audio_files_into_tracks_data(tracks_data)
        self._merge_existing_tracks_metadata(tracks_data)
        if not self._write_auxiliary_configs(rooms_json_text, tracks_data):
            return False

        self.statusBar().showMessage("Проект успешно сохранён.", 5000)
        return True

    def show_project_properties_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Свойства проекта")
        form = QFormLayout(dialog)

        name_edit = QLineEdit(dialog)
        name_edit.setPlaceholderText("Имя проекта (опционально)")
        if self.project_name:
            name_edit.setText(self.project_name)
        form.addRow("Имя:", name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        self.project_name = name_edit.text().strip()
        self._update_window_title()

    def save_project(self):
        target = self.current_project_file
        if not target:
            requested = self._request_new_project_destination()
            if not requested:
                return False
            requested_name, requested_file = requested
            self.project_name = requested_name
            self._update_window_title()
            target = requested_file
        data = self._collect_project_data()
        if self._save_project_file(target, data):
            self.current_project_file = os.path.abspath(target)
            self._mark_state_as_saved()
            return True
        return False

    def save_project_as(self):
        requested = self._request_new_project_destination()
        if not requested:
            return False
        requested_name, fp = requested
        self.project_name = requested_name
        self._update_window_title()
        data = self._collect_project_data()
        if self._save_project_file(fp, data):
            self.current_project_file = os.path.abspath(fp)
            self._mark_state_as_saved()
            return True
        return False

    def show_import_menu(self):
        menu = QMenu(self)
        rooms_action = menu.addAction("Импортировать объекты")
        tracks_action = menu.addAction("Импортировать аудиофайлы")
        global_pos = QCursor.pos()
        if not self.rect().contains(self.mapFromGlobal(global_pos)):
            global_pos = self.mapToGlobal(self.rect().center())
        chosen = menu.exec(global_pos)
        if chosen == rooms_action:
            self.import_rooms_config()
        elif chosen == tracks_action:
            self.import_tracks_config()

    def show_export_menu(self):
        menu = QMenu(self)
        rooms_action = menu.addAction("Экспортировать объекты")
        tracks_action = menu.addAction("Экспортировать аудиофайлы")
        global_pos = QCursor.pos()
        if not self.rect().contains(self.mapFromGlobal(global_pos)):
            global_pos = self.mapToGlobal(self.rect().center())
        chosen = menu.exec(global_pos)
        if chosen == rooms_action:
            self.export_rooms_config()
        elif chosen == tracks_action:
            self.export_tracks_config()

    def import_rooms_config(self):
        fp, _ = choose_open_file(self, "Импорт объектов", get_last_used_directory(), "JSON файлы (*.json)")
        if not fp:
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")
            return
        rooms = data.get("rooms") if isinstance(data, dict) else None
        if not isinstance(rooms, list):
            QMessageBox.warning(self, "Ошибка", "Выбранный файл не соответствует формату rooms.json.")
            return

        ppcm = self.scene.pixel_per_cm_x or 0.0
        if ppcm <= 0:
            QMessageBox.warning(self, "Ошибка", "Перед импортом объектов выполните калибровку масштаба.")
            return

        prev_state = self.capture_state()
        hall_map = {h.number: h for h in self.halls}
        zone_audio_backup = {h.number: copy.deepcopy(h.zone_audio_tracks) for h in self.halls if h.zone_audio_tracks}
        existing_zone_count = sum(1 for h in self.halls for ch in h.childItems() if isinstance(ch, RectZoneItem))
        existing_anchor_count = len(self.anchors)
        changed = bool(existing_zone_count or existing_anchor_count)

        for hall in self.halls:
            for child in list(hall.childItems()):
                if isinstance(child, RectZoneItem):
                    child.scene().removeItem(child)
            hall.zone_audio_tracks.clear()
        for anchor in list(self.anchors):
            self.scene.removeItem(anchor)
        self.anchors.clear()

        missing_halls: list[int] = []
        for room in rooms:
            if not isinstance(room, dict):
                continue
            try:
                hall_number = int(room.get("num"))
            except (TypeError, ValueError):
                continue
            hall = hall_map.get(hall_number)
            if hall is None:
                missing_halls.append(hall_number)
                continue

            width = room.get("width")
            height = room.get("height")
            extra_tracks_raw = room.get("extra_tracks")
            hall.extra_tracks = normalize_int_list(extra_tracks_raw)
            try:
                width_m = float(width)
                height_m = float(height)
            except (TypeError, ValueError):
                width_m = height_m = None
            if width_m and width_m > 0 and height_m and height_m > 0:
                w_px = width_m * ppcm * 100
                h_px = height_m * ppcm * 100
                hall.prepareGeometryChange()
                hall.setRect(0, 0, w_px, h_px)
                hall.setZValue(-w_px * h_px)
                changed = True

            created_zone_numbers: set[int] = set()

            def add_zone(section: dict | None, zone_type: str) -> bool:
                if not isinstance(section, dict):
                    return False
                try:
                    w_m = float(section.get("w", 0))
                    h_m = float(section.get("h", 0))
                    x_m = float(section.get("x", 0))
                    y_m = float(section.get("y", 0))
                    angle = float(section.get("angle", 0))
                except (TypeError, ValueError):
                    return False
                if w_m <= 0 or h_m <= 0:
                    return False
                w_px = w_m * ppcm * 100
                h_px = h_m * ppcm * 100
                px = x_m * ppcm * 100
                py = hall.rect().height() - y_m * ppcm * 100
                RectZoneItem(QPointF(px, py), w_px, h_px, zone_number, zone_type, angle, hall)
                return True

            zones = room.get("zones") if isinstance(room.get("zones"), list) else []
            for zone in zones:
                if not isinstance(zone, dict):
                    continue
                try:
                    zone_number = int(zone.get("num"))
                except (TypeError, ValueError):
                    continue
                bound = bool(zone.get("bound", False))
                if bound:
                    if add_zone(zone.get("enter"), "Переходная"):
                        created_zone_numbers.add(zone_number)
                        changed = True
                else:
                    entered = add_zone(zone.get("enter"), "Входная зона")
                    exited = add_zone(zone.get("exit"), "Выходная зона")
                    if entered or exited:
                        created_zone_numbers.add(zone_number)
                        changed = True

            anchors = room.get("anchors") if isinstance(room.get("anchors"), list) else []
            for anchor_data in anchors:
                if not isinstance(anchor_data, dict):
                    continue
                try:
                    anchor_id = int(anchor_data.get("id"))
                    x_m = float(anchor_data.get("x", 0))
                    y_m = float(anchor_data.get("y", 0))
                    z_m = float(anchor_data.get("z", 0))
                except (TypeError, ValueError):
                    continue
                px = x_m * ppcm * 100
                py = hall.rect().height() - y_m * ppcm * 100
                scene_pos = hall.mapToScene(QPointF(px, py))
                anchor_item = AnchorItem(scene_pos.x(), scene_pos.y(), anchor_id, main_hall_number=hall.number, scene=self.scene)
                anchor_item.z = int(round(z_m * 100))
                if anchor_data.get("bound"):
                    anchor_item.bound = True
                    anchor_item.bound_explicit = True
                self.scene.addItem(anchor_item)
                self.anchors.append(anchor_item)
                changed = True

            saved_audio = zone_audio_backup.get(hall_number, {})
            if saved_audio:
                for zone_id in created_zone_numbers:
                    audio_info = saved_audio.get(zone_id)
                    if audio_info:
                        hall.zone_audio_tracks[zone_id] = copy.deepcopy(audio_info)

        if missing_halls:
            missing_str = ", ".join(str(n) for n in sorted(set(missing_halls)))
            QMessageBox.warning(self, "Предупреждение", f"В проекте отсутствуют залы: {missing_str}. Объекты этих залов не были импортированы.")

        self.populate_tree()
        if changed or rooms:
            self.push_undo_state(prev_state)
        self.statusBar().showMessage("Импорт объектов завершён.", 5000)
        QMessageBox.information(self, "Импорт", "Импорт объектов завершён.")

    def _build_audio_info_from_track(self, track: dict, file_sizes: dict[str, int] | None = None, file_crc32: dict[str, str] | None = None):
        filename = track.get("audio")
        if not filename:
            return None
        try:
            base_id = int(track.get("id"))
        except (TypeError, ValueError):
            base_id = None
        size_bytes = 0
        if isinstance(file_sizes, dict) and filename in file_sizes:
            try:
                size_bytes = int(file_sizes.get(filename, 0) or 0)
            except (TypeError, ValueError):
                size_bytes = 0
        if size_bytes <= 0:
            try:
                size_bytes = int(track.get("size") or 0)
            except (TypeError, ValueError):
                size_bytes = 0
        extras = []
        for value in track.get("multi_id", []) or []:
            try:
                extra_id = int(value)
            except (TypeError, ValueError):
                continue
            if base_id is not None and extra_id == base_id:
                continue
            extras.append(extra_id)
        info = {
            "filename": filename,
            "data": "",
            "duration_ms": int(track.get("duration_ms", 0) or 0),
            "size": size_bytes,
            "extra_ids": extras,
            "interruptible": bool(track.get("term", True)),
            "reset": bool(track.get("reset", False)),
            "play_once": bool(track.get("play_once", False))
        }
        if isinstance(file_crc32, dict):
            crc_value = file_crc32.get(filename)
            if isinstance(crc_value, str) and crc_value:
                info["crc32"] = crc_value
        name_value = track.get("name")
        if isinstance(name_value, str) and name_value.strip():
            info["display_name"] = name_value.strip()
        if track.get("audio2"):
            sec_size = 0
            if isinstance(file_sizes, dict) and track["audio2"] in file_sizes:
                try:
                    sec_size = int(file_sizes.get(track["audio2"], 0) or 0)
                except (TypeError, ValueError):
                    sec_size = 0
            info["secondary"] = {
                "filename": track["audio2"],
                "data": "",
                "duration_ms": 0,
                "size": sec_size
            }
            if isinstance(file_crc32, dict):
                secondary_crc = file_crc32.get(track["audio2"])
                if isinstance(secondary_crc, str) and secondary_crc:
                    info["secondary"]["crc32"] = secondary_crc
        return info

    def import_tracks_config(self):
        fp, _ = choose_open_file(self, "Импорт аудиофайлов", get_last_used_directory(), "JSON файлы (*.json)")
        if not fp:
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")
            return
        tracks = data.get("tracks") if isinstance(data, dict) else None
        if not isinstance(tracks, list):
            QMessageBox.warning(self, "Ошибка", "Выбранный файл не соответствует формату tracks.json.")
            return

        file_sizes: dict[str, int] = {}
        file_crc32: dict[str, str] = {}
        files_section = data.get("files") if isinstance(data, dict) else None
        if isinstance(files_section, list):
            for entry in files_section:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    continue
                try:
                    size_value = int(entry.get("size") or 0)
                except (TypeError, ValueError):
                    continue
                file_sizes[name] = max(size_value, file_sizes.get(name, 0), 0)
                crc_value = str(entry.get("crc32", "") or "").strip().lower()
                if crc_value:
                    file_crc32[name] = crc_value

        prev_state = self.capture_state()
        hall_map = {h.number: h for h in self.halls}
        had_audio = any(h.audio_settings or h.zone_audio_tracks for h in self.halls) or any(pz.audio_info for pz in self.proximity_zones)
        for hall in self.halls:
            hall.audio_settings = None
            hall.zone_audio_tracks.clear()
        for pz in self.proximity_zones:
            pz.audio_info = None

        changed = had_audio
        unmatched_halls: set[int] = set()
        unmatched_zones: set[int] = set()
        proximity_by_id: dict[int, list[ProximityZoneItem]] = {}
        for pz in self.proximity_zones:
            proximity_by_id.setdefault(pz.zone_num, []).append(pz)

        for entry in tracks:
            if not isinstance(entry, dict):
                continue
            try:
                track_id = int(entry.get("id"))
            except (TypeError, ValueError):
                continue
            audio_info = self._build_audio_info_from_track(entry, file_sizes, file_crc32)
            if not audio_info:
                continue
            target_hall = None
            room_id = entry.get("room_id")
            if isinstance(room_id, (int, float)):
                target_hall = hall_map.get(int(room_id))
            if target_hall is None:
                target_hall = hall_map.get(track_id)
            if entry.get("hall"):
                if target_hall is None:
                    unmatched_halls.add(track_id)
                    continue
                target_hall.audio_settings = audio_info
                changed = True
                continue
            candidates = [h for h in self.halls if any(isinstance(ch, RectZoneItem) and ch.zone_num == track_id for ch in h.childItems())]
            if target_hall is not None:
                candidates = [h for h in candidates if h is target_hall]

            assigned = False
            if len(candidates) == 1:
                candidates[0].zone_audio_tracks[track_id] = audio_info
                assigned = True
            else:
                prox_candidates = proximity_by_id.get(track_id, [])
                if target_hall is not None:
                    prox_candidates = [
                        pz for pz in prox_candidates
                        if target_hall.number in (pz.halls or ([pz.anchor.main_hall_number] if pz.anchor else []))
                    ]
                elif isinstance(room_id, (int, float)):
                    prox_candidates = [
                        pz for pz in prox_candidates
                        if int(room_id) in (pz.halls or ([pz.anchor.main_hall_number] if pz.anchor else []))
                    ]
                if len(prox_candidates) == 1:
                    prox_candidates[0].audio_info = audio_info
                    assigned = True

            if assigned:
                changed = True
            else:
                unmatched_zones.add(track_id)

        warnings = []
        if unmatched_halls:
            hall_list = ", ".join(str(x) for x in sorted(unmatched_halls))
            warnings.append(f"Залы: {hall_list}")
        if unmatched_zones:
            zone_list = ", ".join(str(x) for x in sorted(unmatched_zones))
            warnings.append(f"Зоны: {zone_list}")
        if warnings:
            QMessageBox.warning(self, "Предупреждение", "Не найдены объекты для следующих идентификаторов:\n" + "\n".join(warnings))

        self.populate_tree()
        if changed or tracks:
            self.push_undo_state(prev_state)
        self.statusBar().showMessage("Импорт аудиофайлов завершён.", 5000)
        QMessageBox.information(self, "Импорт", "Импорт аудиофайлов завершён.")

    def refresh_audio_from_content(self):
        if not self.current_project_file:
            QMessageBox.warning(self, "Обновить аудио", "Сначала сохраните или создайте проект.")
            return
        if not self._ensure_project_layout_for_current_file():
            return

        reply = QMessageBox.question(
            self,
            "Обновить аудио",
            "Сканировать папку content и автоматически назначить MP3-файлы по номеру трека?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        hall_by_num = {h.number: h for h in self.halls}
        zone_halls: dict[int, list[HallItem]] = {}
        for hall in self.halls:
            for child in hall.childItems():
                if isinstance(child, RectZoneItem):
                    zone_halls.setdefault(child.zone_num, []).append(hall)

        proximity_by_id: dict[int, list[ProximityZoneItem]] = {}
        for pz in self.proximity_zones:
            proximity_by_id.setdefault(pz.zone_num, []).append(pz)

        prev_state = self.capture_state()
        changed = False
        assigned_halls = 0
        assigned_zones = 0
        unmatched: list[str] = []
        unmatched_files: dict[str, dict] = {}

        for audio_path in self._iter_project_audio_files():
            try:
                info = load_audio_file_info(audio_path)
            except ValueError:
                continue
            filename = str(info.get("filename", "") or "")
            track_id = extract_track_id(filename)

            if track_id <= 0:
                data_b64 = info.get("data", "")
                crc32_hex = ""
                if data_b64:
                    try:
                        raw_bytes = base64.b64decode(data_b64.encode("ascii"))
                        crc = 0
                        for offset in range(0, len(raw_bytes), 4096):
                            crc = zlib.crc32(raw_bytes[offset:offset + 4096], crc)
                        crc32_hex = f"{crc & 0xFFFFFFFF:08x}"
                    except Exception:
                        crc32_hex = ""
                unmatched_files[filename] = {
                    "name": filename,
                    "size": int(info.get("size") or 0),
                    "crc32": crc32_hex,
                }
                unmatched.append(filename)
                continue

            hall_target = hall_by_num.get(track_id)
            if hall_target is not None:
                hall_target.audio_settings = self._merge_audio_info_preserving_track_settings(hall_target.audio_settings, info)
                assigned_halls += 1
                changed = True
                continue

            zone_candidates = zone_halls.get(track_id, [])
            if len(zone_candidates) == 1:
                existing_zone_info = zone_candidates[0].zone_audio_tracks.get(track_id)
                zone_candidates[0].zone_audio_tracks[track_id] = self._merge_audio_info_preserving_track_settings(existing_zone_info, info)
                assigned_zones += 1
                changed = True
                continue

            prox_candidates = proximity_by_id.get(track_id, [])
            if len(prox_candidates) == 1:
                prox_candidates[0].audio_info = self._merge_audio_info_preserving_track_settings(prox_candidates[0].audio_info, info)
                assigned_zones += 1
                changed = True
                continue

            unmatched_name = filename
            data_b64 = info.get("data", "")
            crc32_hex = ""
            if data_b64:
                try:
                    raw_bytes = base64.b64decode(data_b64.encode("ascii"))
                    crc = 0
                    for offset in range(0, len(raw_bytes), 4096):
                        crc = zlib.crc32(raw_bytes[offset:offset + 4096], crc)
                    crc32_hex = f"{crc & 0xFFFFFFFF:08x}"
                except Exception:
                    crc32_hex = ""
            unmatched_files[unmatched_name] = {
                "name": unmatched_name,
                "size": int(info.get("size") or 0),
                "crc32": crc32_hex,
            }
            unmatched.append(unmatched_name)

        self.populate_tree()
        self.populate_tracks_table()
        if changed:
            self.push_undo_state(prev_state)

        rooms_json_text, tracks_data = self._prepare_export_payload()
        self.unmatched_audio_files = self._normalize_unmatched_audio_files(unmatched_files)
        self._merge_unmatched_audio_files_into_tracks_data(tracks_data)
        self._merge_existing_tracks_metadata(tracks_data)
        if not self._write_auxiliary_configs(rooms_json_text, tracks_data):
            return

        message_lines = [
            f"Назначено треков залам: {assigned_halls}",
            f"Назначено треков зонам: {assigned_zones}",
            f"Файл tracks.json обновлён: {self._tracks_json_path()}",
        ]
        if unmatched:
            message_lines.append("Без соответствия: " + ", ".join(unmatched))
        QMessageBox.information(self, "Обновить аудио", "\n".join(message_lines))
        self.statusBar().showMessage("Обновление аудио завершено.", 5000)


    def load_project(self):
        if not self._confirm_save_before_load():
            return
        fp,_ = choose_open_file(self,"Загрузить проект", get_last_used_directory(),"*.proj")
        if not fp: return
        prev_state = self.capture_state()
        try:
            with open(fp,"r",encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self,"Ошибка",f"Ошибка чтения:\n{e}"); return
        self.scene.clear(); self.halls.clear(); self.anchors.clear(); self.proximity_zones.clear()
        self.scene.pixmap = None
        self._reset_background_cache()
        buf_data = data.get("image_data","")
        if buf_data:
            ba = QByteArray.fromBase64(buf_data.encode())
            pix = QPixmap(); pix.loadFromData(ba,"PNG")
            self.scene.set_background_image(pix)
        self.scene.pixel_per_cm_x = data.get("pixel_per_cm_x",1.0)
        self.scene.pixel_per_cm_y = data.get("pixel_per_cm_y",1.0)
        self.scene.grid_step_cm   = data.get("grid_step_cm",20.0)
        self.lock_halls   = data.get("lock_halls",False)
        self.lock_zones   = data.get("lock_zones",False)
        self.lock_anchors = data.get("lock_anchors",False)
        self.project_name = data.get("project_name", "") if isinstance(data.get("project_name", ""), str) else ""
        self.unmatched_audio_files = self._normalize_unmatched_audio_files(data.get("unmatched_audio_files"))
        self._update_window_title()
        self.grid_calibrated = True
        for hd in data.get("halls",[]):
            h = HallItem(
                hd.get("x_px",0), hd.get("y_px",0),
                hd.get("w_px",100), hd.get("h_px",100),
                hd.get("name",""), hd.get("num",0),
                scene=self.scene
            )
            h.audio_settings = hd.get("audio")
            h.extra_tracks = normalize_int_list(hd.get("extra_tracks"))
            zone_audio_raw = hd.get("zone_audio", {})
            if zone_audio_raw:
                h.zone_audio_tracks = {}
                for k, v in zone_audio_raw.items():
                    try:
                        h.zone_audio_tracks[int(k)] = copy.deepcopy(v)
                    except (TypeError, ValueError):
                        continue
            self.scene.addItem(h); self.halls.append(h)
            for zd in hd.get("zones",[]):
                bl = QPointF(zd.get("bottom_left_x",0), zd.get("bottom_left_y",0))
                RectZoneItem(
                    bl, zd.get("w_px",0), zd.get("h_px",0),
                    zd.get("zone_num",0),
                    zd.get("zone_type","Входная зона"),
                    zd.get("zone_angle",0), h
                )
        anchor_map = {}
        for ad in data.get("anchors",[]):
            a = AnchorItem(
                ad.get("x",0), ad.get("y",0),
                ad.get("number",0),
                main_hall_number=ad.get("main_hall"),
                scene=self.scene
            )
            a.z = ad.get("z",0)
            a.extra_halls = ad.get("extra_halls",[])
            if ad.get("bound"):
                a.bound = True
                a.bound_explicit = True
            self.scene.addItem(a); self.anchors.append(a); anchor_map[a.number] = a
        for zd in data.get("proximity_zones", []):
            anchor = anchor_map.get(zd.get("anchor_id"))
            if not anchor:
                continue
            zone = ProximityZoneItem(
                anchor,
                zd.get("zone_num", 0),
                float(zd.get("dist_in", 0.0)),
                float(zd.get("dist_out", 0.0)),
                bool(zd.get("bound", False)),
                list(zd.get("halls", [])),
                list(zd.get("blacklist", [])),
                copy.deepcopy(zd.get("audio")) if zd.get("audio") else None,
            )
            self.proximity_zones.append(zone)
        self.apply_lock_flags(); self.populate_tree()
        self.current_project_file = os.path.abspath(fp)
        remember_last_used_path(self.current_project_file)
        self.project_root_dir = None
        self.project_content_dir = None
        self._ensure_project_layout_for_current_file()
        self.statusBar().showMessage("Проект успешно загружен.", 5000)
        self.push_undo_state(prev_state)
        self._mark_state_as_saved()

    def export_rooms_config(self):
        if self.current_project_file:
            self._sync_auxiliary_configs_from_current_state(show_errors=False)
        fp, _ = choose_save_file(self, "Экспорт объектов", get_last_used_directory(), "JSON файлы (*.json)")
        if not fp:
            return

        rooms_json_text, _ = self._prepare_export_payload()
        try:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(rooms_json_text)
            self.statusBar().showMessage("Экспорт объектов завершён.", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать:\n{e}")

    def export_tracks_config(self):
        if self.current_project_file:
            self._sync_auxiliary_configs_from_current_state(show_errors=False)
        fp, _ = choose_save_file(self, "Экспорт аудиофайлов", os.path.join(get_last_used_directory(), "tracks.json"), "JSON файлы (*.json)")
        if not fp:
            return

        _, tracks_data = self._prepare_export_payload()
        self._merge_unmatched_audio_files_into_tracks_data(tracks_data)
        self._merge_existing_tracks_metadata(tracks_data)
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(tracks_data, f, ensure_ascii=False, indent=4)
            self.statusBar().showMessage("Экспорт аудиофайлов завершён.", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать:\n{e}")

    def upload_config_to_server(self):
        if self.current_project_file:
            self._sync_auxiliary_configs_from_current_state(show_errors=False)
        rooms_json_text, tracks_data = self._prepare_export_payload()
        self._merge_unmatched_audio_files_into_tracks_data(tracks_data)
        self._merge_existing_tracks_metadata(tracks_data)

        upload_mode, mode_ok = QInputDialog.getItem(
            self,
            "Выгрузка на сервер",
            "Что выгружать:",
            ["Проект целиком", "Только конфигурацию"],
            1,
            False,
        )
        if not mode_ok:
            return
        upload_full_project = upload_mode == "Проект целиком"

        dialog = QDialog(self)
        dialog.setWindowTitle("Выгрузка на сервер")
        form_layout = QFormLayout(dialog)

        host_edit = QLineEdit(dialog)
        host_edit.setPlaceholderText("example.com")
        host_edit.setText("178.154.195.218")
        form_layout.addRow("Хост:", host_edit)

        login_edit = QLineEdit(dialog)
        login_edit.setPlaceholderText("user")
        login_edit.setText("radiog")
        form_layout.addRow("Логин:", login_edit)

        target_dir_edit = QLineEdit(dialog)
        target_dir_edit.setPlaceholderText("~/rg_mapper (символ ~ разворачивается в домашний каталог)")
        target_dir_edit.setText("~/headphones")
        form_layout.addRow("Каталог на сервере:", target_dir_edit)

        port_spin = QSpinBox(dialog)
        port_spin.setRange(1, 65535)
        port_spin.setValue(26015)
        form_layout.addRow("Порт:", port_spin)

        password_edit = QLineEdit(dialog)
        password_edit.setEchoMode(QLineEdit.Password)
        password_edit.setPlaceholderText("Пароль для ключа (если требуется)")
        form_layout.addRow("Пароль к ключу:", password_edit)

        key_widget = QWidget(dialog)
        key_layout = QHBoxLayout(key_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_path_edit = QLineEdit(key_widget)
        key_path_edit.setPlaceholderText("Файл ключа из текущей папки")
        app_root = os.path.dirname(os.path.abspath(__file__))
        preferred_key_path = os.path.join(app_root, "id_rsa")
        default_key_path = preferred_key_path if os.path.isfile(preferred_key_path) else None
        if not default_key_path:
            default_key_path = find_default_ssh_key(app_root) or find_default_ssh_key(os.getcwd())
        if default_key_path:
            key_path_edit.setText(default_key_path)
        key_layout.addWidget(key_path_edit)
        browse_button = QPushButton("Обзор…", key_widget)

        def browse_key_file():
            filename, _ = choose_open_file(
                self,
                "Выберите приватный ключ SSH",
                os.path.expanduser("~/.ssh"),
                "Все файлы (*);;OpenSSH ключи (*.pem *.key *.rsa *.ssh)",
            )
            if filename:
                key_path_edit.setText(filename)

        browse_button.clicked.connect(browse_key_file)
        key_layout.addWidget(browse_button)
        form_layout.addRow("Файл ключа:", key_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form_layout.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        host = host_edit.text().strip()
        username = login_edit.text().strip()
        remote_dir = target_dir_edit.text().strip()
        key_path = key_path_edit.text().strip()
        port = port_spin.value()
        passphrase = password_edit.text() or None

        if not host or not username or not key_path:
            QMessageBox.warning(self, "Выгрузка на сервер", "Заполните хост, логин и путь к ключу для подключения.")
            return

        try:
            with open(key_path, "rb") as _key_file:
                _key_file.read(1)
        except Exception as exc:
            QMessageBox.critical(self, "Выгрузка на сервер", f"Не удалось открыть файл ключа:\n{exc}")
            return

        try:
            key_obj = None
            if key_path.lower().endswith(".ppk"):
                import importlib.util
                if importlib.util.find_spec("paramiko.ppk") is not None:
                    from paramiko.ppk import PPKKey as _PPKKey
                    key_obj = _PPKKey.from_file(key_path, password=passphrase)
                elif importlib.util.find_spec("paramiko_ppk") is not None:
                    from paramiko_ppk import PPKKey as _PPKKey  # type: ignore
                    key_obj = _PPKKey.from_file(key_path, password=passphrase)
                else:
                    raise ModuleNotFoundError("Поддержка ключей PPK недоступна. Установите пакет paramiko-ppk.")
            else:
                key_obj = paramiko.RSAKey.from_private_key_file(key_path, password=passphrase)
        except Exception as exc:
            QMessageBox.critical(self, "Выгрузка на сервер", f"Не удалось загрузить SSH-ключ:\n{exc}")
            return

        tracks_json_text = json.dumps(tracks_data, ensure_ascii=False, indent=4)
        rooms_bytes = rooms_json_text.encode("utf-8")
        tracks_bytes = tracks_json_text.encode("utf-8")

        ssh = None
        sftp = None
        normalized_target_directory = ""
        export_folder_name = ""
        upload_results: list[tuple[str, bool, str]] = []

        progress_dialog = QProgressDialog("Подготовка выгрузки...", "Отмена", 0, 100, self)
        progress_dialog.setWindowTitle("Выгрузка на сервер")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)

        bytes_uploaded = 0
        total_bytes_to_upload = 0
        file_index = 0
        total_files_count = 0

        def update_progress(file_label: str):
            percent = int((bytes_uploaded / total_bytes_to_upload) * 100) if total_bytes_to_upload > 0 else 0
            progress_dialog.setValue(min(percent, 100))
            progress_dialog.setLabelText(
                f"Файл {file_index}/{total_files_count}: {file_label}\n"
                f"Прогресс: {bytes_uploaded / (1024 * 1024):.2f} / {total_bytes_to_upload / (1024 * 1024):.2f} МБ"
            )
            QApplication.processEvents()

        def upload_bytes(remote_path: str, payload: bytes, display_name: str):
            nonlocal bytes_uploaded, file_index
            chunk_size = 256 * 1024
            uploaded_for_file = 0
            file_size = len(payload)
            file_index += 1
            update_progress(display_name)
            with sftp.file(remote_path, "wb") as remote_file:
                while uploaded_for_file < file_size:
                    if progress_dialog.wasCanceled():
                        raise RuntimeError("Выгрузка отменена пользователем.")
                    next_chunk = payload[uploaded_for_file:uploaded_for_file + chunk_size]
                    remote_file.write(next_chunk)
                    uploaded_for_file += len(next_chunk)
                    bytes_uploaded += len(next_chunk)
                    update_progress(display_name)
                remote_file.flush()
            upload_results.append((display_name, True, "OK"))

        def upload_local_file(local_path: str, remote_path: str, display_name: str):
            nonlocal bytes_uploaded, file_index
            chunk_size = 256 * 1024
            file_size = os.path.getsize(local_path)
            uploaded_for_file = 0
            file_index += 1
            update_progress(display_name)
            with open(local_path, "rb") as local_stream, sftp.file(remote_path, "wb") as remote_stream:
                while True:
                    if progress_dialog.wasCanceled():
                        raise RuntimeError("Выгрузка отменена пользователем.")
                    chunk = local_stream.read(chunk_size)
                    if not chunk:
                        break
                    remote_stream.write(chunk)
                    uploaded_for_file += len(chunk)
                    bytes_uploaded += len(chunk)
                    update_progress(display_name)
                remote_stream.flush()

            if uploaded_for_file != file_size:
                upload_results.append((display_name, False, "Размер файла не совпал после передачи"))
                raise IOError(f"Файл передан не полностью: {display_name}")
            upload_results.append((display_name, True, "OK"))

        def ensure_remote_dirs(path_value: str):
            normalized = path_value.replace("\\", "/")
            if not normalized:
                return
            parts = [part for part in normalized.split("/") if part]
            current = "/" if normalized.startswith("/") else ""
            for part in parts:
                current = f"{current}/{part}" if current else part
                try:
                    sftp.listdir(current)
                except IOError:
                    sftp.mkdir(current)

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=host, port=port, username=username, pkey=key_obj, allow_agent=False, look_for_keys=False)
            sftp = ssh.open_sftp()

            remote_dir_clean = remote_dir.replace("\\", "/").strip()
            remote_dir_effective = remote_dir_clean
            if remote_dir_effective and remote_dir_effective not in (".", "./"):
                if remote_dir_effective.startswith("~"):
                    try:
                        home_dir = sftp.normalize(".")
                    except IOError:
                        home_dir = sftp.normalize("~")
                    subpath = remote_dir_effective[1:].lstrip("/")
                    remote_dir_effective = posixpath.join(home_dir, subpath) if subpath else home_dir
                ensure_remote_dirs(remote_dir_effective)
                base_dir = sftp.normalize(remote_dir_effective)
            else:
                base_dir = sftp.normalize(".")

            export_folder_name = self._build_remote_export_folder_name()
            target_directory = posixpath.join(base_dir, export_folder_name)
            ensure_remote_dirs(target_directory)
            normalized_target_directory = sftp.normalize(target_directory)

            rooms_remote_path = posixpath.join(normalized_target_directory, "rooms.json")
            tracks_remote_path = posixpath.join(normalized_target_directory, "tracks.json")

            files_to_upload: list[tuple[str, str, int, str, str]] = [
                ("bytes", rooms_remote_path, len(rooms_bytes), "rooms.json", "rooms.json"),
            ]
            if not upload_full_project:
                files_to_upload.append(("bytes", tracks_remote_path, len(tracks_bytes), "tracks.json", "tracks.json"))

            project_file_remote = ""
            local_project_file = ""
            local_root_dir = ""

            if upload_full_project:
                if not self._ensure_project_layout_for_current_file():
                    return
                local_project_file = os.path.abspath(self.current_project_file) if self.current_project_file else ""
                local_root_dir = self._get_effective_project_root_dir()
                if not local_project_file or not local_root_dir or not os.path.isdir(local_root_dir):
                    raise IOError("Не удалось определить структуру локального проекта для полной выгрузки.")

                project_file_remote = posixpath.join(normalized_target_directory, os.path.basename(local_project_file))
                files_to_upload.append((
                    "file",
                    project_file_remote,
                    os.path.getsize(local_project_file),
                    os.path.basename(local_project_file),
                    local_project_file,
                ))

                root_remote_dir = posixpath.join(normalized_target_directory, os.path.basename(local_root_dir))
                ensure_remote_dirs(root_remote_dir)

                for root, _, files in os.walk(local_root_dir):
                    rel_root = os.path.relpath(root, local_root_dir)
                    remote_root = root_remote_dir if rel_root == "." else posixpath.join(root_remote_dir, rel_root.replace("\\", "/"))
                    ensure_remote_dirs(remote_root)
                    for filename in files:
                        local_path = os.path.join(root, filename)
                        remote_path = posixpath.join(remote_root, filename)
                        rel_display = os.path.relpath(local_path, os.path.dirname(local_project_file)).replace("\\", "/")
                        files_to_upload.append(("file", remote_path, os.path.getsize(local_path), rel_display, local_path))

            total_bytes_to_upload = sum(item[2] for item in files_to_upload)
            total_files_count = len(files_to_upload)
            progress_dialog.setMaximum(100)

            for item_type, remote_path, _, display_name, source in files_to_upload:
                self.statusBar().showMessage(f"Загрузка: {display_name}")
                if item_type == "bytes":
                    payload = rooms_bytes if source == "rooms.json" else tracks_bytes
                    upload_bytes(remote_path, payload, display_name)
                else:
                    upload_local_file(source, remote_path, display_name)

            progress_dialog.setValue(100)
            progress_dialog.setLabelText("Выгрузка завершена")
            QApplication.processEvents()

        except Exception as exc:
            upload_results.append(("Общий статус", False, str(exc)))
            QMessageBox.critical(self, "Выгрузка на сервер", f"Ошибка при передаче данных:\n{exc}")
            self.statusBar().showMessage("Ошибка выгрузки конфигурации.", 7000)
            return
        finally:
            progress_dialog.close()
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    pass

        mode_suffix = "Проект целиком" if upload_full_project else "Только конфигурация"
        self.statusBar().showMessage(f"Выгрузка на сервер завершена ({mode_suffix}).", 7000)
        message_text = f"{mode_suffix}: данные успешно переданы на сервер."
        if normalized_target_directory:
            message_text += f" Каталог: {normalized_target_directory}."
        if upload_results:
            success_count = sum(1 for _, ok, _ in upload_results if ok)
            fail_count = sum(1 for _, ok, _ in upload_results if not ok)
            message_text += f"\nФайлов загружено: {success_count}"
            if fail_count:
                message_text += f", ошибок: {fail_count}"
        QMessageBox.information(self, "Выгрузка на сервер", message_text)


    def _prepare_export_payload(self) -> tuple[str, dict]:
        config = {"rooms": []}
        audio_files_map: dict[str, dict] = {}
        track_entries_map: dict[str, dict] = {}
        anchor_bound_flags = {a.number: bool(a.bound_explicit) for a in self.anchors}
        anchor_zone_halls: dict[int, set[int]] = {}

        for pz in self.proximity_zones:
            if not pz.anchor:
                continue
            halls = pz.halls or ([pz.anchor.main_hall_number] if pz.anchor else [])
            for hall_num in halls:
                if not isinstance(hall_num, int):
                    continue
                anchor_zone_halls.setdefault(pz.anchor.number, set()).add(hall_num)

        def _bytes_from_b64(b64str: str) -> int:
            if not b64str:
                return 0
            try:
                return len(base64.b64decode(b64str.encode("ascii")))
            except Exception:
                return 0

        def _extract_size(info: dict | None) -> int:
            if not isinstance(info, dict):
                return 0
            try:
                size_val = int(info.get("size") or 0)
            except (TypeError, ValueError):
                size_val = 0
            if size_val <= 0:
                size_val = _bytes_from_b64(info.get("data", ""))
            return max(size_val, 0)

        def _extract_crc32(info: dict | None) -> str:
            if not isinstance(info, dict):
                return ""
            payload = info.get("data")
            if not payload:
                crc_value = str(info.get("crc32", "") or "").strip().lower()
                return crc_value
            try:
                raw_bytes = base64.b64decode(payload.encode("ascii"))
            except Exception:
                return ""
            crc = 0
            for offset in range(0, len(raw_bytes), 4096):
                crc = zlib.crc32(raw_bytes[offset:offset + 4096], crc)
            return f"{crc & 0xFFFFFFFF:08x}"

        def _register_audio_file(name: str, size_bytes: int, crc32_hex: str):
            existing = audio_files_map.get(name)
            if existing is None:
                audio_files_map[name] = {
                    "size": max(size_bytes, 0),
                    "crc32": crc32_hex
                }
                return
            existing["size"] = max(int(existing.get("size", 0)), max(size_bytes, 0))
            if crc32_hex:
                existing["crc32"] = crc32_hex

        def collect_audio_files(info: dict | None):
            if not isinstance(info, dict):
                return
            name = info.get("filename")
            if isinstance(name, str) and name:
                size_bytes = _extract_size(info)
                _register_audio_file(name, size_bytes, _extract_crc32(info))
            secondary = info.get("secondary")
            if isinstance(secondary, dict):
                sec_name = secondary.get("filename")
                if isinstance(sec_name, str) and sec_name:
                    size_bytes2 = _extract_size(secondary)
                    _register_audio_file(sec_name, size_bytes2, _extract_crc32(secondary))

        def create_track_entry(info: dict | None, room_id: int, is_hall: bool):
            if not isinstance(info, dict):
                return None
            filename = info.get("filename")
            if not filename:
                return None
            base_id = extract_track_id(filename)
            extras = [i for i in info.get("extra_ids", []) if isinstance(i, int)]

            entry = {
                "audio": filename,
                "hall": is_hall,
                "id": base_id,
                "name": "",
                "play_once": bool(info.get("play_once", False)),
                "reset": bool(info.get("reset", False)),
                "room_id": room_id,
                "term": bool(info.get("interruptible", True))
            }

            if extras:
                seen = set()
                merged = []
                for mid in [base_id] + extras:
                    if mid in seen:
                        continue
                    seen.add(mid)
                    merged.append(mid)
                entry["multi_id"] = merged

            secondary = info.get("secondary")
            if isinstance(secondary, dict) and secondary.get("filename"):
                entry["audio2"] = secondary["filename"]
                entry["extra"] = True
            return entry

        def register_track_entry(entry: dict | None):
            if not isinstance(entry, dict):
                return
            key = entry.get("audio")
            if not key:
                return
            existing = track_entries_map.get(key)
            if existing is None:
                track_entries_map[key] = entry
                return

            existing["hall"] = bool(existing.get("hall")) or bool(entry.get("hall"))

            new_room = entry.get("room_id")
            old_room = existing.get("room_id")
            if isinstance(new_room, int):
                if not isinstance(old_room, int):
                    existing["room_id"] = new_room
                else:
                    existing["room_id"] = min(old_room, new_room)

            if entry.get("audio2") and not existing.get("audio2"):
                existing["audio2"] = entry["audio2"]

            if entry.get("extra"):
                existing["extra"] = True

            existing["play_once"] = bool(existing.get("play_once")) or bool(entry.get("play_once"))
            existing["reset"] = bool(existing.get("reset")) or bool(entry.get("reset"))
            existing["term"] = bool(existing.get("term", True)) and bool(entry.get("term", True))

            combined_ids: set[int] = set()
            for value in (existing.get("id"), entry.get("id")):
                if isinstance(value, int):
                    combined_ids.add(value)
            for seq in (existing.get("multi_id"), entry.get("multi_id")):
                if isinstance(seq, list):
                    for value in seq:
                        if isinstance(value, int):
                            combined_ids.add(value)
            base_id = existing.get("id")
            if isinstance(base_id, int) and base_id in combined_ids:
                combined_ids.remove(base_id)
            if combined_ids:
                existing["multi_id"] = sorted(combined_ids)
            elif "multi_id" in existing:
                existing.pop("multi_id")

        # === rooms.json ===
        for h in self.halls:
            w_m = fix_negative_zero(round(h.rect().width() / (self.scene.pixel_per_cm_x * 100), 1))
            h_m = fix_negative_zero(round(h.rect().height() / (self.scene.pixel_per_cm_x * 100), 1))

            room = {
                "num": h.number,
                "width": w_m,
                "height": h_m,
                "anchors": [],
                "zones": []
            }
            if h.extra_tracks:
                room["extra_tracks"] = sorted({int(x) for x in h.extra_tracks if isinstance(x, int)})

            for a in self.anchors:
                if a.main_hall_number == h.number or h.number in a.extra_halls:
                    lp = h.mapFromScene(a.scenePos())
                    xm = fix_negative_zero(round(lp.x() / (self.scene.pixel_per_cm_x * 100), 1))
                    ym = fix_negative_zero(round((h.rect().height() - lp.y()) / (self.scene.pixel_per_cm_x * 100), 1))
                    ae = {"id": a.number, "x": xm, "y": ym, "z": fix_negative_zero(round(a.z / 100, 1))}
                    if anchor_bound_flags.get(a.number, False):
                        ae["bound"] = True
                    if h.number in anchor_zone_halls.get(a.number, set()):
                        ae["anch_zone"] = True
                    room["anchors"].append(ae)

            zones: dict[int, dict] = {}
            default = {"x": 0, "y": 0, "w": 0, "h": 0, "angle": 0}
            for ch in h.childItems():
                if isinstance(ch, RectZoneItem):
                    n = ch.zone_num
                    if n not in zones:
                        zones[n] = {"num": n, "enter": default.copy(), "exit": default.copy()}
                    dz = ch.get_export_data()
                    if ch.zone_type == "Входная зона":
                        zones[n]["enter"] = dz
                    elif ch.zone_type == "Выходная зона":
                        zones[n]["exit"] = dz
                    elif ch.zone_type == "Переходная":
                        zones[n]["enter"] = dz
                        zones[n]["bound"] = True

            for z in zones.values():
                room["zones"].append(z)

            for pz in self.proximity_zones:
                if not pz.anchor:
                    continue
                halls = pz.halls or ([pz.anchor.main_hall_number] if pz.anchor else [])
                if h.number not in halls:
                    continue
                pz_entry = {
                    "num": pz.zone_num,
                    "anch_zone": True,
                    "anchor_id": pz.anchor.number if pz.anchor else None,
                    "dist_in": fix_negative_zero(round(pz.dist_in, 1)),
                    "dist_out": fix_negative_zero(round(pz.dist_out, 1)),
                }
                if pz.bound:
                    pz_entry["bound"] = True
                if pz.blacklist:
                    pz_entry["blist"] = list(pz.blacklist)
                room["zones"].append(pz_entry)

            config["rooms"].append(room)

            if h.audio_settings:
                collect_audio_files(h.audio_settings)
                register_track_entry(create_track_entry(h.audio_settings, h.number, True))
            for _, audio_info in sorted(h.zone_audio_tracks.items()):
                if not audio_info:
                    continue
                collect_audio_files(audio_info)
                register_track_entry(create_track_entry(audio_info, h.number, False))

        for pz in self.proximity_zones:
            if not pz.audio_info:
                continue
            halls = pz.halls or ([] if not pz.anchor else [pz.anchor.main_hall_number])
            hall_numbers = [h for h in halls if isinstance(h, int)]
            room_id = min(hall_numbers) if hall_numbers else (pz.anchor.main_hall_number if pz.anchor else 0)
            collect_audio_files(pz.audio_info)
            register_track_entry(create_track_entry(pz.audio_info, room_id if room_id is not None else 0, False))

        rooms_strs = []
        for room in config["rooms"]:
            lines = [
                "{",
                f'"num": {room["num"]},',
                f'"width": {room["width"]},',
                f'"height": {room["height"]},',
                (f'"extra_tracks": {json.dumps(room["extra_tracks"], ensure_ascii=False)},' if room.get("extra_tracks") else None),
                '"anchors": ['
            ]
            lines = [line for line in lines if line is not None]
            alines = []
            for a in room["anchors"]:
                s = f'{{ "id": {a["id"]}, "x": {a["x"]}, "y": {a["y"]}, "z": {a["z"]}'
                if a.get("bound"):
                    s += ', "bound": true'
                if a.get("anch_zone"):
                    s += ', "anch_zone": true'
                s += " }"
                alines.append(s)
            lines.append(",\n".join(alines))
            lines.append("],")
            lines.append('"zones": [')
            zlines = []
            for z in room["zones"]:
                if z.get("anch_zone"):
                    zl = "{"
                    zl += f'\n"num": {z.get("num", 0)},'
                    zl += f'\n"anch_zone": true,'
                    zl += f'\n"anchor_id": {z.get("anchor_id", 0)},'
                    zl += f'\n"dist_in": {z.get("dist_in", 0)},'
                    zl += f'\n"dist_out": {z.get("dist_out", 0)}'
                    if z.get("bound"):
                        zl += ',\n"bound": true'
                    if z.get("blist"):
                        zl += f',\n"blist": {json.dumps(z.get("blist"))}'
                    zl += "\n}"
                else:
                    zl = "{"
                    zl += f'\n"num": {z["num"]},'
                    zl += (
                        f'\n"enter": {{ "x": {z["enter"]["x"]}, "y": {z["enter"]["y"]}, '
                        f'"w": {z["enter"]["w"]}, "h": {z["enter"]["h"]}, '
                        f'"angle": {z["enter"]["angle"]} }},'
                    )
                    zl += (
                        f'\n"exit":  {{ "x": {z["exit"]["x"]}, "y": {z["exit"]["y"]}, '
                        f'"w": {z["exit"]["w"]}, "h": {z["exit"]["h"]}, '
                        f'"angle": {z["exit"]["angle"]} }}'
                    )
                    if z.get("bound"):
                        zl += ',\n"bound": true'
                    zl += "\n}"
                zlines.append(zl)
            lines.append(",\n".join(zlines))
            lines.append("]")
            lines.append("}")
            rooms_strs.append("\n".join(lines))

        rooms_json_text = '{\n"rooms": [\n' + ",\n".join(rooms_strs) + "\n]\n}"

        track_entries = list(track_entries_map.values())

        def _sort_key(item: dict):
            room_id = item.get("room_id")
            if not isinstance(room_id, int):
                try:
                    room_id = int(room_id)
                except (TypeError, ValueError):
                    room_id = 0
            return (
                room_id,
                not bool(item.get("hall")),
                item.get("id", 0),
                item.get("audio", "")
            )

        track_entries.sort(key=_sort_key)
        files_list = []
        for name in sorted(audio_files_map):
            file_info = audio_files_map[name]
            files_list.append({
                "name": name,
                "size": int(file_info.get("size", 0)),
                "crc32": file_info.get("crc32", "")
            })
        tracks_data = {
            "files": files_list,
            "langs": [],
            "tracks": track_entries,
            "version": datetime.now().strftime("%y%m%d")
        }

        return rooms_json_text, tracks_data

    @staticmethod
    def _normalize_unmatched_audio_files(raw_files):
        def _safe_size(value):
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        normalized = {}
        if not isinstance(raw_files, dict):
            return normalized
        for name, meta in raw_files.items():
            if not isinstance(name, str) or not name:
                continue
            item = meta if isinstance(meta, dict) else {}
            normalized[name] = {
                "name": name,
                "size": _safe_size(item.get("size", 0)),
                "crc32": str(item.get("crc32", "") or ""),
            }
        return normalized

    def _merge_unmatched_audio_files_into_tracks_data(self, tracks_data: dict):
        files_index = {
            str(item.get("name", "")): item
            for item in tracks_data.get("files", [])
            if isinstance(item, dict) and item.get("name")
        }
        for name, meta in self.unmatched_audio_files.items():
            existing = files_index.get(name)
            if existing is None:
                files_index[name] = {
                    "name": name,
                    "size": int(meta.get("size", 0)),
                    "crc32": str(meta.get("crc32", "")),
                }
                continue
            existing["size"] = max(int(existing.get("size", 0)), int(meta.get("size", 0)))
            if not existing.get("crc32") and meta.get("crc32"):
                existing["crc32"] = str(meta.get("crc32", ""))
        tracks_data["files"] = [files_index[name] for name in sorted(files_index)]

    def _merge_existing_tracks_metadata(self, tracks_data: dict):
        tracks_path = self._tracks_json_path()
        if not tracks_path or not os.path.isfile(tracks_path):
            return
        try:
            with open(tracks_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            return

        existing_files = existing_data.get("files") if isinstance(existing_data, dict) else None
        if not isinstance(existing_files, list):
            return

        existing_index = {}
        for item in existing_files:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            existing_index[name] = item

        for item in tracks_data.get("files", []):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            old_item = existing_index.get(name)
            if not isinstance(old_item, dict):
                continue

            if not item.get("crc32") and old_item.get("crc32"):
                item["crc32"] = str(old_item.get("crc32", ""))

            try:
                current_size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                current_size = 0
            try:
                old_size = int(old_item.get("size") or 0)
            except (TypeError, ValueError):
                old_size = 0
            item["size"] = max(current_size, old_size, 0)

    def closeEvent(self, event):
        self._save_window_preferences()
        if not self._confirm_save_discard("Сохранить текущий проект перед выходом?"):
            event.ignore()
            return
        try:
            self.scene.selectionChanged.disconnect(self.on_scene_selection_changed)
        except Exception:
            pass
        self.view.setScene(None)
        event.accept()

if __name__ == "__main__":
    app = QApplication(os.getenv("QT_FORCE_STDERR_LOGGING") and sys.argv or sys.argv)
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    app_icon_path = os.path.join(icons_dir, "app.png")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))
    window = PlanEditorMainWindow()
    window.show()
    sys.exit(app.exec())
