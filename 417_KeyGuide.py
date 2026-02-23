import sys
import json
import os
import time
import math
import logging
import traceback
from pathlib import Path

# --- High DPI対応 & Qtログ抑制 ---
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_LOGGING_RULES"] = "qt.text.font.db=false"

from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                             QSystemTrayIcon, QMenu, QDialog, QFormLayout, 
                             QSpinBox, QCheckBox, QColorDialog, QPushButton, 
                             QTabWidget, QFrame, QStyle, QFontDialog, QDoubleSpinBox,
                             QTextEdit, QMessageBox, QGraphicsDropShadowEffect,
                             QFileDialog, QGraphicsOpacityEffect, QComboBox, QSizePolicy,
                             QGroupBox, QListWidget, QListWidgetItem, QAbstractItemView,
                             QScrollArea, QLineEdit, QGridLayout, QTreeWidget, QTreeWidgetItem,
                             QHeaderView, QKeySequenceEdit, QButtonGroup, QSpacerItem,
                             QTreeWidgetItemIterator, QTableWidget, QTableWidgetItem,
                             QSlider, QSizeGrip, QStyledItemDelegate, QStyleOptionViewItem,
                             QStyleOptionButton)
from PyQt6.QtCore import (Qt, QTimer, pyqtSignal, QObject, QPoint, QRect, QSize, QEvent, 
                          pyqtSlot, QStandardPaths, QLibraryInfo, QSharedMemory)
from PyQt6.QtGui import (QPainter, QColor, QAction, QCursor, QFont, QPainterPath, QIcon,
                         QPolygon, QFontDatabase, QPixmap, QPen, QFontMetrics, QKeySequence, QShortcut, QLinearGradient)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from pynput import mouse, keyboard

# --- アプリケーション定数 ---
APP_NAME = "417 KeyGuide"
APP_ORG = "MyTools"
APP_VERSION = "0.9.0-beta" 
IPC_KEY = "417KeyGuide_Instance_Lock_Socket"

# --- スクロールバーの共通スタイル ---
SCROLLBAR_STYLESHEET = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 10px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: rgba(128, 128, 128, 0.5);
        min-height: 20px;
        border-radius: 5px;
        margin: 0px 3px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(128, 128, 128, 0.8);
        margin: 0px 1px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
"""

# --- カスタムデリゲート ---
class CenteredCheckBoxDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() in [0, 1, 2]: return None
        return super().createEditor(parent, option, index)

    def paint(self, painter, option, index):
        if index.column() in [0, 1, 2]:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
            opt.text = "" 
            style = opt.widget.style() if opt.widget else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
            check_data = index.data(Qt.ItemDataRole.CheckStateRole)
            is_checked = False
            if isinstance(check_data, int): is_checked = (check_data == Qt.CheckState.Checked.value)
            elif check_data == Qt.CheckState.Checked: is_checked = True
            chk_opt = QStyleOptionButton()
            chk_opt.state = opt.state
            if is_checked: chk_opt.state |= QStyle.StateFlag.State_On
            else: chk_opt.state |= QStyle.StateFlag.State_Off
            chk_rect = style.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, chk_opt, opt.widget)
            center_x = opt.rect.x() + (opt.rect.width() - chk_rect.width()) / 2
            center_y = opt.rect.y() + (opt.rect.height() - chk_rect.height()) / 2
            chk_opt.rect = QRect(int(center_x), int(center_y), chk_rect.width(), chk_rect.height())
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, chk_opt, painter, opt.widget)
        else:
            super().paint(painter, option, index)

    def editorEvent(self, event, model, option, index):
        if index.column() in [0, 1, 2]:
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if option.rect.contains(event.pos()):
                    current_state = index.data(Qt.ItemDataRole.CheckStateRole)
                    is_checked = False
                    if isinstance(current_state, int): is_checked = (current_state == Qt.CheckState.Checked.value)
                    elif current_state == Qt.CheckState.Checked: is_checked = True
                    new_state = Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
                    model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
                    return True
        return super().editorEvent(event, model, option, index)

# --- カスタムウィジェット ---
class NoScrollSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(140)
    def wheelEvent(self, event): event.ignore()

class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(140)
    def wheelEvent(self, event): event.ignore()

class NoScrollSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event): event.ignore()

# --- 設定管理クラス ---
class Config(QObject):
    changed_signal = pyqtSignal(str, object) 
    reload_signal = pyqtSignal()
    language_changed_signal = pyqtSignal() # 言語変更専用シグナル

    DEFAULT_SETTINGS = {
        "language": "ja-original", 
        "log_enabled": True,
        "display_time": 2000, 
        "fade_duration": 1000, 
        "max_stack": 1,
        "pos_x": 50,
        "pos_y": 800,
        "window_width": 500,
        "combo_timeout": 1000,
        "double_click_timeout": 0.3,
        "show_single_keys": True,
        "text_color": "#FFFFFFFF",
        "bg_color": "#CC000000",
        "font_family": "Arial",
        "font_size": 28,
        "font_bold": True,
        "font_italic": False,
        "font_underline": False,
        "font_strikeout": False,
        "text_shadow_enabled": False,
        "text_shadow_blur": 0,
        "text_shadow_color": "#FF000000",
        "text_shadow_offset_x": 2,
        "text_shadow_offset_y": 2,
        "text_outline_enabled": False,
        "text_outline_width": 2,
        "text_outline_color": "#FF000000",
        "desc_text_color": "#FFDDDDDD",
        "desc_font_family": "Arial",
        "desc_font_size": 16,
        "desc_font_bold": False,
        "desc_font_italic": False,
        "desc_font_underline": False,
        "desc_font_strikeout": False,
        "desc_shadow_enabled": False,
        "desc_shadow_blur": 0,
        "desc_shadow_color": "#FF000000",
        "desc_shadow_offset_x": 1,
        "desc_shadow_offset_y": 1,
        "desc_outline_enabled": False,
        "desc_outline_width": 1,
        "desc_outline_color": "#FF000000",
        "separator_enabled": True,
        "separator_color": "#FF888888",
        "separator_width": 1,
        "separator_spacing": 5,
        "sep_shadow_enabled": False,
        "sep_shadow_blur": 2,
        "sep_shadow_color": "#FF000000",
        "sep_shadow_offset_x": 1,
        "sep_shadow_offset_y": 1,
        "padding_x": 15,
        "padding_y": 8,
        "border_width": 0,
        "border_color": "#FFFFFFFF",
        "border_radius": 8,
        "item_proximity_enabled": True,
        "item_proximity_dist": 150,
        "item_proximity_min_opacity": 0.1,
        "cheat_sheet_enabled": True,
        "cheat_sheet_key": "Tab", 
        "cheat_sheet_hold_ms": 300, 
        "cheat_sheet_bg_color": "#DC000000",
        "cheat_sheet_fullscreen_bg_color": "#DC000000",
        "cheat_sheet_header_color": "#FFFFD700",
        "cheat_sheet_key_color": "#FF00A6FF",
        "cheat_sheet_desc_color": "#FFFFFFFF",
        "cheat_sheet_key_align": 0,
        "cheat_sheet_spacing": 20,
        "cheat_sheet_font_size": 14,
        "cheat_sheet_col_width_key": 100, 
        "cheat_sheet_col_width_desc": 50,
        "cheat_sheet_word_wrap": True,
        "cheat_window_border_enabled": False,
        "cheat_window_border_color": "#FFFFFFFF",
        "cheat_window_geo": None,
        "cheat_sheet_fullscreen_font_size": 24, 
        "cheat_sheet_fullscreen_min_key": 100,
        "cheat_sheet_fullscreen_min_desc": 50,
        "mouse_halo_enabled": True,
        "halo_size": 20,
        "halo_color": "#66FFFFFF",
        "halo_offset_x": 0,
        "halo_offset_y": 0,
        "middle_click_square_size": 15,
        "scroll_arrow_size": 20,
        "scroll_arrow_color": "#FF000000",
        "click_left_color": "#FFFFAA00",
        "click_right_color": "#FFFFAA00",
        "click_middle_color": "#FFFFAA00",
        "scroll_color": "#FF000000",
        "action_symbol_scale": 1.0,
        "log_left_click": False,
        "log_left_double": True,
        "log_right_click": True,
        "log_middle_click": True,
        "log_middle_drag": True,
        "log_scroll": True,
        "drag_threshold": 15,
        "icon_paths": { "left": "", "right": "", "middle": "" },
        "log_display_mode": 0,
        "mod_mouse_display_mode": 1,
        "icon_size": 40,
        "custom_fonts": [],
        "cascadeur_mode": True,
        "show_desc": True,
        "mouse_aliases": {
            "Left Click": "Left Click", "Right Click": "Right Click", "Middle Click": "Middle Click",
            "Double Click": "Double Click", "Middle Drag": "Middle Drag", "Scroll Up": "Scroll Up", "Scroll Down": "Scroll Down"
        }
    }

    DEFAULT_SHORTCUTS = [
        {"combo": "# Common", "desc": "", "enabled": True, "type": "header", "show_in_log": True, "show_in_cheat": True},
        {"combo": "Ctrl+C", "desc": "Copy", "enabled": True, "type": "key", "show_in_log": True, "show_in_cheat": True},
        {"combo": "Ctrl+V", "desc": "Paste", "enabled": True, "type": "key", "show_in_log": True, "show_in_cheat": True},
        {"combo": "Ctrl+Z", "desc": "Undo", "enabled": True, "type": "key", "show_in_log": True, "show_in_cheat": True},
        {"combo": "Ctrl+S", "desc": "Save", "enabled": True, "type": "key", "show_in_log": True, "show_in_cheat": True}
    ]
    
    DEFAULT_LOCALE = {
        "ui.window.cheat": "417 KeyGuide (Cheat Sheet)", "ui.btn.reset_page": "このページを初期化",
        "ui.btn.quit": "アプリを終了", "ui.common.color": "色を選択", "ui.common.opacity": "不透明度:", "ui.common.font": "フォント:",
        "ui.common.file_select": "ファイル選択...", "ui.common.cancel": "キャンセル", "ui.common.confirm": "確認", "ui.common.error": "エラー",
        "ui.tab.general": "ログ表示", "ui.tab.mouse": "マウスログ", "ui.tab.appearance": "ログ外観", "ui.tab.cheat": "チートシート", "ui.tab.shortcuts": "ショートカット管理",
        "ui.gen.log_enable": "キー入力ログ表示を有効にする", "ui.gen.disp_time": "ログ表示維持時間 (ms):", "ui.gen.fade_time": "フェードアウト時間 (ms):",
        "ui.gen.max_stack": "最大ログ表示数:", "ui.gen.combo_to": "連続入力判定時間 (ms):", "ui.gen.pos_btn": "画面上で位置を指定する",
        "ui.gen.pos_label": "位置:", "ui.gen.pos_x": "X座標:", "ui.gen.pos_y": "Y座標:", "ui.gen.pos_guide_1": "ログ表示範囲の【左下】をクリック", "ui.gen.pos_guide_2": "(Escキーでキャンセル)",
        "ui.mouse.sec_icon": "【アイコン設定】", "ui.mouse.mode_normal": "通常表示モード:", "ui.mouse.mode_mod": "修飾キー+クリック表示モード:",
        "ui.mouse.mode_0": "文字のみ", "ui.mouse.mode_1": "アイコン + 文字", "ui.mouse.mode_2": "アイコンのみ(文字置換)", "ui.mouse.icon_l": "左クリック画像:",
        "ui.mouse.icon_r": "右クリック画像:", "ui.mouse.icon_m": "中ボタン/スクロール画像:", "ui.mouse.icon_size": "アイコンサイズ:", "ui.mouse.sec_alias": "【操作名の変更】",
        "ui.mouse.sec_target": "【ログ出力対象】", "ui.mouse.log_l": "左クリック (単発)", "ui.mouse.log_r": "右クリック", "ui.mouse.log_m": "中クリック",
        "ui.mouse.log_d": "中ドラッグ", "ui.mouse.log_s": "スクロール", "ui.mouse.sec_halo": "【マウス円 (Halo) 設定】", "ui.mouse.halo_enable": "有効化",
        "ui.mouse.halo_r": "円の半径:", "ui.mouse.halo_sq": "中クリック(■)サイズ:", "ui.mouse.halo_arr": "スクロール(▼▲)サイズ:", "ui.mouse.col_base": "基本色",
        "ui.mouse.col_l": "左クリック色", "ui.mouse.col_r": "右クリック色", "ui.mouse.col_m": "中クリック色", "ui.mouse.col_s": "スクロール矢印色",
        "ui.app.grp_font": "カスタムフォント管理", "ui.app.btn_add": "追加...", "ui.app.btn_del": "削除", "ui.app.grp_main": "キー入力文字 (Main)",
        "ui.app.col_text": "文字色", "ui.app.chk_shadow": "影を有効化", "ui.app.col_shadow": "影色", "ui.app.offset": "  Offset X/Y:", "ui.app.chk_outline": "縁取りを有効化",
        "ui.app.width": "  太さ:", "ui.app.col_outline": "縁色", "ui.app.grp_desc": "説明文 (Desc)", "ui.app.chk_show_desc": "説明を表示する", "ui.app.grp_sep": "区切り線",
        "ui.app.chk_sep": "線を引く", "ui.app.col_sep": "線の色", "ui.app.width_sep": "太さ:", "ui.app.spacing": "余白:", "ui.app.grp_bg": "背景・ウィンドウ枠",
        "ui.app.col_bg": "ログ背景色", "ui.app.col_border": "枠線の色", "ui.app.width_border": "枠線の太さ:", "ui.app.radius": "角丸半径:", "ui.app.grp_prox": "近接透過",
        "ui.app.chk_prox": "マウス接近で個別に透過する", "ui.app.prox_dist": "反応距離 (px):", "ui.app.prox_min": "最大透過時不透明度:",
        "ui.cheat.enable": "チートシートを有効化", "ui.cheat.note": "※単押しで「ウィンドウ表示」、長押しで「全画面表示」します。", "ui.cheat.sec_act": "【動作設定】",
        "ui.cheat.trigger": "トリガーキー:", "ui.cheat.placeholder": "例: F1, Alt, Shift", "ui.cheat.hold": "長押し判定時間 (ms):", "ui.cheat.close_hint": "(【{}】で閉じる)",
        "ui.cheat.sec_com": "【表示設定(共通)】", "ui.cheat.align": "キー列の配置:", "ui.cheat.align_l": "左揃え", "ui.cheat.align_r": "右揃え", "ui.cheat.spacing": "キーと説明文間の余白:",
        "ui.cheat.sec_win": "【表示設定(ウィンドウモード)】", "ui.cheat.font_size": "フォントサイズ:", "ui.cheat.col_w_key": "キー列の最小幅 (px):", "ui.cheat.col_w_desc": "説明文の最小幅 (px):",
        "ui.cheat.wrap": "説明文の自動折り返し", "ui.cheat.wrap_note": "　※ウィンドウの幅に合わせて自動で説明文を折り返します。", "ui.cheat.sec_full": "【表示設定(全画面モード)】",
        "ui.cheat.full_note": "　※項目が多い場合、自動で縮小します", "ui.cheat.sec_col": "【色設定】", "ui.cheat.col_h": "ヘッダー文字色", "ui.cheat.col_k": "キー文字色",
        "ui.cheat.col_d": "説明文字色", "ui.cheat.col_bg_win": "背景色(ウィンドウ)", "ui.cheat.col_bg_full": "背景色(全画面)", "ui.cheat.chk_border": "ウィンドウ内に外枠をつける",
        "ui.cheat.col_border": "外枠の色(ウィンドウ)", "ui.sc.note": "※ ショートカット押下時に説明文を表示します", "ui.sc.add": "項目を追加", "ui.sc.del": "削除",
        "ui.sc.all_del": "全て削除", "ui.sc.import": "読込 (JSON/TXT)", "ui.sc.export": "出力 (JSON/TXT)", "ui.sc.toggle_master": "マスター全有効/無効",
        "ui.sc.toggle_log": "ログ全有効/無効", "ui.sc.toggle_cheat": "チート全有効/無効", "ui.sc.msg_del": "リストを全て削除しますか？\nこの操作は取り消せますが、現在のリストは消去されます。",
        "ui.sc.msg_imp_mode": "件のデータを読み込みました。\nモードを選択してください", "ui.sc.btn_append": "追加 (末尾)", "ui.sc.btn_overwrite": "上書き (置換)",
        "ui.sc.msg_exp_opt": "出力形式を選択してください", "ui.sc.btn_full": "フル設定 (JSON)", "ui.sc.btn_simple": "キーと説明のみ (Simple)", "ui.sc.msg_saved": "保存しました。",
        "ui.sc.btn_reset": "初期化", "ui.sc.reset_confirm_title": "確認", "ui.sc.reset_confirm_msg": "ショートカットリストを初期状態（デフォルト）に戻しますか？\n現在のリストは破棄されます。",
        "ui.tray.log": "ログ 有効/無効", "ui.tray.cheat": "チートシート 有効/無効", "ui.tray.settings": "設定", "ui.tray.exit": "アプリの終了",
        "ui.lang.note_missing": "データが一部不足している場合、各言語の初期値または日本語にします。",
        "ui.lang.note_corrupt": "データが破損した場合は、[config]フォルダ内の、問題のあるjsonデータを削除してください。\n全てのjsonデータは、削除後にアプリの再起動や設定変更をすると自動で再生成されます。"
    }

    LANGUAGES = {
        "ja-original": "日本語 (Default)",
        "en": "English",
        "ru": "Русский",
        "zh": "中文",
        "ko": "한국어",
        "hi": "हिन्दी",
        "custom": "Other (Custom)"
    }

    FILE_SETTINGS = "settings.json"
    FILE_SHORTCUTS = "shortcuts.json"
    CONFIG_DIR_NAME = "config"
    LANG_DIR_NAME = "language"

    def __init__(self):
        super().__init__()
        self.data = self.DEFAULT_SETTINGS.copy()
        self.shortcuts = self.DEFAULT_SHORTCUTS.copy()
        self.locale_data = self.DEFAULT_LOCALE.copy()
        
        self.undo_stack = []
        self.redo_stack = []
        self.is_undoing = False
        
        self.data_dir = Path(".")
        self.config_dir = Path(".")
        self.lang_dir = Path(".")
        
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self._perform_save)

    def init_paths(self):
        try:
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
                self.bundle_dir = Path(sys._MEIPASS)
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
                self.bundle_dir = Path(base_path)
            
            self.data_dir = Path(base_path)
            self.config_dir = self.data_dir / self.CONFIG_DIR_NAME
            self.lang_dir = self.config_dir / self.LANG_DIR_NAME
            
            if not self.config_dir.exists():
                self.config_dir.mkdir(parents=True, exist_ok=True)
            if not self.lang_dir.exists():
                self.lang_dir.mkdir(parents=True, exist_ok=True)
                
            print(f"Config directory: {self.config_dir}") 
        except Exception as e:
            print(f"Failed to init paths: {e}")
            self.config_dir = Path(".")
            self.lang_dir = Path("language")

    def _get_path(self, filename):
        return self.config_dir / filename
    
    def get_app_icon_path(self):
        if hasattr(sys, '_MEIPASS'):
            bundled_icon = Path(sys._MEIPASS) / "icon.ico"
            if bundled_icon.exists(): return str(bundled_icon)
        local_icon = self.data_dir / "icon.ico"
        if local_icon.exists(): return str(local_icon)
        return None

    def load(self):
        f_settings = self._get_path(self.FILE_SETTINGS)
        if f_settings.exists():
            try:
                with open(f_settings, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    for k, v in loaded.items():
                        if k == "icon_paths" and isinstance(v, dict): self.data["icon_paths"].update(v)
                        elif k == "mouse_aliases" and isinstance(v, dict): self.data["mouse_aliases"].update(v)
                        elif k in self.data:
                             if "color" in k and isinstance(v, str) and v.startswith("#") and len(v) == 7: v = "#FF" + v[1:]
                             self.data[k] = v
            except Exception as e: logging.error(f"Failed to load settings: {e}")

        f_shortcuts = self._get_path(self.FILE_SHORTCUTS)
        if f_shortcuts.exists():
            try:
                with open(f_shortcuts, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.shortcuts = []
                        for item in data:
                            if isinstance(item, dict):
                                if "show_in_log" not in item: item["show_in_log"] = True
                                if "show_in_cheat" not in item: item["show_in_cheat"] = True
                                self.shortcuts.append(item)
            except Exception as e: logging.error(f"Failed to load shortcuts: {e}")

        self._load_custom_fonts()
        self.ensure_language_files()
        self.load_locale()

    def ensure_language_files(self):
        try:
            # 1. ja-original.json (常に再生成)
            ja_path = self.lang_dir / "ja-original.json"
            try:
                with open(ja_path, 'w', encoding='utf-8') as f:
                    json.dump(self.DEFAULT_LOCALE, f, indent=4, ensure_ascii=False)
            except Exception as e: logging.error(f"Failed to generate ja-original.json: {e}")

            target_langs = ["en", "ru", "zh", "ko", "hi", "custom"]
            
            for lang in target_langs:
                file_name = f"{lang}.json"
                target_path = self.lang_dir / file_name
                bundled_path = self.bundle_dir / self.LANG_DIR_NAME / file_name
                
                # 優先順位: User File > Bundled File > Default Locale
                
                current_data = {}
                # ユーザーデータの読み込み
                if target_path.exists():
                    try:
                        with open(target_path, 'r', encoding='utf-8') as f:
                            current_data = json.load(f)
                    except:
                        current_data = {} # 破損時は空とみなす

                # バンドルデータの読み込み
                bundled_data = {}
                if bundled_path.exists():
                    try:
                        with open(bundled_path, 'r', encoding='utf-8') as f:
                            bundled_data = json.load(f)
                    except:
                        pass

                modified = False
                # デフォルトキー(日本語)を基準に不足分を補完
                for k, v_default in self.DEFAULT_LOCALE.items():
                    if k not in current_data:
                        # ユーザーデータにない場合、バンドルデータにあるか確認
                        if k in bundled_data:
                            current_data[k] = bundled_data[k]
                        else:
                            # バンドルにもなければ日本語デフォルトを使用
                            current_data[k] = v_default
                        modified = True
                
                # ファイルが存在しない、または変更があった場合に書き込み
                if modified or not target_path.exists():
                    try:
                        with open(target_path, 'w', encoding='utf-8') as f:
                            json.dump(current_data, f, indent=4, ensure_ascii=False)
                        if modified and target_path.exists():
                            logging.info(f"Updated {file_name} with missing keys.")
                        else:
                            logging.info(f"Created {file_name}.")
                    except Exception as e:
                        logging.error(f"Failed to save language file {file_name}: {e}")

        except Exception as e:
            logging.error(f"Error in ensure_language_files: {e}")

    def load_locale(self):
        current_lang = self.data.get("language", "ja-original")
        file_name = f"{current_lang}.json"
        f_locale = self.lang_dir / file_name
        
        # ロケールデータをリセット（デフォルトに戻す）してからロード
        self.locale_data = self.DEFAULT_LOCALE.copy()

        if not f_locale.exists():
            f_locale = self.lang_dir / "ja-original.json"
            
        if f_locale.exists():
            try:
                with open(f_locale, 'r', encoding='utf-8') as f:
                    user_locale = json.load(f)
                    self.locale_data.update(user_locale)
            except Exception as e:
                logging.error(f"Failed to load locale {f_locale}: {e}")

    def tr(self, key, default): return self.locale_data.get(key, default)

    def _load_custom_fonts(self):
        for path in self.data.get("custom_fonts", []):
            if os.path.exists(path): QFontDatabase.addApplicationFont(path)

    def save(self):
        self.save_timer.start()

    def force_save(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._perform_save()

    def _perform_save(self):
        try:
            tmp_settings = self._get_path(self.FILE_SETTINGS).with_suffix(".tmp")
            target_settings = self._get_path(self.FILE_SETTINGS)
            with open(tmp_settings, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_settings, target_settings)

            tmp_shortcuts = self._get_path(self.FILE_SHORTCUTS).with_suffix(".tmp")
            target_shortcuts = self._get_path(self.FILE_SHORTCUTS)
            with open(tmp_shortcuts, 'w', encoding='utf-8') as f:
                json.dump(self.shortcuts, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_shortcuts, target_shortcuts)
            logging.info("Configuration saved safely.")
        except Exception as e:
            logging.error(f"Failed to save settings: {e}")

    def get(self, key):
        if key == "shortcuts_list": return self.shortcuts
        return self.data.get(key, self.DEFAULT_SETTINGS.get(key))
    
    def get_default(self, key): return self.DEFAULT_SETTINGS.get(key)

    def set(self, key, value, record_history=True):
        current_val = self.shortcuts if key == "shortcuts_list" else self.data.get(key)
        if current_val == value: return

        if record_history and not self.is_undoing:
            import copy
            old_val = copy.deepcopy(current_val)
            self.undo_stack.append((key, old_val))
            self.redo_stack.clear() 

        if key == "shortcuts_list": self.shortcuts = value
        else: self.data[key] = value
        
        # 言語設定が変更された場合、即座にロケールを再読み込み
        if key == "language":
            self.load_locale()
            self.language_changed_signal.emit()

        self.save()
        self.changed_signal.emit(key, value)
        self.reload_signal.emit()

    def undo(self):
        if not self.undo_stack: return
        key, old_val = self.undo_stack.pop()
        import copy
        current_val = copy.deepcopy(self.shortcuts if key == "shortcuts_list" else self.data.get(key))
        self.redo_stack.append((key, current_val))
        self.is_undoing = True
        self.set(key, old_val, record_history=False)
        self.is_undoing = False

    def redo(self):
        if not self.redo_stack: return
        key, new_val = self.redo_stack.pop()
        import copy
        current_val = copy.deepcopy(self.shortcuts if key == "shortcuts_list" else self.data.get(key))
        self.undo_stack.append((key, current_val))
        self.is_undoing = True
        self.set(key, new_val, record_history=False)
        self.is_undoing = False

    def get_shortcut_item(self, combo_text):
        for item in self.shortcuts:
            if item.get("enabled") and item.get("type") == "key":
                if item.get("combo") == combo_text: return item
        return None

    def get_shortcut_desc(self, combo_text):
        item = self.get_shortcut_item(combo_text)
        return item.get("desc") if item else ""

    def set_icon_path(self, key, path):
        paths = self.data["icon_paths"].copy()
        paths[key] = path
        self.set("icon_paths", paths)
    
    def set_mouse_alias(self, original, new_name):
        aliases = self.data["mouse_aliases"].copy()
        aliases[original] = new_name
        self.set("mouse_aliases", aliases)
        
    def add_custom_font(self, path):
        current = self.get("custom_fonts")
        if path not in current:
            current.append(path)
            self.set("custom_fonts", current)
            QFontDatabase.addApplicationFont(path)

    def remove_custom_font(self, path):
        current = self.get("custom_fonts")
        if path in current:
            current.remove(path)
            self.set("custom_fonts", current)

config = Config()

# --- 入力検知クラス ---
class InputWorker(QObject):
    key_signal = pyqtSignal(str, str, bool)     
    hold_signal = pyqtSignal(str)         
    mouse_signal = pyqtSignal(str, bool)
    halo_scroll_signal = pyqtSignal(int)
    halo_click_signal = pyqtSignal(str, bool)
    
    cheat_overlay_signal = pyqtSignal(bool)
    cheat_window_signal = pyqtSignal()      
    _timer_ctrl_signal = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.pressed_keys = set()
        self.pressed_mouse = set()
        self.active_keys = {} 
        self.k_listener = None
        self.m_listener = None
        self.last_left_click_time = 0
        self.middle_press_pos = None
        self.overlay_active = False     
        self.just_activated_by_hold = False 
        
        self.last_scroll_time = 0

        self.cheat_hold_timer = QTimer()
        self.cheat_hold_timer.setSingleShot(True)
        self.cheat_hold_timer.timeout.connect(self.on_cheat_hold_complete)
        self._timer_ctrl_signal.connect(self._handle_timer_ctrl)
        
        self.key_map_normalize = {
            'ctrl_l': 'Ctrl', 'ctrl_r': 'Ctrl', 'alt_l': 'Alt', 'alt_r': 'Alt',
            'shift': 'Shift', 'shift_r': 'Shift', 'cmd': 'Win', 'cmd_l': 'Win', 'cmd_r': 'Win',
            'control': 'Ctrl', 'alt': 'Alt', 'shift_l': 'Shift', 'menu': 'Menu',
            'enter': 'Enter', 'tab': 'Tab', 'space': 'Space', 'delete': 'Del', 'escape': 'Esc',
            'backspace': 'Backspace', 'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
            'page_up': 'PgUp', 'page_down': 'PgDn', 'home': 'Home', 'end': 'End',
            'insert': 'Ins', 'caps_lock': 'CapsLock', 'num_lock': 'NumLock',
            'print_screen': 'PrtSc', 'scroll_lock': 'ScrLk',
            'f1': 'F1', 'f2': 'F2', 'f3': 'F3', 'f4': 'F4', 'f5': 'F5', 'f6': 'F6',
            'f7': 'F7', 'f8': 'F8', 'f9': 'F9', 'f10': 'F10', 'f11': 'F11', 'f12': 'F12'
        }
        self.update_settings()
        config.reload_signal.connect(self.update_settings)
        self.hold_timer = QTimer()
        self.hold_timer.timeout.connect(self.check_hold)
        self.hold_timer.setInterval(100)

    def update_settings(self):
        self.cfg_log_enabled = config.get("log_enabled")
        self.cfg_drag_threshold = config.get("drag_threshold")
        self.cfg_log_middle_click = config.get("log_middle_click")
        self.cfg_log_middle_drag = config.get("log_middle_drag")
        self.cfg_double_click_timeout = config.get("double_click_timeout")
        self.cfg_log_left_double = config.get("log_left_double")
        self.cfg_log_left_click = config.get("log_left_click")
        self.cfg_log_right_click = config.get("log_right_click")
        self.cfg_log_scroll = config.get("log_scroll")
        self.cfg_show_single_keys = config.get("show_single_keys")
        self.cfg_cascadeur_mode = config.get("cascadeur_mode")
        self.cfg_aliases = config.get("mouse_aliases")
        self.cfg_cheat_enabled = config.get("cheat_sheet_enabled")
        self.cfg_cheat_key = config.get("cheat_sheet_key").upper()
        self.cfg_cheat_hold_ms = config.get("cheat_sheet_hold_ms")

    def start_listening(self):
        self.k_listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.k_listener.start()
        self.m_listener = mouse.Listener(
            on_click=self.on_click, 
            on_scroll=self.on_scroll
        )
        self.m_listener.start()
        self.hold_timer.start()

    def stop_listening(self):
        if self.k_listener: self.k_listener.stop()
        if self.m_listener: self.m_listener.stop()
        self.hold_timer.stop()

    def check_hold(self):
        if self.pressed_keys:
            text, _ = self._build_key_text()
            if text: self.hold_signal.emit(text)
        
    def _get_active_modifiers_text(self):
        modifiers_order = ['Win', 'Ctrl', 'Alt', 'Shift']
        return [m for m in modifiers_order if m in self.pressed_keys]
    
    def _apply_alias(self, raw_name): return self.cfg_aliases.get(raw_name, raw_name)

    def on_click(self, x, y, button, pressed):
        try:
            btn_name = str(button).replace('Button.', '')
            self.halo_click_signal.emit(btn_name, pressed)
            if pressed: self.pressed_mouse.add(btn_name)
            else:
                if btn_name in self.pressed_mouse: self.pressed_mouse.remove(btn_name)
            if not self.cfg_log_enabled: return 
            mods = self._get_active_modifiers_text()
            is_mod_active = len(mods) > 0
            prefix = "+".join(mods) + ("+" if mods else "")
            if btn_name == 'middle':
                if pressed: self.middle_press_pos = (x, y); return 
                else:
                    if self.middle_press_pos:
                        dx = x - self.middle_press_pos[0]; dy = y - self.middle_press_pos[1]
                        dist = math.sqrt(dx*dx + dy*dy); self.middle_press_pos = None
                        raw_action = "Middle Click"; should_log = self.cfg_log_middle_click
                        if dist > self.cfg_drag_threshold: raw_action = "Middle Drag"; should_log = self.cfg_log_middle_drag
                        if should_log or is_mod_active: self.mouse_signal.emit(prefix + self._apply_alias(raw_action), is_mod_active)
                    return
            if pressed:
                should_log = False; raw_text = ""; curr_time = time.time()
                if btn_name == 'left':
                    is_double = (curr_time - self.last_left_click_time) < self.cfg_double_click_timeout
                    self.last_left_click_time = curr_time
                    if is_double and self.cfg_log_left_double: raw_text = "Double Click"; should_log = True
                    elif self.cfg_log_left_click or is_mod_active: raw_text = "Left Click"; should_log = True
                elif btn_name == 'right':
                    raw_text = "Right Click"
                    if self.cfg_log_right_click or is_mod_active: should_log = True
                elif btn_name not in ['middle']: raw_text = f"Button {btn_name}"; should_log = True
                if should_log and raw_text: self.mouse_signal.emit(prefix + self._apply_alias(raw_text), is_mod_active)
        except Exception:
            logging.error(f"Click Error: {traceback.format_exc()}")

    def on_scroll(self, x, y, dx, dy):
        try:
            now = time.time()
            if now - self.last_scroll_time < 0.03:
                return
            self.last_scroll_time = now

            self.halo_scroll_signal.emit(dy)
            if not self.cfg_log_enabled: return
            mods = self._get_active_modifiers_text()
            is_mod_active = len(mods) > 0
            if self.cfg_log_scroll or is_mod_active:
                prefix = "+".join(mods) + ("+" if mods else "")
                direction = "Scroll Up" if dy > 0 else "Scroll Down"
                self.mouse_signal.emit(prefix + self._apply_alias(direction), is_mod_active)
        except Exception:
            logging.error(f"Scroll Error: {traceback.format_exc()}")

    def _normalize_key(self, key):
        try:
            if hasattr(key, 'vk') and key.vk == 229: return None
            k_str = ""
            if hasattr(key, 'char') and key.char:
                code = ord(key.char)
                if code < 32:
                    if 1 <= code <= 26: k_str = chr(code + 64).upper()
                    else:
                        if hasattr(key, 'vk') and key.vk:
                            if 48 <= key.vk <= 57 or 65 <= key.vk <= 90: k_str = chr(key.vk)
                else: k_str = key.char.upper()
            else:
                k_str = str(key).replace('Key.', '')
                if k_str.startswith('<') and k_str.endswith('>'):
                    vk = int(k_str.strip('<>'))
                    if 96 <= vk <= 105: k_str = str(vk - 96)
                    elif 48 <= vk <= 57 or 65 <= vk <= 90: k_str = chr(vk)
                    else: return None
            if k_str in self.key_map_normalize: return self.key_map_normalize[k_str]
            if len(k_str) > 1 and k_str.isupper(): k_str = k_str.title()
            return k_str
        except: return None

    def _get_key_id(self, key): return key.vk if hasattr(key, 'vk') and key.vk is not None else key

    def _build_key_text(self):
        mods = self._get_active_modifiers_text()
        others = sorted([x for x in self.pressed_keys if x not in mods])
        if 'Shift' in mods and len(others) == 1:
            key_char = others[0]
            shifted_symbols = "!\"#$%&'()=~|`{+*}<>?_" 
            if key_char in shifted_symbols: mods.remove('Shift')
        parts = mods + others
        if not parts: return None, False
        is_char_input = (len(mods) == 0)
        if not self.cfg_show_single_keys and is_char_input and len(parts) == 1:
            allowed = ['Enter', 'Tab', 'Space', 'Esc', 'Del', 'Backspace', '↑', '↓', '←', '→', 'PrtSc']
            if parts[0] not in allowed and len(parts[0]) == 1: return None, False
        return "+".join(parts), is_char_input

    @pyqtSlot(bool)
    def _handle_timer_ctrl(self, start):
        if start: self.cheat_hold_timer.start(self.cfg_cheat_hold_ms)
        else: self.cheat_hold_timer.stop()

    def on_cheat_hold_complete(self):
        self.overlay_active = True
        self.just_activated_by_hold = True
        self.cheat_overlay_signal.emit(True)

    def on_press(self, key):
        try:
            k = self._normalize_key(key)
            if not k: return
            kid = self._get_key_id(key)
            if kid in self.active_keys: return 
            self.active_keys[kid] = k; self.pressed_keys.add(k)
            if k == 'Esc' and self.overlay_active:
                self._timer_ctrl_signal.emit(False); self.cheat_overlay_signal.emit(False); self.overlay_active = False; return
            if self.cfg_cheat_enabled and k.upper() == self.cfg_cheat_key:
                if not self.overlay_active: self._timer_ctrl_signal.emit(True)
            if self.cfg_log_enabled:
                text, is_char_input = self._build_key_text()
                if not text: return
                item = config.get_shortcut_item(text)
                desc = item.get("desc") if item and self.cfg_cascadeur_mode else ""
                show_in_log = item.get("show_in_log", True) if item else True
                if show_in_log: self.key_signal.emit(text, desc, is_char_input)
        except Exception:
             logging.error(f"Key Press Error: {traceback.format_exc()}")

    def on_release(self, key):
        try:
            kid = self._get_key_id(key)
            released_k = None
            if kid in self.active_keys:
                released_k = self.active_keys[kid]
                if released_k in self.pressed_keys: self.pressed_keys.remove(released_k)
                del self.active_keys[kid]
            else:
                k = self._normalize_key(key)
                if k and k in self.pressed_keys: released_k = k; self.pressed_keys.remove(k)
            if released_k and self.cfg_cheat_enabled and released_k.upper() == self.cfg_cheat_key:
                self._timer_ctrl_signal.emit(False) 
                if self.just_activated_by_hold: self.just_activated_by_hold = False; return
                if self.overlay_active: self.cheat_overlay_signal.emit(False); self.overlay_active = False
                else: self.cheat_window_signal.emit()
        except Exception:
             logging.error(f"Key Release Error: {traceback.format_exc()}")

# --- チートシート (Window) ---
class CheatSheetWindow(QWidget):
    EDGE_NONE = 0; EDGE_LEFT = 1; EDGE_TOP = 2; EDGE_RIGHT = 3; EDGE_BOTTOM = 4
    EDGE_TOP_LEFT = 5; EDGE_TOP_RIGHT = 6; EDGE_BOTTOM_LEFT = 7; EDGE_BOTTOM_RIGHT = 8
    GRIP_SIZE = 5

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        saved_geo = config.get("cheat_window_geo")
        if saved_geo and len(saved_geo) == 4:
            self.setGeometry(*saved_geo)
        else:
            self.resize(500, 600)
        
        self.is_resizing = False
        self.resize_edge = self.EDGE_NONE
        self.is_moving = False
        self.drag_start_pos = QPoint()
        self.drag_start_global_pos = QPoint()
        self.window_start_geo = QRect()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0) 
        
        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(30)
        
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 0, 0, 0)
        
        self.window_title_lbl = QLabel(config.tr("ui.window.cheat", "417 KeyGuide (Cheat Sheet)"))
        self.window_title_lbl.setStyleSheet("color: white; font-weight: bold; background: transparent;")
        title_layout.addWidget(self.window_title_lbl)
        title_layout.addStretch()
        
        self.btn_close = QPushButton("×") # ハードコードに変更
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.setStyleSheet("QPushButton { background-color: transparent; color: white; border: none; font-size: 16px; font-weight: bold; } QPushButton:hover { background-color: #cc0000; }")
        self.btn_close.clicked.connect(self.close)
        title_layout.addWidget(self.btn_close)
        self.main_layout.addWidget(self.title_bar)
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0) 
        
        self.container = QFrame()
        self.container.setObjectName("container")
        self.cont_layout = QVBoxLayout(self.container)
        self.cont_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.addWidget(self.container)
        
        self.lbl_title = QLabel("Shortcuts")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cont_layout.addWidget(self.lbl_title)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(SCROLLBAR_STYLESHEET + "QScrollArea { background: transparent; border: none; }")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.scroll_content)
        self.cont_layout.addWidget(self.scroll)
        
        self.main_layout.addWidget(self.content_widget)

        config.changed_signal.connect(self.update_content)
        # 言語変更時にタイトル更新
        config.language_changed_signal.connect(self.update_content)
        self.update_content()
        self.installEventFilter(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        bg_col = QColor(config.get("cheat_sheet_bg_color"))
        radius = config.get("border_radius")
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_col)
        painter.drawRoundedRect(self.rect(), radius, radius)
        
        if config.get("cheat_window_border_enabled"):
            b_col = QColor(config.get("cheat_window_border_color"))
            pen = QPen(b_col)
            pen.setWidth(2) 
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            draw_rect = self.rect().adjusted(1, 1, -1, -1)
            painter.drawRoundedRect(draw_rect, radius, radius)

    def showEvent(self, event):
        super().showEvent(event)
        widgets = self.findChildren(QWidget)
        for widget in widgets:
            widget.setMouseTracking(True)
            widget.removeEventFilter(self) 
            widget.installEventFilter(self)

    def hideEvent(self, event):
        if not self.isMinimized():
            rect = self.geometry().getRect()
            config.set("cheat_window_geo", rect, record_history=False)
        super().hideEvent(event)

    def closeEvent(self, event):
        self.hide()
        event.accept()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.HoverMove or event.type() == QEvent.Type.MouseMove:
            global_pos = event.globalPosition().toPoint()
            local_pos = self.mapFromGlobal(global_pos)
            if self.is_resizing: self._handle_resize(global_pos); return True
            elif self.is_moving: self.move(global_pos - self.drag_start_pos); return True
            else: self._update_cursor(self._hit_test(local_pos))
        elif event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                if obj == self.btn_close: return False
                global_pos = event.globalPosition().toPoint()
                local_pos = self.mapFromGlobal(global_pos)
                edge = self._hit_test(local_pos)
                if edge != self.EDGE_NONE:
                    self.is_resizing = True; self.resize_edge = edge; self.drag_start_global_pos = global_pos; self.window_start_geo = self.geometry(); return True
                elif self.title_bar.geometry().contains(local_pos):
                    self.is_moving = True; self.drag_start_pos = global_pos - self.pos(); return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self.is_resizing or self.is_moving:
                self.is_resizing = False; self.is_moving = False; self.resize_edge = self.EDGE_NONE
                self._update_cursor(self._hit_test(self.mapFromGlobal(event.globalPosition().toPoint())))
                return True
        return super().eventFilter(obj, event)

    def _hit_test(self, pos):
        rect = self.rect(); w, h = rect.width(), rect.height(); x, y = pos.x(), pos.y(); grip = self.GRIP_SIZE
        if x < grip and y < grip: return self.EDGE_TOP_LEFT
        if x > w - grip and y < grip: return self.EDGE_TOP_RIGHT
        if x < grip and y > h - grip: return self.EDGE_BOTTOM_LEFT
        if x > w - grip and y > h - grip: return self.EDGE_BOTTOM_RIGHT
        if x < grip: return self.EDGE_LEFT
        if x > w - grip: return self.EDGE_RIGHT
        if y < grip: return self.EDGE_TOP
        if y > h - grip: return self.EDGE_BOTTOM
        return self.EDGE_NONE

    def _update_cursor(self, edge):
        cursors = {self.EDGE_TOP_LEFT: Qt.CursorShape.SizeFDiagCursor, self.EDGE_BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
                   self.EDGE_TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor, self.EDGE_BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
                   self.EDGE_LEFT: Qt.CursorShape.SizeHorCursor, self.EDGE_RIGHT: Qt.CursorShape.SizeHorCursor,
                   self.EDGE_TOP: Qt.CursorShape.SizeVerCursor, self.EDGE_BOTTOM: Qt.CursorShape.SizeVerCursor}
        self.setCursor(cursors.get(edge, Qt.CursorShape.ArrowCursor))

    def _handle_resize(self, global_mouse_pos):
        geo = self.window_start_geo
        dx = global_mouse_pos.x() - self.drag_start_global_pos.x(); dy = global_mouse_pos.y() - self.drag_start_global_pos.y()
        new_geo = QRect(geo); min_w = 200; min_h = 100
        if self.resize_edge == self.EDGE_LEFT: new_geo.setLeft(geo.left() + dx)
        elif self.resize_edge == self.EDGE_RIGHT: new_geo.setRight(geo.right() + dx)
        elif self.resize_edge == self.EDGE_TOP: new_geo.setTop(geo.top() + dy)
        elif self.resize_edge == self.EDGE_BOTTOM: new_geo.setBottom(geo.bottom() + dy)
        elif self.resize_edge == self.EDGE_TOP_LEFT: new_geo.setTopLeft(QPoint(geo.left() + dx, geo.top() + dy))
        elif self.resize_edge == self.EDGE_TOP_RIGHT: new_geo.setTopRight(QPoint(geo.right() + dx, geo.top() + dy))
        elif self.resize_edge == self.EDGE_BOTTOM_LEFT: new_geo.setBottomLeft(QPoint(geo.left() + dx, geo.bottom() + dy))
        elif self.resize_edge == self.EDGE_BOTTOM_RIGHT: new_geo.setBottomRight(QPoint(geo.right() + dx, geo.bottom() + dy))
        
        if new_geo.width() < min_w:
            if self.resize_edge in (self.EDGE_LEFT, self.EDGE_TOP_LEFT, self.EDGE_BOTTOM_LEFT): new_geo.setLeft(new_geo.right() - min_w + 1)
            else: new_geo.setWidth(min_w)
        if new_geo.height() < min_h:
            if self.resize_edge in (self.EDGE_TOP, self.EDGE_TOP_LEFT, self.EDGE_TOP_RIGHT): new_geo.setTop(new_geo.bottom() - min_h + 1)
            else: new_geo.setHeight(min_h)
        self.setGeometry(new_geo)

    def toggle_visibility(self):
        if self.isVisible(): self.close()
        else:
            self.update_content()
            self.showNormal() 
            self.raise_(); self.activateWindow()
            widgets = self.findChildren(QWidget)
            for widget in widgets: widget.setMouseTracking(True); widget.removeEventFilter(self); widget.installEventFilter(self)

    def update_content(self, key=None, val=None):
        if not self.isVisible() and key is not None and key != "language": return

        # UIテキスト更新
        self.window_title_lbl.setText(config.tr("ui.window.cheat", "417 KeyGuide (Cheat Sheet)"))
        self.btn_close.setText("×") # ハードコードに変更

        self.title_bar.setStyleSheet("background: transparent; border: none;")
        self.container.setStyleSheet("#container { background: transparent; border: none; }")
        
        self.update()

        base_size = config.get("cheat_sheet_font_size") or 14
        title_font = QFont("Arial", base_size + 6, QFont.Weight.Bold)
        self.lbl_title.setFont(title_font)
        self.lbl_title.setStyleSheet(f"color: {config.get('cheat_sheet_header_color')}; background: transparent;")
        
        if self.scroll_content.layout() is None: layout = QGridLayout(self.scroll_content); layout.setContentsMargins(0, 0, 0, 0)
        else:
             layout = self.scroll_content.layout()
             while layout.count(): item = layout.takeAt(0); (item.widget().deleteLater() if item.widget() else None)
        
        spacing = config.get("cheat_sheet_spacing")
        layout.setHorizontalSpacing(spacing)
        layout.setVerticalSpacing(5)

        font_header = QFont("Arial", base_size + 4, QFont.Weight.Bold)
        font_key = QFont("Arial", base_size, QFont.Weight.Bold)
        font_desc = QFont("Arial", base_size)

        col_style_header = f"color: {config.get('cheat_sheet_header_color')}; margin-top: 8px; background: transparent;"
        col_style_key = f"color: {config.get('cheat_sheet_key_color')}; background: transparent;"
        col_style_desc = f"color: {config.get('cheat_sheet_desc_color')}; background: transparent;"

        min_w_key = config.get("cheat_sheet_col_width_key")
        min_w_desc = config.get("cheat_sheet_col_width_desc")
        align_val = config.get("cheat_sheet_key_align")
        key_align = (Qt.AlignmentFlag.AlignRight if align_val == 1 else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
        do_wrap = config.get("cheat_sheet_word_wrap")

        shortcuts = config.get("shortcuts_list")
        items_to_show = [i for i in shortcuts if i.get("enabled") and i.get("show_in_cheat", True)]
        cr = 0
        for item in items_to_show:
            if item.get("type") == "header":
                l = QLabel(item.get("combo")); l.setFont(font_header); l.setStyleSheet(col_style_header); layout.addWidget(l, cr, 0, 1, 2)
            else:
                k = QLabel(item.get("combo")); k.setFont(font_key); k.setStyleSheet(col_style_key); k.setAlignment(key_align); k.setMinimumWidth(min_w_key)
                d = QLabel(item.get("desc")); d.setFont(font_desc); d.setStyleSheet(col_style_desc); d.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter); d.setWordWrap(do_wrap); d.setMinimumWidth(min_w_desc)
                layout.addWidget(k, cr, 0); layout.addWidget(d, cr, 1)
            cr += 1
        layout.setColumnStretch(0, 0); layout.setColumnStretch(1, 1); layout.setRowStretch(layout.rowCount(), 1)

# --- チートシート (Overlay) ---
class CheatSheetOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_container = QWidget()
        self.center_container.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.center_container)
        self.main_layout.addWidget(self.center_container)
        config.changed_signal.connect(self.refresh_style)
        config.language_changed_signal.connect(self.refresh_style)

    def refresh_style(self, key=None, val=None): self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        bg_col = QColor(config.get("cheat_sheet_fullscreen_bg_color"))
        painter.fillRect(self.rect(), bg_col)
        key_name = config.get('cheat_sheet_key').upper()
        hint_format = config.tr("ui.cheat.close_hint", "(【{}】で閉じる)")
        hint_text = hint_format.format(key_name)
        painter.setPen(QColor(255, 255, 255, 200))
        base_size = config.get("cheat_sheet_fullscreen_font_size")
        font = QFont("Arial", base_size + 10, QFont.Weight.Bold)
        painter.setFont(font)
        rect = self.rect(); margin_x = 40; margin_y = 40
        draw_rect = rect.adjusted(0, 0, -margin_x, -margin_y)
        painter.drawText(draw_rect, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, hint_text)

    def build_layout(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
            elif child.layout(): pass
        shortcuts = config.get("shortcuts_list")
        items = [i for i in shortcuts if i.get("enabled") and i.get("show_in_cheat", True)]
        if not items: return
        screen_geo = QApplication.primaryScreen().geometry()
        screen_w = screen_geo.width(); screen_h = screen_geo.height()
        margin_v = 100; margin_h = 100
        available_h = screen_h - (margin_v * 2); available_w = screen_w - (margin_h * 2)
        base_size = config.get("cheat_sheet_fullscreen_font_size")
        max_start_size = base_size; min_size = 9
        min_w_key = config.get("cheat_sheet_fullscreen_min_key"); min_w_desc = config.get("cheat_sheet_fullscreen_min_desc")
        spacing = config.get("cheat_sheet_spacing")
        final_font_size = min_size; final_cols = 1; final_items_per_col = len(items)

        for size in range(max_start_size, min_size - 1, -1):
            font = QFont("Arial", size); fm = QFontMetrics(font)
            line_height = fm.height() + 8 
            items_per_col = max(1, int(available_h / line_height))
            num_cols = math.ceil(len(items) / items_per_col)
            col_widths = [0] * num_cols
            for idx, item in enumerate(items):
                col_idx = idx // items_per_col
                text_w_key = fm.horizontalAdvance(item.get("combo")); w_combo = max(text_w_key, min_w_key)
                text_w_desc = fm.horizontalAdvance(item.get("desc")); w_desc = max(text_w_desc, min_w_desc)
                total_w = w_combo + spacing + w_desc 
                if total_w > col_widths[col_idx]: col_widths[col_idx] = total_w
            total_required_width = sum(col_widths) + (num_cols - 1) * 80 
            if total_required_width <= available_w:
                final_font_size = size; final_cols = num_cols; final_items_per_col = items_per_col; break
        
        font_header = QFont("Arial", final_font_size + 4, QFont.Weight.Bold)
        font_key = QFont("Arial", final_font_size, QFont.Weight.Bold)
        font_desc = QFont("Arial", final_font_size)
        col_header = config.get("cheat_sheet_header_color"); col_key = config.get("cheat_sheet_key_color"); col_desc = config.get("cheat_sheet_desc_color")
        align_val = config.get("cheat_sheet_key_align")
        key_align = (Qt.AlignmentFlag.AlignRight if align_val == 1 else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
        self.grid_layout.setSpacing(0); self.grid_layout.setVerticalSpacing(4)
        
        for idx, item in enumerate(items):
            col_idx = idx // final_items_per_col; row_idx = idx % final_items_per_col; base_grid_col = col_idx * 4 
            if item.get("type") == "header":
                lbl = QLabel(item.get("combo")); lbl.setFont(font_header); lbl.setStyleSheet(f"color: {col_header}; margin-top: 5px; background: transparent;")
                self.grid_layout.addWidget(lbl, row_idx, base_grid_col, 1, 3) 
            else:
                k = QLabel(item.get("combo")); k.setFont(font_key); k.setStyleSheet(f"color: {col_key}; background: transparent;"); k.setAlignment(key_align); k.setMinimumWidth(min_w_key)
                d = QLabel(item.get("desc")); d.setFont(font_desc); d.setStyleSheet(f"color: {col_desc}; background: transparent;"); d.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter); d.setMinimumWidth(min_w_desc)
                self.grid_layout.addWidget(k, row_idx, base_grid_col)
                sp_widget = QWidget(); sp_widget.setFixedWidth(spacing); sp_widget.setStyleSheet("background: transparent;")
                self.grid_layout.addWidget(sp_widget, row_idx, base_grid_col + 1)
                self.grid_layout.addWidget(d, row_idx, base_grid_col + 2)
            if col_idx < final_cols - 1 and row_idx == 0:
                col_spacer = QFrame(); col_spacer.setFixedWidth(80); col_spacer.setStyleSheet("background: transparent;")
                self.grid_layout.addWidget(col_spacer, 0, base_grid_col + 3, final_items_per_col, 1)

    def show_overlay(self, show):
        if show:
            screen = QApplication.primaryScreen().geometry()
            self.setGeometry(screen)
            self.build_layout()
            self.show()
        else: self.hide()

# --- 画面位置指定 ---
class PositionSelector(QWidget):
    positionSelected = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(QApplication.primaryScreen().virtualGeometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.current_mouse_pos = QPoint(0,0)
    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        box_w = config.get("window_width"); est_height = config.get("max_stack") * 60 
        x = self.current_mouse_pos.x(); y = self.current_mouse_pos.y()
        painter.setPen(QPen(QColor(0, 255, 0), 2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 255, 0, 50)); painter.drawRect(QRect(x, y - est_height, box_w, est_height))
        painter.setBrush(Qt.GlobalColor.red); painter.setPen(Qt.PenStyle.NoPen); painter.drawEllipse(QPoint(x, y), 5, 5)
        painter.setPen(Qt.GlobalColor.white)
        font = QFont(); font.setPointSize(24); font.setBold(True); painter.setFont(font)
        rect_msg = QRect(0, 100, self.width(), 100)
        painter.drawText(rect_msg, Qt.AlignmentFlag.AlignCenter, config.tr("ui.gen.pos_guide_1", "ログ表示範囲の【左下】をクリック"))
        font.setPointSize(18); painter.setFont(font)
        rect_sub = QRect(0, 160, self.width(), 100)
        painter.drawText(rect_sub, Qt.AlignmentFlag.AlignCenter, config.tr("ui.gen.pos_guide_2", "(Escキーでキャンセル)"))
    def mouseMoveEvent(self, event): self.current_mouse_pos = event.pos(); self.update()
    def mousePressEvent(self, event):
        pos = event.globalPosition().toPoint(); config.set("pos_x", pos.x()); config.set("pos_y", pos.y())
        self.positionSelected.emit(); self.close()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.positionSelected.emit(); self.close()

# --- カラー＋不透明度 コントロール ---
class ColorOpacityControl(QWidget):
    def __init__(self, key, label_text):
        super().__init__()
        self.key = key
        self.layout = QHBoxLayout(self); self.layout.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton(label_text); self.btn.clicked.connect(self.pick_color); self.btn.setFixedWidth(140) 
        self.preview = QLabel(); self.preview.setFixedSize(24, 24); self.preview.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain); self.preview.setAutoFillBackground(True)
        self.sb_opacity = NoScrollSpinBox(); self.sb_opacity.setRange(0, 100); self.sb_opacity.setFixedWidth(100) 
        self.slider = NoScrollSlider(Qt.Orientation.Horizontal); self.slider.setRange(0, 100); self.slider.setFixedWidth(150)
        self.slider.setStyleSheet("QSlider::groove:horizontal { border: 1px solid #444444; height: 4px; background: #444444; border-radius: 2px; } QSlider::sub-page:horizontal { background: #dddddd; border-radius: 2px; } QSlider::handle:horizontal { background: #ffffff; border: 1px solid #999999; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; } QSlider::handle:horizontal:hover { background: #ffffff; border-color: #ffffff; }")
        self.slider.valueChanged.connect(self.sb_opacity.setValue); self.sb_opacity.valueChanged.connect(self.slider.setValue)
        self.sb_opacity.editingFinished.connect(self.save_opacity); self.slider.sliderReleased.connect(self.save_opacity)
        self.layout.addWidget(self.preview); self.layout.addWidget(self.btn); self.layout.addSpacing(15) 
        self.layout.addWidget(QLabel(config.tr("ui.common.opacity", "不透明度:"))); self.layout.addWidget(self.sb_opacity); self.layout.addWidget(self.slider); self.layout.addStretch()
        self.update_ui_from_config()
    def setEnabled(self, enabled): super().setEnabled(enabled); self.btn.setEnabled(enabled); self.sb_opacity.setEnabled(enabled); self.slider.setEnabled(enabled)
    def update_ui_from_config(self):
        col_str = config.get(self.key); c = QColor(col_str); c_opaque = QColor(c); c_opaque.setAlpha(255)
        self.preview.setStyleSheet(f"background-color: {c_opaque.name()}; border: 1px solid gray;")
        opacity_percent = round((c.alpha() / 255.0) * 100)
        self.sb_opacity.blockSignals(True); self.slider.blockSignals(True)
        self.sb_opacity.setValue(opacity_percent); self.slider.setValue(opacity_percent)
        self.sb_opacity.blockSignals(False); self.slider.blockSignals(False)
    def pick_color(self):
        initial = QColor(config.get(self.key))
        c = QColorDialog.getColor(initial, self, config.tr("ui.common.color", "色を選択"), QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid(): hex_argb = c.name(QColor.NameFormat.HexArgb); config.set(self.key, hex_argb)
    def save_opacity(self):
        current_hex = config.get(self.key); c = QColor(current_hex); new_opacity = self.sb_opacity.value()
        new_alpha = int(round((new_opacity / 100.0) * 255)); c.setAlpha(new_alpha); new_hex = c.name(QColor.NameFormat.HexArgb); config.set(self.key, new_hex)

# --- 軽量な区切り線 (PaintEventで描画) ---
class SeparatorLine(QWidget):
    def __init__(self): super().__init__(); self.setFixedHeight(10); self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    def paintEvent(self, event):
        if not config.get("separator_enabled"): return
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = config.get("separator_width"); color = QColor(config.get("separator_color")); y = self.height() / 2
        if config.get("sep_shadow_enabled"):
            shadow_color = QColor(config.get("sep_shadow_color")); offset_x = config.get("sep_shadow_offset_x"); offset_y = config.get("sep_shadow_offset_y")
            shadow_pen = QPen(shadow_color, width); shadow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(shadow_pen); painter.drawLine(int(offset_x), int(y + offset_y), int(self.width() + offset_x), int(y + offset_y))
        pen = QPen(color, width); pen.setCapStyle(Qt.PenCapStyle.RoundCap); painter.setPen(pen); painter.drawLine(0, int(y), self.width(), int(y))

# --- ラベル描画 ---
class OutlinedLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent); self.outline_enabled = False; self.outline_width = 1; self.outline_color = QColor("black")
        self.text_color = QColor("white"); self.shadow_enabled = False; self.shadow_color = QColor("black"); self.shadow_offset = QPoint(2, 2)
        self.use_custom_style = False; self.setStyleSheet("background: transparent;")
    def set_custom_style(self, enabled, o_enabled, o_width, o_color, t_color, s_enabled=False, s_color=None, s_offset_x=0, s_offset_y=0):
        self.use_custom_style = enabled; self.outline_enabled = o_enabled; self.outline_width = o_width
        self.outline_color = QColor(o_color); self.text_color = QColor(t_color)
        self.shadow_enabled = s_enabled; self.shadow_color = QColor(s_color) if s_color else QColor("black")
        self.shadow_offset = QPoint(s_offset_x, s_offset_y); self.update()
    def paintEvent(self, event):
        if not self.use_custom_style: super().paintEvent(event); return
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); font = self.font(); painter.setFont(font); metrics = QFontMetrics(font)
        y = (self.height() + metrics.ascent() - metrics.descent()) // 2; path = QPainterPath(); path.addText(0, y, font, self.text())
        if self.shadow_enabled:
            painter.save(); painter.translate(self.shadow_offset); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(self.shadow_color); painter.drawPath(path); painter.restore()
        if self.outline_enabled and self.outline_width > 0:
            pen = QPen(self.outline_color, self.outline_width * 2); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(self.text_color); painter.drawPath(path)

# --- キーアイテム ---
class KeyItem(QWidget):
    def __init__(self, text, desc, is_mod_pressed=False, is_char_input=False, parent=None):
        super().__init__(parent)
        self.raw_text = text; self.count = 1; self.is_mod_pressed = is_mod_pressed
        self.main_layout = QVBoxLayout(self); self.main_layout.setContentsMargins(0, 0, 0, 0); self.main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.frame = QFrame(); self.frame.setObjectName("keyFrame"); self.frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.content_layout = QVBoxLayout(self.frame); self.content_layout.setSpacing(2)
        self.key_row_widget = QWidget(); self.key_row_widget.setStyleSheet("background: transparent;")
        self.key_row_layout = QHBoxLayout(self.key_row_widget); self.key_row_layout.setContentsMargins(0,0,0,0); self.key_row_layout.setSpacing(4)
        mod_text, icon_pixmap, main_text = self.parse_content(text, is_mod_pressed)
        self.lbl_mods = None; self.icon_lbl = None; self.lbl_main = None
        if mod_text: self.lbl_mods = OutlinedLabel(mod_text); self.key_row_layout.addWidget(self.lbl_mods)
        if icon_pixmap:
            self.icon_lbl = QLabel(); self.icon_lbl.setPixmap(icon_pixmap); self.icon_lbl.setFixedSize(config.get("icon_size"), config.get("icon_size")); self.icon_lbl.setScaledContents(True); self.icon_lbl.setStyleSheet("background: transparent;")
            self.key_row_layout.addWidget(self.icon_lbl)
        if main_text: self.lbl_main = OutlinedLabel(main_text); self.key_row_layout.addWidget(self.lbl_main)
        self.content_layout.addWidget(self.key_row_widget)
        self.lbl_desc = None; self.line = None
        if not desc and config.get("cascadeur_mode"): desc = config.get_shortcut_desc(text)
        if desc and config.get("show_desc"):
            if config.get("separator_enabled"): self.line = SeparatorLine(); self.content_layout.addWidget(self.line)
            self.lbl_desc = OutlinedLabel(desc); self.content_layout.addWidget(self.lbl_desc)
        self.main_layout.addWidget(self.frame)
        self.opacity_effect = QGraphicsOpacityEffect(self); self.opacity_effect.setOpacity(1.0); self.setGraphicsEffect(self.opacity_effect)
        self.start_ts = time.time(); self.timer = QTimer(self); self.timer.timeout.connect(self.update_state); self.timer.start(30)
        self.update_style(); self.update_font(); config.changed_signal.connect(self.on_config_changed)
    def parse_content(self, text, is_mod):
        if is_mod: mode = config.get("mod_mouse_display_mode")
        else: mode = config.get("log_display_mode")
        icon_paths = config.get("icon_paths"); aliases = config.get("mouse_aliases"); target_key = None
        std_keys = [("Right Click", "right"), ("Left Click", "left"), ("Double Click", "left"), ("Middle Click", "middle"), ("Middle Drag", "middle"), ("Scroll", "middle")]
        for std_name, key_type in std_keys:
            alias_val = aliases.get(std_name, std_name)
            if alias_val in text: target_key = key_type; break
        pixmap = None; mod_part = ""; main_part = text
        if target_key and icon_paths.get(target_key) and os.path.exists(icon_paths[target_key]):
            if mode > 0:
                pixmap = QPixmap(icon_paths[target_key])
                if "+" in text:
                    parts = text.rsplit("+", 1)
                    if len(parts) == 2: mod_part = parts[0] + "+"; main_part = parts[1]
                    else: mod_part = ""; main_part = text
                else: mod_part = ""; main_part = text
                if mode == 2: main_part = ""
        if mod_part == text and main_part == text: mod_part = ""
        return mod_part, pixmap, main_part
    def increment_count(self):
        self.count += 1; _, _, base_main = self.parse_content(self.raw_text, self.is_mod_pressed)
        disp_text = f"{base_main} x{self.count}" if base_main else f"x{self.count}"
        if self.lbl_main: self.lbl_main.setText(disp_text)
        elif not self.lbl_main: self.lbl_main = OutlinedLabel(disp_text); self.key_row_layout.addWidget(self.lbl_main); self.update_style()
        self.reset_timer()
    def on_config_changed(self, key, value): self.update_style(); self.update_font()
    def reset_timer(self): self.start_ts = time.time(); self.opacity_effect.setOpacity(1.0); self.timer.start(30)
    def update_style(self):
        bg_col = QColor(config.get("bg_color")); bg_css = f"rgba({bg_col.red()},{bg_col.green()},{bg_col.blue()},{bg_col.alpha()/255:.2f})"
        self.frame.setStyleSheet(f"#keyFrame {{ background-color: {bg_css}; border: {config.get('border_width')}px solid {config.get('border_color')}; border-radius: {config.get('border_radius')}px; }} QLabel {{ background: transparent; }}")
        pad_x = config.get("padding_x"); pad_y = config.get("padding_y"); self.frame.layout().setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        def apply_style(lbl, key_prefix="text"):
            if not lbl: return
            lbl.set_custom_style(True, config.get(f"{key_prefix}_outline_enabled"), config.get(f"{key_prefix}_outline_width"), config.get(f"{key_prefix}_outline_color"), config.get(f"{key_prefix}_color"), config.get(f"{key_prefix}_shadow_enabled"), config.get(f"{key_prefix}_shadow_color"), config.get(f"{key_prefix}_shadow_offset_x"), config.get(f"{key_prefix}_shadow_offset_y"))
        apply_style(self.lbl_main, "text"); apply_style(self.lbl_mods, "text")
        if self.lbl_desc:
            self.lbl_desc.set_custom_style(True, config.get("desc_outline_enabled"), config.get("desc_outline_width"), config.get("desc_outline_color"), config.get("desc_text_color"), config.get("desc_shadow_enabled"), config.get("desc_shadow_color"), config.get("desc_shadow_offset_x"), config.get("desc_shadow_offset_y"))
        if self.line:
            sep_w = config.get("separator_width"); sep_sp = config.get("separator_spacing"); self.line.setFixedHeight(sep_w + sep_sp * 2); self.line.update() 
        self.update()
    def update_font(self):
        font = QFont(config.get("font_family"), config.get("font_size")); font.setBold(config.get("font_bold")); font.setItalic(config.get("font_italic")); font.setUnderline(config.get("font_underline")); font.setStrikeOut(config.get("font_strikeout"))
        if self.lbl_main: self.lbl_main.setFont(font)
        if self.lbl_mods: self.lbl_mods.setFont(font)
        if self.lbl_desc:
            desc_font = QFont(config.get("desc_font_family"), config.get("desc_font_size")); desc_font.setBold(config.get("desc_font_bold")); desc_font.setItalic(config.get("desc_font_italic")); desc_font.setUnderline(config.get("desc_font_underline")); desc_font.setStrikeOut(config.get("desc_font_strikeout")); self.lbl_desc.setFont(desc_font)
    def update_state(self):
        elapsed = (time.time() - self.start_ts) * 1000; disp = config.get("display_time"); fade = config.get("fade_duration")
        time_opacity = 1.0
        if elapsed > disp:
            if elapsed < disp + fade: time_opacity = 1.0 - ((elapsed - disp) / fade)
            else: time_opacity = 0.0; self.timer.stop()
        prox_opacity = 1.0
        if config.get("item_proximity_enabled") and self.isVisible():
            cursor_pos = QCursor.pos(); center_glob = self.mapToGlobal(self.rect().center()); dist = math.sqrt((cursor_pos.x() - center_glob.x())**2 + (cursor_pos.y() - center_glob.y())**2); thresh = config.get("item_proximity_dist"); min_op = config.get("item_proximity_min_opacity")
            if dist < thresh: ratio = dist / thresh; prox_opacity = min_op + (1.0 - min_op) * ratio; prox_opacity = max(min_op, min(1.0, prox_opacity))
        self.opacity_effect.setOpacity(time_opacity * prox_opacity)

class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.layout = QVBoxLayout(self); self.layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft); self.layout.setSpacing(5)
        self.items = []; self.update_geometry(); config.changed_signal.connect(self.on_config_changed)
    def on_config_changed(self, key, value):
        if key in ["pos_x", "pos_y", "window_width"]: self.update_geometry()
    def update_geometry(self): x = config.get("pos_x"); y_bottom = config.get("pos_y"); w = config.get("window_width"); h = 1000; self.setGeometry(x, y_bottom - h, w, h)
    def add_key(self, text, desc="", is_mod_pressed=False, is_char_input=False):
        if self.items:
            last = self.items[-1]; last_parts = set(last.raw_text.split('+')); curr_parts = set(text.split('+'))
            if last_parts < curr_parts and last.opacity_effect.opacity() > 0: self.layout.removeWidget(last); last.deleteLater(); self.items.pop()
        if self.items:
            last = self.items[-1]
            if last.raw_text == text and last.opacity_effect.opacity() > 0:
                if (time.time() - last.start_ts) * 1000 < config.get("combo_timeout"):
                    if "Scroll" in text: last.reset_timer()
                    else: last.increment_count()
                    return
        item = KeyItem(text, desc, is_mod_pressed, is_char_input)
        self.items.append(item); self.layout.addWidget(item)
        while len(self.items) > config.get("max_stack"): old = self.items.pop(0); self.layout.removeWidget(old); old.deleteLater()
    def maintain_key(self, text):
        for item in reversed(self.items):
            try: 
                if item.raw_text == text: item.reset_timer(); return
            except: pass
    def clean_up(self):
        active_items = []
        for item in self.items:
            try:
                if item.opacity_effect.opacity() <= 0.01: self.layout.removeWidget(item); item.deleteLater()
                else: active_items.append(item)
            except: pass
        self.items = active_items

# --- マウスHalo (修正版: タイマーポーリング + ToolTip) ---
class MouseHalo(QWidget):
    def __init__(self):
        super().__init__()
        # 修正: ToolTipフラグでタスクバーより手前に表示
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.ToolTip | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.left_pressed = False; self.right_pressed = False; self.middle_pressed = False; self.scroll_dy = 0
        self.scroll_timer = QTimer(self); self.scroll_timer.setInterval(500); self.scroll_timer.timeout.connect(self.reset_scroll)
        
        self.pos_timer = QTimer(self)
        self.pos_timer.setInterval(16) # 約60FPS
        self.pos_timer.timeout.connect(self.update_pos)
        
        self.update_settings()
        config.changed_signal.connect(lambda k,v: self.update_settings())

    def update_settings(self):
        self.size_val = config.get("halo_size"); self.resize(self.size_val * 2 + 50, self.size_val * 2 + 50)
        self.base_color = QColor(config.get("halo_color")); self.l_color = QColor(config.get("click_left_color")); self.r_color = QColor(config.get("click_right_color"))
        self.m_color = QColor(config.get("click_middle_color")); self.s_arrow_color = QColor(config.get("scroll_arrow_color"))
        self.s_arrow_size = config.get("scroll_arrow_size"); self.symbol_scale = config.get("action_symbol_scale")
        self.offset_x = config.get("halo_offset_x"); self.offset_y = config.get("halo_offset_y")
        self.middle_sq_size = config.get("middle_click_square_size")
        
        if config.get("mouse_halo_enabled"):
            self.pos_timer.start()
            self.show()
        else:
            self.pos_timer.stop()
            self.hide()
            
        self.update()

    def update_pos(self):
        if not config.get("mouse_halo_enabled"):
            return
        
        cursor = QCursor.pos()
        self.move(cursor.x() - self.width() // 2 + self.offset_x, 
                  cursor.y() - self.height() // 2 + self.offset_y)
        
        if self.isHidden():
            self.show()
        self.raise_()

    def set_click(self, btn, pressed):
        if btn == 'left': self.left_pressed = pressed
        elif btn == 'right': self.right_pressed = pressed
        elif btn == 'middle': self.middle_pressed = pressed
        self.update()
    def set_scroll(self, dy): self.scroll_dy = dy; self.scroll_timer.start(); self.update()
    def reset_scroll(self): self.scroll_dy = 0; self.scroll_timer.stop(); self.update()
    def paintEvent(self, event):
        if not config.get("mouse_halo_enabled"): return
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() // 2; cy = self.height() // 2; r = self.size_val
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.base_color); p.drawEllipse(QPoint(cx, cy), r, r)
        if self.left_pressed: p.setBrush(self.l_color); p.drawPie(QRect(cx - r, cy - r, r*2, r*2), 90 * 16, 180 * 16)
        if self.right_pressed: p.setBrush(self.r_color); p.drawPie(QRect(cx - r, cy - r, r*2, r*2), 270 * 16, 180 * 16)
        if self.scroll_dy != 0:
            p.setBrush(self.s_arrow_color); arrow_s = int(self.s_arrow_size * self.symbol_scale)
            if self.scroll_dy > 0: p1=QPoint(cx,cy-arrow_s); p2=QPoint(cx-int(arrow_s/1.5),cy+int(arrow_s/2)); p3=QPoint(cx+int(arrow_s/1.5),cy+int(arrow_s/2))
            else: p1=QPoint(cx,cy+arrow_s); p2=QPoint(cx-int(arrow_s/1.5),cy-int(arrow_s/2)); p3=QPoint(cx+int(arrow_s/1.5),cy-int(arrow_s/2))
            p.drawPolygon(QPolygon([p1, p2, p3]))
        elif self.middle_pressed:
            p.setBrush(self.m_color); box_s = int(self.middle_sq_size * self.symbol_scale); h = box_s // 2; p.drawRect(cx - h, cy - h, box_s, box_s)

# --- カスタムツリーウィジェット ---
class NoNestTreeWidget(QTreeWidget):
    orderChanged = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
    def dropEvent(self, event):
        if event.source() == self:
            super().dropEvent(event)
            root = self.invisibleRootItem(); items_to_move = []
            def collect_items(parent_item):
                children = []
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i); children.append(child); children.extend(collect_items(child))
                return children
            all_items = []
            for i in range(root.childCount()):
                item = root.child(i); all_items.append(item); all_items.extend(collect_items(item))
            items_needed_moving = []
            iterator = QTreeWidgetItemIterator(self)
            while iterator.value():
                item = iterator.value()
                if item.parent() is not None: items_needed_moving.append(item)
                iterator += 1
            for item in reversed(items_needed_moving):
                parent = item.parent()
                if parent:
                    idx = self.indexOfTopLevelItem(parent); parent.removeChild(item); self.insertTopLevelItem(idx + 1, item)
            if items_needed_moving: self.setCurrentItem(items_needed_moving[-1])
            self.orderChanged.emit()
        else: super().dropEvent(event)

# --- 設定画面 ---
class SettingsDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("417 KeyGuide - Settings")
        self.setFixedSize(640, 800)
        self.main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget(); self.main_layout.addWidget(self.tabs)
        self.bottom_layout = QHBoxLayout()
        self.lbl_version = QLabel(f"Version: {APP_VERSION}"); self.lbl_version.setStyleSheet("color: gray;")
        self.bottom_layout.addWidget(self.lbl_version); self.bottom_layout.addStretch()
        self.btn_quit = QPushButton(config.tr("ui.btn.quit", "アプリを終了")); self.btn_quit.clicked.connect(QApplication.instance().quit)
        self.bottom_layout.addWidget(self.btn_quit); self.main_layout.addLayout(self.bottom_layout)
        self.loading_shortcuts = False; self.is_updating_from_tree = False
        self.ui_registry = {}; self.tab_keys = {}
        from collections import defaultdict
        self.tab_keys = defaultdict(list)
        self.icon_ui_updaters = {}
        self.init_general_tab(); self.init_mouse_tab(); self.init_appearance_tab(); self.init_cheat_tab(); self.init_shortcuts_tab(); self.init_language_tab()
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(config.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(config.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(config.redo)
        self.installEventFilter(self)
        config.changed_signal.connect(self.on_external_change)
        # 言語変更時にUI再構築
        config.language_changed_signal.connect(self.rebuild_ui)
        
        self.setStyleSheet(SCROLLBAR_STYLESHEET)
        app_icon_path = config.get_app_icon_path()
        if app_icon_path: self.setWindowIcon(QIcon(app_icon_path))
    
    def rebuild_ui(self):
        # UIを再構築して言語変更を即時反映
        current_index = self.tabs.currentIndex()
        self.ui_registry.clear()
        self.tab_keys.clear()
        self.tabs.clear()
        
        # タイトル等の更新
        self.btn_quit.setText(config.tr("ui.btn.quit", "アプリを終了"))
        
        self.init_general_tab()
        self.init_mouse_tab()
        self.init_appearance_tab()
        self.init_cheat_tab()
        self.init_shortcuts_tab()
        self.init_language_tab()
        
        self.tabs.setCurrentIndex(current_index)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.PaletteChange: current_style = self.styleSheet(); self.setStyleSheet(""); self.setStyleSheet(current_style) 
        super().changeEvent(event)
    def register_widget(self, key, widget, tab_name=None):
        self.ui_registry[key] = widget
        if tab_name: self.tab_keys[tab_name].append(key)
        val = config.get(key); self.update_widget_value(widget, val)
    def update_widget_value(self, widget, val):
        widget.blockSignals(True)
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)): widget.setValue(val)
        elif isinstance(widget, QCheckBox): widget.setChecked(bool(val))
        elif isinstance(widget, QComboBox):
            if isinstance(val, int): widget.setCurrentIndex(val)
            elif isinstance(val, str): # Language combo uses string data
                idx = widget.findData(val)
                if idx >= 0: widget.setCurrentIndex(idx)
        elif isinstance(widget, QLineEdit): widget.setText(str(val))
        elif isinstance(widget, ColorOpacityControl): widget.update_ui_from_config() 
        widget.blockSignals(False)
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and (event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter):
            focus_widget = QApplication.focusWidget()
            if isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox)): focus_widget.clearFocus(); return True
        return super().eventFilter(obj, event)
    def mousePressEvent(self, event):
        focused = QApplication.focusWidget()
        if focused and isinstance(focused, (QLineEdit, QSpinBox, QDoubleSpinBox)):
            if not focused.geometry().contains(focused.mapFromGlobal(event.globalPosition().toPoint())): focused.clearFocus()
        super().mousePressEvent(event)
    def _attach_validator(self, spinbox, config_key, tab_name=None):
        if isinstance(spinbox, (QSpinBox, QDoubleSpinBox)): spinbox.editingFinished.connect(lambda: self._save_from_spinbox(spinbox, config_key)); self.register_widget(config_key, spinbox, tab_name)
    def _save_from_spinbox(self, spinbox, key):
        if spinbox.text().strip() == "": default_val = config.get_default(key); spinbox.setValue(default_val)
        config.set(key, spinbox.value())
    def create_section_header(self, text):
        lbl = QLabel(text); font = lbl.font(); font.setPointSize(font.pointSize() + 3); font.setBold(True); lbl.setFont(font); return lbl
    def add_section(self, layout, text, space_height=10):
        if layout.rowCount() > 0 and space_height > 0: spacer = QWidget(); spacer.setFixedHeight(space_height); layout.addRow(spacer)
        lbl = self.create_section_header(text); layout.addRow(lbl)
    def add_separator(self, layout): line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken); line.setStyleSheet("background-color: #444444;"); line.setFixedHeight(1); layout.addRow(line)
    def add_reset_button(self, layout, tab_name):
        btn_reset = QPushButton(config.tr("ui.btn.reset_page", "このページを初期化")); btn_reset.clicked.connect(lambda: self.reset_tab(tab_name))
        if isinstance(layout, QFormLayout): layout.addRow(QLabel("<hr>")); layout.addRow(btn_reset)
        else: layout.addWidget(QLabel("<hr>")); layout.addWidget(btn_reset)
    def reset_tab(self, tab_name):
        keys = self.tab_keys.get(tab_name, [])
        for key in keys: default_val = config.get_default(key); config.set(key, default_val)
        if tab_name == "mouse":
            default_icons = config.get_default("icon_paths"); config.set("icon_paths", default_icons)
            default_aliases = config.get_default("mouse_aliases"); config.set("mouse_aliases", default_aliases)
    def init_general_tab(self):
        tab_name = "general"; tab = QWidget(); form = QFormLayout(tab)
        self.chk_log_enable = QCheckBox(config.tr("ui.gen.log_enable", "キー入力ログ表示を有効にする")); self.chk_log_enable.toggled.connect(lambda v: config.set("log_enabled", v)); self.register_widget("log_enabled", self.chk_log_enable, tab_name); form.addRow(self.chk_log_enable)
        self.sb_disp = NoScrollSpinBox(); self.sb_disp.setRange(100, 60000); self._attach_validator(self.sb_disp, "display_time", tab_name); form.addRow(config.tr("ui.gen.disp_time", "ログ表示維持時間 (ms):"), self.sb_disp)
        self.sb_fade = NoScrollSpinBox(); self.sb_fade.setRange(0, 5000); self._attach_validator(self.sb_fade, "fade_duration", tab_name); form.addRow(config.tr("ui.gen.fade_time", "フェードアウト時間 (ms):"), self.sb_fade)
        self.sb_max_stack = NoScrollSpinBox(); self.sb_max_stack.setRange(1, 10); self._attach_validator(self.sb_max_stack, "max_stack", tab_name); form.addRow(config.tr("ui.gen.max_stack", "最大ログ表示数:"), self.sb_max_stack)
        self.sb_combo_to = NoScrollSpinBox(); self.sb_combo_to.setRange(100, 5000); self._attach_validator(self.sb_combo_to, "combo_timeout", tab_name); form.addRow(config.tr("ui.gen.combo_to", "連続入力判定時間 (ms):"), self.sb_combo_to)
        form.addRow(QLabel("<hr>"))
        btn_pos = QPushButton(config.tr("ui.gen.pos_btn", "画面上で位置を指定する")); btn_pos.clicked.connect(self.pick_position); form.addRow(config.tr("ui.gen.pos_label", "位置:"), btn_pos)
        self.sb_x = NoScrollSpinBox(); self.sb_x.setRange(0, 10000); self._attach_validator(self.sb_x, "pos_x", tab_name); form.addRow(config.tr("ui.gen.pos_x", "X座標:"), self.sb_x)
        self.sb_y = NoScrollSpinBox(); self.sb_y.setRange(0, 10000); self._attach_validator(self.sb_y, "pos_y", tab_name); form.addRow(config.tr("ui.gen.pos_y", "Y座標:"), self.sb_y)
        self.add_reset_button(form, tab_name); self.tabs.addTab(tab, config.tr("ui.tab.general", "ログ表示"))
    def init_mouse_tab(self):
        tab_name = "mouse"; scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); tab = QWidget(); scroll_area.setWidget(tab); form = QFormLayout(tab)
        self.add_section(form, config.tr("ui.mouse.sec_icon", "【アイコン設定】"))
        self.cmb_mode = QComboBox(); self.cmb_mode.addItems([config.tr("ui.mouse.mode_0", "文字のみ"), config.tr("ui.mouse.mode_1", "アイコン + 文字"), config.tr("ui.mouse.mode_2", "アイコンのみ(文字置換)")]); self.cmb_mode.currentIndexChanged.connect(lambda: config.set("log_display_mode", self.cmb_mode.currentIndex())); self.register_widget("log_display_mode", self.cmb_mode, tab_name); form.addRow(config.tr("ui.mouse.mode_normal", "通常表示モード:"), self.cmb_mode)
        self.cmb_mod_mode = QComboBox(); self.cmb_mod_mode.addItems([config.tr("ui.mouse.mode_0", "文字のみ"), config.tr("ui.mouse.mode_1", "アイコン + 文字"), config.tr("ui.mouse.mode_2", "アイコンのみ(文字置換)")]); self.cmb_mod_mode.currentIndexChanged.connect(lambda: config.set("mod_mouse_display_mode", self.cmb_mod_mode.currentIndex())); self.register_widget("mod_mouse_display_mode", self.cmb_mod_mode, tab_name); form.addRow(config.tr("ui.mouse.mode_mod", "修飾キー+クリック表示モード:"), self.cmb_mod_mode)
        self.add_icon_picker(form, config.tr("ui.mouse.icon_l", "左クリック画像:"), "left"); self.add_icon_picker(form, config.tr("ui.mouse.icon_r", "右クリック画像:"), "right"); self.add_icon_picker(form, config.tr("ui.mouse.icon_m", "中ボタン/スクロール画像:"), "middle")
        self.sb_icon_size = NoScrollSpinBox(); self._attach_validator(self.sb_icon_size, "icon_size", tab_name); form.addRow(config.tr("ui.mouse.icon_size", "アイコンサイズ:"), self.sb_icon_size)
        self.add_section(form, config.tr("ui.mouse.sec_alias", "【操作名の変更】"))
        alias_group = QWidget(); alias_layout = QGridLayout(alias_group); alias_layout.setContentsMargins(0, 0, 0, 0); std_actions = ["Left Click", "Right Click", "Middle Click", "Double Click", "Middle Drag", "Scroll Up", "Scroll Down"]; self.alias_edits = {}
        for i, action in enumerate(std_actions):
            lbl = QLabel(f"{action} →"); edit = QLineEdit(config.get("mouse_aliases").get(action, action)); edit.setFixedWidth(140); edit.editingFinished.connect(lambda k=action: config.set_mouse_alias(k, self.alias_edits[k].text())); self.alias_edits[action] = edit; alias_layout.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight); alias_layout.addWidget(edit, i, 1, Qt.AlignmentFlag.AlignLeft)
        alias_layout.setColumnStretch(2, 1); form.addRow(alias_group)
        self.add_section(form, config.tr("ui.mouse.sec_target", "【ログ出力対象】"))
        self.chk_log_l = QCheckBox(config.tr("ui.mouse.log_l", "左クリック (単発)")); self.chk_log_l.toggled.connect(lambda v: config.set("log_left_click", v)); self.register_widget("log_left_click", self.chk_log_l, tab_name); form.addRow(self.chk_log_l)
        self.chk_log_r = QCheckBox(config.tr("ui.mouse.log_r", "右クリック")); self.chk_log_r.toggled.connect(lambda v: config.set("log_right_click", v)); self.register_widget("log_right_click", self.chk_log_r, tab_name); form.addRow(self.chk_log_r)
        self.chk_log_mc = QCheckBox(config.tr("ui.mouse.log_m", "中クリック")); self.chk_log_mc.toggled.connect(lambda v: config.set("log_middle_click", v)); self.register_widget("log_middle_click", self.chk_log_mc, tab_name); form.addRow(self.chk_log_mc)
        self.chk_log_md = QCheckBox(config.tr("ui.mouse.log_d", "中ドラッグ")); self.chk_log_md.toggled.connect(lambda v: config.set("log_middle_drag", v)); self.register_widget("log_middle_drag", self.chk_log_md, tab_name); form.addRow(self.chk_log_md)
        self.chk_log_s = QCheckBox(config.tr("ui.mouse.log_s", "スクロール")); self.chk_log_s.toggled.connect(lambda v: config.set("log_scroll", v)); self.register_widget("log_scroll", self.chk_log_s, tab_name); form.addRow(self.chk_log_s)
        self.add_section(form, config.tr("ui.mouse.sec_halo", "【マウス円 (Halo) 設定】"))
        self.chk_halo = QCheckBox(config.tr("ui.mouse.halo_enable", "有効化")); self.chk_halo.toggled.connect(lambda v: config.set("mouse_halo_enabled", v)); self.register_widget("mouse_halo_enabled", self.chk_halo, tab_name); form.addRow(self.chk_halo)
        self.sb_halo_size = NoScrollSpinBox(); self._attach_validator(self.sb_halo_size, "halo_size", tab_name); form.addRow(config.tr("ui.mouse.halo_r", "円の半径:"), self.sb_halo_size)
        self.sb_sq_size = NoScrollSpinBox(); self._attach_validator(self.sb_sq_size, "middle_click_square_size", tab_name); form.addRow(config.tr("ui.mouse.halo_sq", "中クリック(■)サイズ:"), self.sb_sq_size)
        self.sb_arr_size = NoScrollSpinBox(); self._attach_validator(self.sb_arr_size, "scroll_arrow_size", tab_name); form.addRow(config.tr("ui.mouse.halo_arr", "スクロール(▼▲)サイズ:"), self.sb_arr_size)
        self.add_color_op(form, "halo_color", config.tr("ui.mouse.col_base", "基本色"), tab_name); self.add_color_op(form, "click_left_color", config.tr("ui.mouse.col_l", "左クリック色"), tab_name); self.add_color_op(form, "click_right_color", config.tr("ui.mouse.col_r", "右クリック色"), tab_name); self.add_color_op(form, "click_middle_color", config.tr("ui.mouse.col_m", "中クリック色"), tab_name); self.add_color_op(form, "scroll_arrow_color", config.tr("ui.mouse.col_s", "スクロール矢印色"), tab_name)
        self.add_reset_button(form, tab_name); self.tabs.addTab(scroll_area, config.tr("ui.tab.mouse", "マウスログ"))
    def add_color_op(self, layout, key, label, tab_name=None):
        co = ColorOpacityControl(key, label); self.register_widget(key, co, tab_name); layout.addRow(co); return co
    def init_appearance_tab(self):
        tab_name = "appearance"; scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); tab = QWidget(); scroll_area.setWidget(tab); lay = QVBoxLayout(tab); form = QFormLayout()
        grp_fontfile = QGroupBox(config.tr("ui.app.grp_font", "カスタムフォント管理")); lay_fontfile = QVBoxLayout(grp_fontfile)
        self.list_fonts = QListWidget(); self.list_fonts.setFixedHeight(60); self.list_fonts.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); self.list_fonts.addItems(config.get("custom_fonts")); lay_fontfile.addWidget(self.list_fonts)
        hbox_ff = QHBoxLayout(); btn_add_ff = QPushButton(config.tr("ui.app.btn_add", "追加...")); btn_add_ff.clicked.connect(self.add_custom_font_file); hbox_ff.addWidget(btn_add_ff); btn_del_ff = QPushButton(config.tr("ui.app.btn_del", "削除")); btn_del_ff.clicked.connect(self.remove_custom_font_file); hbox_ff.addWidget(btn_del_ff); lay_fontfile.addLayout(hbox_ff); lay.addWidget(grp_fontfile)
        grp_main = QGroupBox(config.tr("ui.app.grp_main", "キー入力文字 (Main)")); form_main = QFormLayout(grp_main)
        self.btn_font_main = QPushButton(self._get_font_desc("main")); self.btn_font_main.clicked.connect(lambda: self.select_font("main")); form_main.addRow(config.tr("ui.common.font", "フォント:"), self.btn_font_main)
        for k in ["font_family", "font_size", "font_bold", "font_italic", "font_underline", "font_strikeout"]: self.tab_keys[tab_name].append(k)
        self.add_color_op(form_main, "text_color", config.tr("ui.app.col_text", "文字色"), tab_name)
        self.add_separator(form_main)
        self.chk_txt_shadow = QCheckBox(config.tr("ui.app.chk_shadow", "影を有効化")); self.chk_txt_shadow.toggled.connect(lambda v: config.set("text_shadow_enabled", v)); self.register_widget("text_shadow_enabled", self.chk_txt_shadow, tab_name); form_main.addRow(self.chk_txt_shadow)
        self.add_color_op(form_main, "text_shadow_color", config.tr("ui.app.col_shadow", "影色"), tab_name)
        sb_ts_x = NoScrollSpinBox(); sb_ts_x.setRange(-20, 20); self._attach_validator(sb_ts_x, "text_shadow_offset_x", tab_name); sb_ts_y = NoScrollSpinBox(); sb_ts_y.setRange(-20, 20); self._attach_validator(sb_ts_y, "text_shadow_offset_y", tab_name)
        form_main.addRow(config.tr("ui.app.offset", "  Offset X/Y:"), self.create_hbox([sb_ts_x, sb_ts_y], add_stretch=True))
        self.add_separator(form_main)
        self.chk_txt_outline = QCheckBox(config.tr("ui.app.chk_outline", "縁取りを有効化")); self.chk_txt_outline.toggled.connect(lambda v: config.set("text_outline_enabled", v)); self.register_widget("text_outline_enabled", self.chk_txt_outline, tab_name); form_main.addRow(self.chk_txt_outline)
        sb_to_w = NoScrollSpinBox(); self._attach_validator(sb_to_w, "text_outline_width", tab_name); form_main.addRow(config.tr("ui.app.width", "  太さ:"), sb_to_w); self.add_color_op(form_main, "text_outline_color", config.tr("ui.app.col_outline", "縁色"), tab_name); lay.addWidget(grp_main)
        grp_desc = QGroupBox(config.tr("ui.app.grp_desc", "説明文 (Desc)")); form_desc = QFormLayout(grp_desc)
        self.chk_show_desc = QCheckBox(config.tr("ui.app.chk_show_desc", "説明を表示する")); self.chk_show_desc.toggled.connect(lambda v: config.set("show_desc", v)); self.register_widget("show_desc", self.chk_show_desc, tab_name); form_desc.addRow(self.chk_show_desc)
        self.btn_font_desc = QPushButton(self._get_font_desc("desc")); self.btn_font_desc.clicked.connect(lambda: self.select_font("desc")); form_desc.addRow(config.tr("ui.common.font", "フォント:"), self.btn_font_desc)
        for k in ["desc_font_family", "desc_font_size", "desc_font_bold", "desc_font_italic", "desc_font_underline", "desc_font_strikeout"]: self.tab_keys[tab_name].append(k)
        self.add_color_op(form_desc, "desc_text_color", config.tr("ui.app.col_text", "文字色"), tab_name); self.add_separator(form_desc)
        self.chk_desc_shadow = QCheckBox(config.tr("ui.app.chk_shadow", "影を有効化")); self.chk_desc_shadow.toggled.connect(lambda v: config.set("desc_shadow_enabled", v)); self.register_widget("desc_shadow_enabled", self.chk_desc_shadow, tab_name); form_desc.addRow(self.chk_desc_shadow)
        self.add_color_op(form_desc, "desc_shadow_color", config.tr("ui.app.col_shadow", "影色"), tab_name); sb_ds_x = NoScrollSpinBox(); sb_ds_x.setRange(-20, 20); self._attach_validator(sb_ds_x, "desc_shadow_offset_x", tab_name); sb_ds_y = NoScrollSpinBox(); sb_ds_y.setRange(-20, 20); self._attach_validator(sb_ds_y, "desc_shadow_offset_y", tab_name)
        form_desc.addRow(config.tr("ui.app.offset", "  Offset X/Y:"), self.create_hbox([sb_ds_x, sb_ds_y], add_stretch=True)); self.add_separator(form_desc)
        
        self.chk_desc_outline = QCheckBox(config.tr("ui.app.chk_outline", "縁取りを有効化")); self.chk_desc_outline.toggled.connect(lambda v: config.set("desc_outline_enabled", v)); self.register_widget("desc_outline_enabled", self.chk_desc_outline, tab_name); form_desc.addRow(self.chk_desc_outline)
        sb_do_w = NoScrollSpinBox(); self._attach_validator(sb_do_w, "desc_outline_width", tab_name); form_desc.addRow(config.tr("ui.app.width", "  太さ:"), sb_do_w); self.add_color_op(form_desc, "desc_outline_color", config.tr("ui.app.col_outline", "縁色"), tab_name); lay.addWidget(grp_desc)
        
        grp_sep = QGroupBox(config.tr("ui.app.grp_sep", "区切り線")); form_sep = QFormLayout(grp_sep)
        self.chk_sep = QCheckBox(config.tr("ui.app.chk_sep", "線を引く")); self.chk_sep.toggled.connect(lambda v: config.set("separator_enabled", v)); self.register_widget("separator_enabled", self.chk_sep, tab_name); form_sep.addRow(self.chk_sep)
        self.add_color_op(form_sep, "separator_color", config.tr("ui.app.col_sep", "線の色"), tab_name)
        self.sb_sep_w = NoScrollSpinBox(); self.sb_sep_w.setRange(1, 10); self._attach_validator(self.sb_sep_w, "separator_width", tab_name); form_sep.addRow(config.tr("ui.app.width_sep", "太さ:"), self.sb_sep_w)
        self.sb_sep_sp = NoScrollSpinBox(); self.sb_sep_sp.setRange(0, 50); self._attach_validator(self.sb_sep_sp, "separator_spacing", tab_name); form_sep.addRow(config.tr("ui.app.spacing", "余白:"), self.sb_sep_sp)
        self.add_separator(form_sep)
        self.chk_sep_shadow = QCheckBox(config.tr("ui.app.chk_shadow", "影を有効化")); self.chk_sep_shadow.toggled.connect(lambda v: config.set("sep_shadow_enabled", v)); self.register_widget("sep_shadow_enabled", self.chk_sep_shadow, tab_name); form_sep.addRow(self.chk_sep_shadow)
        self.add_color_op(form_sep, "sep_shadow_color", config.tr("ui.app.col_shadow", "影色"), tab_name); lay.addWidget(grp_sep)
        grp_bg = QGroupBox(config.tr("ui.app.grp_bg", "背景・ウィンドウ枠")); form_bg = QFormLayout(grp_bg)
        self.add_color_op(form_bg, "bg_color", config.tr("ui.app.col_bg", "ログ背景色"), tab_name); self.add_color_op(form_bg, "border_color", config.tr("ui.app.col_border", "枠線の色"), tab_name)
        self.sb_border_w = NoScrollSpinBox(); self.sb_border_w.setRange(0, 20); self._attach_validator(self.sb_border_w, "border_width", tab_name); form_bg.addRow(config.tr("ui.app.width_border", "枠線の太さ:"), self.sb_border_w)
        self.sb_radius = NoScrollSpinBox(); self.sb_radius.setRange(0, 50); self._attach_validator(self.sb_radius, "border_radius", tab_name); form_bg.addRow(config.tr("ui.app.radius", "角丸半径:"), self.sb_radius); lay.addWidget(grp_bg)
        grp_prox = QGroupBox(config.tr("ui.app.grp_prox", "近接透過")); form_prox = QFormLayout(grp_prox)
        self.chk_prox = QCheckBox(config.tr("ui.app.chk_prox", "マウス接近で個別に透過する")); self.chk_prox.toggled.connect(lambda v: config.set("item_proximity_enabled", v)); self.register_widget("item_proximity_enabled", self.chk_prox, tab_name); form_prox.addRow(self.chk_prox)
        self.sb_prox_dist = NoScrollSpinBox(); self.sb_prox_dist.setRange(10, 500); self._attach_validator(self.sb_prox_dist, "item_proximity_dist", tab_name); form_prox.addRow(config.tr("ui.app.prox_dist", "反応距離 (px):"), self.sb_prox_dist)
        self.sb_prox_min = NoScrollDoubleSpinBox(); self.sb_prox_min.setRange(0.0, 1.0); self.sb_prox_min.setSingleStep(0.1); self._attach_validator(self.sb_prox_min, "item_proximity_min_opacity", tab_name); form_prox.addRow(config.tr("ui.app.prox_min", "最大透過時不透明度:"), self.sb_prox_min); lay.addWidget(grp_prox)
        lay.addStretch(); self.add_reset_button(lay, tab_name); self.tabs.addTab(scroll_area, config.tr("ui.tab.appearance", "ログ外観"))
    def init_cheat_tab(self):
        tab_name = "cheat"; scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); tab = QWidget(); scroll_area.setWidget(tab); form = QFormLayout(tab)
        self.chk_cheat = QCheckBox(config.tr("ui.cheat.enable", "チートシートを有効化")); self.chk_cheat.toggled.connect(lambda v: config.set("cheat_sheet_enabled", v)); self.register_widget("cheat_sheet_enabled", self.chk_cheat, tab_name); form.addRow(self.chk_cheat)
        form.addRow(QLabel(config.tr("ui.cheat.note", "※単押しで「ウィンドウ表示」、長押しで「全画面表示」します。"))); form.addRow(QLabel("<hr>"))
        self.add_section(form, config.tr("ui.cheat.sec_act", "【動作設定】"), space_height=0) 
        self.txt_cheat_key = QLineEdit(config.get("cheat_sheet_key")); self.txt_cheat_key.setPlaceholderText(config.tr("ui.cheat.placeholder", "例: F1, Alt, Shift")); self.txt_cheat_key.setFixedWidth(140) 
        self.txt_cheat_key.editingFinished.connect(lambda: config.set("cheat_sheet_key", self.txt_cheat_key.text())); self.register_widget("cheat_sheet_key", self.txt_cheat_key, tab_name); form.addRow(config.tr("ui.cheat.trigger", "トリガーキー:"), self.txt_cheat_key)
        self.sb_cheat_hold = NoScrollSpinBox(); self.sb_cheat_hold.setRange(100, 3000); self._attach_validator(self.sb_cheat_hold, "cheat_sheet_hold_ms", tab_name); form.addRow(config.tr("ui.cheat.hold", "長押し判定時間 (ms):"), self.sb_cheat_hold)
        self.add_section(form, config.tr("ui.cheat.sec_com", "【表示設定(共通)】"))
        self.cmb_align = QComboBox(); self.cmb_align.addItems([config.tr("ui.cheat.align_l", "左揃え"), config.tr("ui.cheat.align_r", "右揃え")]); self.cmb_align.setFixedWidth(140) 
        self.cmb_align.currentIndexChanged.connect(lambda: config.set("cheat_sheet_key_align", self.cmb_align.currentIndex())); self.register_widget("cheat_sheet_key_align", self.cmb_align, tab_name); form.addRow(config.tr("ui.cheat.align", "キー列の配置:"), self.cmb_align)
        self.sb_spacing = NoScrollSpinBox(); self.sb_spacing.setRange(0, 200); self._attach_validator(self.sb_spacing, "cheat_sheet_spacing", tab_name); form.addRow(config.tr("ui.cheat.spacing", "キーと説明文間の余白:"), self.sb_spacing)
        self.add_section(form, config.tr("ui.cheat.sec_win", "【表示設定(ウィンドウモード)】"))
        self.sb_cheat_fs = NoScrollSpinBox(); self.sb_cheat_fs.setRange(8, 72); self._attach_validator(self.sb_cheat_fs, "cheat_sheet_font_size", tab_name); form.addRow(config.tr("ui.cheat.font_size", "フォントサイズ:"), self.sb_cheat_fs)
        self.sb_cw_key = NoScrollSpinBox(); self.sb_cw_key.setRange(0, 500); self._attach_validator(self.sb_cw_key, "cheat_sheet_col_width_key", tab_name); form.addRow(config.tr("ui.cheat.col_w_key", "キー列の最小幅 (px):"), self.sb_cw_key)
        self.sb_cw_desc = NoScrollSpinBox(); self.sb_cw_desc.setRange(0, 1000); self._attach_validator(self.sb_cw_desc, "cheat_sheet_col_width_desc", tab_name); form.addRow(config.tr("ui.cheat.col_w_desc", "説明文の最小幅 (px):"), self.sb_cw_desc)
        self.chk_word_wrap = QCheckBox(config.tr("ui.cheat.wrap", "説明文の自動折り返し")); self.chk_word_wrap.toggled.connect(lambda: config.set("cheat_sheet_word_wrap", self.chk_word_wrap.isChecked())); self.register_widget("cheat_sheet_word_wrap", self.chk_word_wrap, tab_name); form.addRow(self.chk_word_wrap); form.addRow(QLabel(config.tr("ui.cheat.wrap_note", "　※ウィンドウの幅に合わせて自動で説明文を折り返します。")))
        self.add_section(form, config.tr("ui.cheat.sec_full", "【表示設定(全画面モード)】"))
        self.sb_cheat_fs_full = NoScrollSpinBox(); self.sb_cheat_fs_full.setRange(8, 100); self._attach_validator(self.sb_cheat_fs_full, "cheat_sheet_fullscreen_font_size", tab_name); form.addRow(config.tr("ui.cheat.font_size", "フォントサイズ:"), self.sb_cheat_fs_full); form.addRow(QLabel(config.tr("ui.cheat.full_note", "　※項目が多い場合、自動で縮小します")))
        self.sb_cw_key_full = NoScrollSpinBox(); self.sb_cw_key_full.setRange(0, 500); self._attach_validator(self.sb_cw_key_full, "cheat_sheet_fullscreen_min_key", tab_name); form.addRow(config.tr("ui.cheat.col_w_key", "キー列の最小幅 (px):"), self.sb_cw_key_full)
        self.sb_cw_desc_full = NoScrollSpinBox(); self.sb_cw_desc_full.setRange(0, 1000); self._attach_validator(self.sb_cw_desc_full, "cheat_sheet_fullscreen_min_desc", tab_name); form.addRow(config.tr("ui.cheat.col_w_desc", "説明文の最小幅 (px):"), self.sb_cw_desc_full)
        self.add_section(form, config.tr("ui.cheat.sec_col", "【色設定】"))
        self.add_color_op(form, "cheat_sheet_header_color", config.tr("ui.cheat.col_h", "ヘッダー文字色"), tab_name); self.add_color_op(form, "cheat_sheet_key_color", config.tr("ui.cheat.col_k", "キー文字色"), tab_name); self.add_color_op(form, "cheat_sheet_desc_color", config.tr("ui.cheat.col_d", "説明文字色"), tab_name); self.add_color_op(form, "cheat_sheet_bg_color", config.tr("ui.cheat.col_bg_win", "背景色(ウィンドウ)"), tab_name); self.add_color_op(form, "cheat_sheet_fullscreen_bg_color", config.tr("ui.cheat.col_bg_full", "背景色(全画面)"), tab_name)
        self.chk_border_enable = QCheckBox(config.tr("ui.cheat.chk_border", "ウィンドウ内に外枠をつける")); self.chk_border_enable.toggled.connect(lambda v: self._toggle_border_settings(v)); self.register_widget("cheat_window_border_enabled", self.chk_border_enable, tab_name); form.addRow(self.chk_border_enable)
        self.border_color_widget = self.add_color_op(form, "cheat_window_border_color", config.tr("ui.cheat.col_border", "外枠の色(ウィンドウ)"), tab_name); self._toggle_border_settings(config.get("cheat_window_border_enabled")) 
        self.add_reset_button(form, tab_name); self.tabs.addTab(scroll_area, config.tr("ui.tab.cheat", "チートシート"))
    def _toggle_border_settings(self, enabled): config.set("cheat_window_border_enabled", enabled); self.border_color_widget.setEnabled(enabled)
    def init_shortcuts_tab(self):
        tab = QWidget(); lay = QVBoxLayout(tab)
        lbl_info = QLabel(config.tr("ui.sc.note", "※ ショートカット押下時に説明文を表示します")); lbl_info.setStyleSheet("font-weight: bold;"); lay.addWidget(lbl_info)
        top_box = QHBoxLayout(); btn_add = QPushButton(config.tr("ui.sc.add", "項目を追加")); btn_add.clicked.connect(self.add_shortcut_item); top_box.addWidget(btn_add); btn_del = QPushButton(config.tr("ui.sc.del", "削除")); btn_del.clicked.connect(self.del_shortcut_item); top_box.addWidget(btn_del); btn_up = QPushButton("↑"); btn_up.clicked.connect(lambda: self.move_item(-1)); top_box.addWidget(btn_up); btn_down = QPushButton("↓"); btn_down.clicked.connect(lambda: self.move_item(1)); top_box.addWidget(btn_down); top_box.addStretch()
        btn_reset = QPushButton(config.tr("ui.sc.btn_reset", "初期化")); btn_reset.setToolTip("デフォルト設定に戻します"); btn_reset.clicked.connect(self.reset_shortcuts_to_default); top_box.addWidget(btn_reset); btn_all_del = QPushButton(config.tr("ui.sc.all_del", "全て削除")); btn_all_del.clicked.connect(self.delete_all_shortcuts); top_box.addWidget(btn_all_del); lay.addLayout(top_box)
        action_box = QHBoxLayout(); btn_import = QPushButton(config.tr("ui.sc.import", "読込 (JSON/TXT)")); btn_import.clicked.connect(self.import_shortcuts); action_box.addWidget(btn_import); btn_export = QPushButton(config.tr("ui.sc.export", "出力 (JSON/TXT)")); btn_export.clicked.connect(self.export_shortcuts); action_box.addWidget(btn_export); action_box.addStretch(); lay.addLayout(action_box)
        toggle_box = QHBoxLayout(); btn_all_master = QPushButton(config.tr("ui.sc.toggle_master", "マスター全有効/無効")); btn_all_master.clicked.connect(lambda: self.toggle_all_columns(0)); btn_all_log = QPushButton(config.tr("ui.sc.toggle_log", "ログ全有効/無効")); btn_all_log.clicked.connect(lambda: self.toggle_all_columns(1)); btn_all_cheat = QPushButton(config.tr("ui.sc.toggle_cheat", "チート全有効/無効")); btn_all_cheat.clicked.connect(lambda: self.toggle_all_columns(2)); toggle_box.addWidget(btn_all_master); toggle_box.addWidget(btn_all_log); toggle_box.addWidget(btn_all_cheat); toggle_box.addStretch(); lay.addLayout(toggle_box)
        self.tree = NoNestTreeWidget(); delegate = CenteredCheckBoxDelegate(self.tree); self.tree.setItemDelegate(delegate); self.tree.setColumnCount(5); self.tree.setHeaderLabels(["Master", "Log", "Cheat", "Key / Header", "Description"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents); self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents); self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents); self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch); self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove); self.tree.itemChanged.connect(self.on_tree_item_changed); self.tree.orderChanged.connect(self.save_shortcuts_from_tree); lay.addWidget(self.tree); self.load_shortcuts_to_tree(); self.tabs.addTab(tab, config.tr("ui.tab.shortcuts", "ショートカット管理"))
    def init_language_tab(self):
        tab_name = "language"; tab = QWidget(); form = QFormLayout(tab)
        
        self.cmb_lang = QComboBox()
        # 言語リストの設定
        lang_keys = ["ja-original", "en", "ru", "zh", "ko", "hi", "custom"]
        for key in lang_keys:
            self.cmb_lang.addItem(config.LANGUAGES.get(key, key), key)
        
        self.cmb_lang.activated.connect(self.on_language_changed)
        self.register_widget("language", self.cmb_lang, tab_name)
        form.addRow("Select Language:", self.cmb_lang)
        
        # 説明文1 (通常)
        lbl_missing = QLabel(config.tr("ui.lang.note_missing", "データが一部不足している場合、各言語の初期値または日本語にします。"))
        lbl_missing.setStyleSheet("color: #AAAAAA;") 
        lbl_missing.setWordWrap(True)
        form.addRow(lbl_missing)

        # スペースを追加
        spacer = QWidget()
        spacer.setFixedHeight(20)
        form.addRow(spacer)

        # 区切り線
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(line)

        # 説明文2 (目立つ色)
        lbl_corrupt = QLabel(config.tr("ui.lang.note_corrupt", "データが破損した場合は、[config]フォルダ内の、問題のあるjsonデータを削除してください。\n全てのjsonデータは、削除後にアプリの再起動や設定変更をすると自動で再生成されます。"))
        lbl_corrupt.setStyleSheet("color: orange; font-weight: bold;")
        lbl_corrupt.setWordWrap(True)
        form.addRow(lbl_corrupt)
        
        # Helpリンク
        help_url = "https://github.com/417-Butter/417_KeyGuide/wiki"
        lbl_help = QLabel(f"Wiki: <a href='{help_url}' style='color: #4da6ff;'>{help_url}</a>")
        lbl_help.setOpenExternalLinks(True)
        form.addRow(lbl_help)
        
        self.tabs.addTab(tab, "Language")

    def on_language_changed(self, index):
        key = self.cmb_lang.itemData(index)
        current_val = config.get("language")

        # Customが再選択された場合、強制リロード
        if key == "custom" and key == current_val:
            config.load_locale()
            config.language_changed_signal.emit()
            QMessageBox.information(self, "Reloaded", "Custom language file reloaded.")
        else:
            config.set("language", key)
        
        if key == "custom":
            # 英語テキストをハードコード (辞書から除外)
            msg_text = "Please translate 'custom.json' in config > language to your language. (AI translation tools allowed)\nIf you have already done so, the switch is complete."
            QMessageBox.information(self, "Language Settings", msg_text)

    def reset_shortcuts_to_default(self):
        res = QMessageBox.question(self, config.tr("ui.sc.reset_confirm_title", "確認"), config.tr("ui.sc.reset_confirm_msg", "ショートカットリストを初期状態（デフォルト）に戻しますか？\n現在のリストは破棄されます。"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res == QMessageBox.StandardButton.Yes:
            self.loading_shortcuts = True; import copy; config.set("shortcuts_list", copy.deepcopy(config.DEFAULT_SHORTCUTS)); self.loading_shortcuts = False; self.load_shortcuts_to_tree()
    def load_shortcuts_to_tree(self):
        self.loading_shortcuts = True; self.tree.clear(); shortcuts = config.get("shortcuts_list")
        for item in shortcuts:
            is_header = item.get("type") == "header"; combo = item.get("combo"); desc = "" if is_header else item.get("desc")
            tree_item = QTreeWidgetItem(self.tree)
            tree_item.setCheckState(0, Qt.CheckState.Checked if item.get("enabled") else Qt.CheckState.Unchecked); tree_item.setCheckState(1, Qt.CheckState.Checked if item.get("show_in_log", True) else Qt.CheckState.Unchecked); tree_item.setCheckState(2, Qt.CheckState.Checked if item.get("show_in_cheat", True) else Qt.CheckState.Unchecked)
            tree_item.setText(3, combo); tree_item.setText(4, desc); tree_item.setFlags(tree_item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            if is_header:
                font = tree_item.font(3); font.setBold(True); tree_item.setFont(3, font); [tree_item.setBackground(i, QColor("#333333")) for i in range(5)]; tree_item.setForeground(3, QColor("#AAAAAA"))
        self.loading_shortcuts = False
    def on_tree_item_changed(self, item, column):
        if self.loading_shortcuts: return
        if column == 0:
            self.loading_shortcuts = True; state = item.checkState(0); item.setCheckState(1, state); item.setCheckState(2, state); self.loading_shortcuts = False
        self.save_shortcuts_from_tree()
    def save_shortcuts_from_tree(self):
        if self.loading_shortcuts: return 
        self.is_updating_from_tree = True; new_list = []; root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i); combo = item.text(3); desc = item.text(4); enabled = (item.checkState(0) == Qt.CheckState.Checked); show_log = (item.checkState(1) == Qt.CheckState.Checked); show_cheat = (item.checkState(2) == Qt.CheckState.Checked)
            is_header = combo.startswith("#") or desc.strip() == ""; new_list.append({"combo": combo, "desc": desc, "enabled": enabled, "type": "header" if is_header else "key", "show_in_log": show_log, "show_in_cheat": show_cheat})
        config.set("shortcuts_list", new_list); self.is_updating_from_tree = False
    def toggle_all_columns(self, column_index):
        root = self.tree.invisibleRootItem(); count = root.childCount()
        if count == 0: return
        first_val = root.child(0).checkState(column_index); is_first_checked = False
        if isinstance(first_val, int): is_first_checked = (first_val == Qt.CheckState.Checked.value)
        elif first_val == Qt.CheckState.Checked: is_first_checked = True
        new_state = Qt.CheckState.Unchecked if is_first_checked else Qt.CheckState.Checked
        self.loading_shortcuts = True
        for i in range(count):
            item = root.child(i); item.setCheckState(column_index, new_state)
            if column_index == 0: item.setCheckState(1, new_state); item.setCheckState(2, new_state)
        self.loading_shortcuts = False; self.save_shortcuts_from_tree()
    def add_shortcut_item(self):
        self.loading_shortcuts = True; item = QTreeWidgetItem(); item.setCheckState(0, Qt.CheckState.Checked); item.setCheckState(1, Qt.CheckState.Checked); item.setCheckState(2, Qt.CheckState.Checked); item.setText(3, ""); item.setText(4, ""); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
        current_item = self.tree.currentItem()
        if current_item: idx = self.tree.indexOfTopLevelItem(current_item); self.tree.insertTopLevelItem(idx + 1, item); self.tree.setCurrentItem(item)
        else: self.tree.addTopLevelItem(item); self.tree.scrollToBottom(); self.tree.setCurrentItem(item)
        self.tree.editItem(item, 3); self.loading_shortcuts = False; self.save_shortcuts_from_tree()
    def del_shortcut_item(self):
        items = self.tree.selectedItems(); 
        if not items: return
        self.loading_shortcuts = True
        for item in items: idx = self.tree.indexOfTopLevelItem(item); self.tree.takeTopLevelItem(idx)
        self.loading_shortcuts = False; self.save_shortcuts_from_tree()
    def delete_all_shortcuts(self):
        res = QMessageBox.question(self, config.tr("ui.common.confirm", "確認"), config.tr("ui.sc.msg_del", "リストを全て削除しますか？\nこの操作は取り消せますが、現在のリストは消去されます。"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res == QMessageBox.StandardButton.Yes: self.loading_shortcuts = True; self.tree.clear(); self.loading_shortcuts = False; self.save_shortcuts_from_tree()
    def move_item(self, direction):
        items = self.tree.selectedItems(); 
        if not items: return
        self.loading_shortcuts = True; indices = []; item_map = {}
        for item in items: idx = self.tree.indexOfTopLevelItem(item); indices.append(idx); item_map[idx] = item
        indices.sort()
        if direction > 0: indices.reverse()
        count = self.tree.topLevelItemCount()
        for idx in indices:
            new_idx = idx + direction
            if 0 <= new_idx < count: item = self.tree.takeTopLevelItem(idx); self.tree.insertTopLevelItem(new_idx, item); item.setSelected(True)
        self.tree.scrollToItem(items[0]); self.loading_shortcuts = False; self.save_shortcuts_from_tree()
    def import_shortcuts(self):
        fname, _ = QFileDialog.getOpenFileName(self, config.tr("ui.common.file_select", "ショートカットファイル選択"), "", "JSON/Text (*.json *.txt);;All Files (*)")
        if fname:
            try:
                with open(fname, 'r', encoding='utf-8') as f: new_data = json.load(f)
                valid_data = []
                if isinstance(new_data, dict):
                    for k, v in new_data.items(): 
                        if not isinstance(k, str) or not isinstance(v, str): continue 
                        is_header = k.startswith("#") or v == ""; valid_data.append({"combo": k.replace("# ", ""), "desc": v, "enabled": True, "type": "header" if is_header else "key", "show_in_log": True, "show_in_cheat": True})
                elif isinstance(new_data, list):
                    for item in new_data:
                        if not isinstance(item, dict): continue
                        if "combo" not in item: continue
                        if "show_in_log" not in item: item["show_in_log"] = True
                        if "show_in_cheat" not in item: item["show_in_cheat"] = True
                        if "type" not in item: item["type"] = "key"
                        if "enabled" not in item: item["enabled"] = True
                        if "desc" not in item: item["desc"] = ""
                        valid_data.append(item)
                else: raise ValueError("JSONの形式が対応していません")
                if not valid_data: raise ValueError("有効なショートカットデータが見つかりませんでした")
                msg = QMessageBox(self); msg.setWindowTitle("インポートモード"); msg.setText(f"{len(valid_data)} " + config.tr("ui.sc.msg_imp_mode", "件のデータを読み込みました。\nモードを選択してください")); btn_append = msg.addButton(config.tr("ui.sc.btn_append", "追加 (末尾)"), QMessageBox.ButtonRole.AcceptRole); btn_overwrite = msg.addButton(config.tr("ui.sc.btn_overwrite", "上書き (置換)"), QMessageBox.ButtonRole.DestructiveRole); msg.addButton(config.tr("ui.common.cancel", "キャンセル"), QMessageBox.ButtonRole.RejectRole); msg.exec()
                if msg.clickedButton() == btn_append: current = config.get("shortcuts_list"); current.extend(valid_data); config.set("shortcuts_list", current)
                elif msg.clickedButton() == btn_overwrite: config.set("shortcuts_list", valid_data)
                self.load_shortcuts_to_tree()
            except Exception as e: QMessageBox.warning(self, config.tr("ui.common.error", "エラー"), f"失敗しました:\n{e}")
    def export_shortcuts(self):
        msg = QMessageBox(self); msg.setWindowTitle("出力オプション"); msg.setText(config.tr("ui.sc.msg_exp_opt", "出力形式を選択してください")); btn_full = msg.addButton(config.tr("ui.sc.btn_full", "フル設定 (JSON)"), QMessageBox.ButtonRole.AcceptRole); btn_simple = msg.addButton(config.tr("ui.sc.btn_simple", "キーと説明のみ (Simple)"), QMessageBox.ButtonRole.ActionRole); btn_cancel = msg.addButton(config.tr("ui.common.cancel", "キャンセル"), QMessageBox.ButtonRole.RejectRole); msg.exec()
        if msg.clickedButton() == btn_cancel: return
        fname, _ = QFileDialog.getSaveFileName(self, "保存", "shortcuts.json", "JSON (*.json);;Text (*.txt)")
        if not fname: return
        try:
            full_list = config.get("shortcuts_list"); data_to_save = []
            if msg.clickedButton() == btn_full: data_to_save = full_list
            else:
                data_to_save = [{"combo": item.get("combo"), "desc": item.get("desc")} for item in full_list if item.get("enabled")]
                if isinstance(data_to_save, list):
                    temp_dict = {}
                    for i in data_to_save: k = i["combo"]; (k if i.get("type") != "header" else "# " + k); temp_dict[k] = i["desc"]
                    data_to_save = temp_dict
            with open(fname, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "完了", config.tr("ui.sc.msg_saved", "保存しました。"))
        except Exception as e: QMessageBox.warning(self, config.tr("ui.common.error", "エラー"), f"失敗しました:\n{e}")
    def create_hbox(self, widgets, add_stretch=False): 
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(5)
        [l.addWidget(wid) for wid in widgets]
        if add_stretch: l.addStretch()
        return w
    def on_external_change(self, key, value):
        if key in self.ui_registry: self.update_widget_value(self.ui_registry[key], value)
        if key == "mouse_aliases":
             for k, edit in self.alias_edits.items():
                 if k in value: edit.blockSignals(True); edit.setText(value[k]); edit.blockSignals(False)
        if key == "icon_paths":
            for k, updater in self.icon_ui_updaters.items(): new_path = value.get(k, ""); updater(new_path)
        if "font" in key: self.btn_font_main.setText(self._get_font_desc("main")); self.btn_font_desc.setText(self._get_font_desc("desc"))
        if key == "custom_fonts": self.list_fonts.clear(); self.list_fonts.addItems(value)
        if key == "shortcuts_list" and not self.loading_shortcuts and not self.is_updating_from_tree: self.load_shortcuts_to_tree()
    def _get_font_desc(self, target):
        prefix = "" if target == "main" else "desc_"
        fam = config.get(f"{prefix}font_family"); size = config.get(f"{prefix}font_size"); styles = []
        if config.get(f"{prefix}font_bold"): styles.append("Bold")
        if config.get(f"{prefix}font_italic"): styles.append("Italic")
        style_str = ",".join(styles) if styles else "Normal"
        return f"{fam} / {size}pt ({style_str})"
    def pick_position(self): self.hide(); self.picker = PositionSelector(); self.picker.positionSelected.connect(self.show); self.picker.showFullScreen()
    def add_icon_picker(self, layout, label_text, key):
        container = QWidget(); hbox = QHBoxLayout(container); hbox.setContentsMargins(0,0,0,0)
        current_path = config.get("icon_paths")[key]; btn_pick = QPushButton(); btn_clear = QPushButton("×"); btn_clear.setFixedSize(30, 24); font_x = QFont("Arial", 12, QFont.Weight.Bold); btn_clear.setFont(font_x)
        def update_ui(path):
            if path and os.path.exists(path): btn_pick.setText(os.path.basename(path)); btn_clear.setEnabled(True)
            else: btn_pick.setText(config.tr("ui.common.file_select", "ファイル選択...")); btn_clear.setEnabled(False)
        update_ui(current_path); self.icon_ui_updaters[key] = update_ui
        def pick():
            path, _ = QFileDialog.getOpenFileName(self, "画像を選択", "", "Images (*.png *.jpg *.bmp)")
            if path: config.set_icon_path(key, path); update_ui(path)
        def clear(): config.set_icon_path(key, ""); update_ui("")
        btn_pick.clicked.connect(pick); btn_clear.clicked.connect(clear); hbox.addWidget(btn_pick); hbox.addWidget(btn_clear); layout.addRow(label_text, container)
    def add_custom_font_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "フォント", "", "Font Files (*.ttf *.otf)"); 
        if path: 
            config.add_custom_font(path)
            if path not in [self.list_fonts.item(i).text() for i in range(self.list_fonts.count())]: self.list_fonts.addItem(path)
    def remove_custom_font_file(self):
        selected_items = self.list_fonts.selectedItems()
        if not selected_items: return
        for item in selected_items: path = item.text(); config.remove_custom_font(path); row = self.list_fonts.row(item); self.list_fonts.takeItem(row)
    def select_font(self, target="main"):
        prefix = "" if target == "main" else "desc_"
        current_font = QFont(config.get(f"{prefix}font_family"), config.get(f"{prefix}font_size")); current_font.setBold(config.get(f"{prefix}font_bold")); current_font.setItalic(config.get(f"{prefix}font_italic")); current_font.setUnderline(config.get(f"{prefix}font_underline")); current_font.setStrikeOut(config.get(f"{prefix}font_strikeout"))
        font, ok = QFontDialog.getFont(current_font, self, config.tr("ui.common.font", "フォント選択"))
        if ok:
            config.set(f"{prefix}font_family", font.family()); config.set(f"{prefix}font_size", font.pointSize()); config.set(f"{prefix}font_bold", font.bold()); config.set(f"{prefix}font_italic", font.italic()); config.set(f"{prefix}font_underline", font.underline()); config.set(f"{prefix}font_strikeout", font.strikeOut())

# --- Logging Setup ---
def setup_logging():
    log_file = config.config_dir / "debug.log"
    # 基本設定
    logging.basicConfig(
        level=logging.ERROR, 
        filename=str(log_file), 
        format='%(asctime)s - %(levelname)s - %(message)s',
        encoding='utf-8' # UTF-8指定
    )
    def excepthook(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Uncaught exception:\n" + tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = excepthook

# --- Main App ---
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setQuitOnLastWindowClosed(False)

    socket = QLocalSocket()
    socket.connectToServer(IPC_KEY)
    
    if socket.waitForConnected(500):
        socket.write(b"SHOW_SETTINGS")
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        sys.exit(0)

    config.init_paths()
    setup_logging()
    config.load()
    
    QLocalServer.removeServer(IPC_KEY)
    server = QLocalServer()
    server.listen(IPC_KEY)
    
    app_icon_path = config.get_app_icon_path()
    app_icon = QIcon(app_icon_path) if app_icon_path else None
    if app_icon: app.setWindowIcon(app_icon)

    overlay = OverlayWindow()
    overlay.show()
    
    # MouseHaloの初期化 (クラス内でタイマー制御・表示制御を行う)
    halo = MouseHalo()
    # 初期状態で有効なら表示する（クラス内でupdate_settingsが呼ばれるが、明示的に制御）
    if config.get("mouse_halo_enabled"):
        halo.show()

    cs_window = CheatSheetWindow()
    if app_icon: cs_window.setWindowIcon(app_icon)
    cs_overlay = CheatSheetOverlay()
    
    worker = InputWorker()
    worker.key_signal.connect(overlay.add_key)
    worker.hold_signal.connect(overlay.maintain_key)
    worker.mouse_signal.connect(lambda t, m: overlay.add_key(t, is_mod_pressed=m))
    worker.halo_click_signal.connect(halo.set_click)
    worker.halo_scroll_signal.connect(halo.set_scroll)
    
    # マウス移動はMouseHalo内のタイマーで行うためシグナル接続不要
    
    worker.cheat_window_signal.connect(cs_window.toggle_visibility)
    worker.cheat_overlay_signal.connect(cs_overlay.show_overlay)

    settings_dialog = None
    def show_settings():
        nonlocal settings_dialog
        if settings_dialog is None:
            settings_dialog = SettingsDialog()
            if app_icon: settings_dialog.setWindowIcon(app_icon)
        settings_dialog.show()
        settings_dialog.raise_()
        settings_dialog.activateWindow()
        
    def handle_new_connection():
        client_socket = server.nextPendingConnection()
        if client_socket.waitForReadyRead(1000):
            msg = client_socket.readAll().data()
            if msg == b"SHOW_SETTINGS":
                show_settings()
        client_socket.disconnectFromServer()
    
    server.newConnection.connect(handle_new_connection)

    tray = QSystemTrayIcon()
    tray_icon = app_icon if app_icon else app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    tray.setIcon(tray_icon)
    tray.setToolTip(APP_NAME)
    menu = QMenu()
    
    action_log = QAction(config.tr("ui.tray.log", "ログ 有効/無効"), menu, checkable=True)
    action_log.setChecked(config.get("log_enabled"))
    action_log.triggered.connect(lambda c: config.set("log_enabled", c))
    menu.addAction(action_log)
    
    action_cheat = QAction(config.tr("ui.tray.cheat", "チートシート 有効/無効"), menu, checkable=True)
    action_cheat.setChecked(config.get("cheat_sheet_enabled"))
    action_cheat.triggered.connect(lambda c: config.set("cheat_sheet_enabled", c))
    menu.addAction(action_cheat)
    
    menu.addSeparator()
    action_settings = QAction(config.tr("ui.tray.settings", "設定"), menu)
    action_settings.triggered.connect(show_settings)
    menu.addAction(action_settings)
    menu.addSeparator()
    action_exit = QAction(config.tr("ui.tray.exit", "アプリの終了"), menu)
    
    # --- 終了処理 ---
    def quit_app():
        config.force_save()     # 未保存があれば保存
        worker.stop_listening() # リスナー停止
        
        if tray.isVisible():
            tray.setVisible(False) # 幽霊アイコン対策
        
        app.quit()
    action_exit.triggered.connect(quit_app)
    
    menu.addAction(action_exit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: show_settings() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    
    def sync_tray_menu(key, val):
        if key == "log_enabled": action_log.setChecked(val)
        elif key == "cheat_sheet_enabled": action_cheat.setChecked(val)
    
    def refresh_tray_menu():
        # 言語切り替え時にメニューのテキストを更新
        action_log.setText(config.tr("ui.tray.log", "ログ 有効/無効"))
        action_cheat.setText(config.tr("ui.tray.cheat", "チートシート 有効/無効"))
        action_settings.setText(config.tr("ui.tray.settings", "設定"))
        action_exit.setText(config.tr("ui.tray.exit", "アプリの終了"))

    config.changed_signal.connect(sync_tray_menu)
    config.language_changed_signal.connect(refresh_tray_menu)

    tray.setVisible(True)
    worker.start_listening()
    clean_timer = QTimer()
    clean_timer.timeout.connect(overlay.clean_up)
    clean_timer.start(100)

    show_settings()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
