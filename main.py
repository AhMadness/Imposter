from __future__ import annotations

import json
import os
import random
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import qrcode
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QSpinBox, QCheckBox, QMessageBox, QStackedWidget,
    QFrame, QScrollArea, QGridLayout, QToolButton, QSizePolicy, QComboBox
)

# -------------------------
# Helpers
# -------------------------

@lru_cache(maxsize=1)
def app_base_dir() -> str:
    # Works for script and for PyInstaller (onedir/onefile).
    # Prefer _MEIPASS when bundled data is embedded in onefile builds.
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.isdir(os.path.join(meipass, "data")):
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def app_icon_path() -> str:
    return os.path.join(app_base_dir(), "data", "images", "icon.ico")


def words_db_path() -> str:
    data_dir = os.path.join(app_base_dir(), "data")
    for name in ("words.json", "words.JSON"):
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        f"Missing words database in {data_dir}. Expected one of: words.json, words.JSON"
    )

def load_words_db(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def hr() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line

def display_name(raw: str) -> str:
    return raw.strip()

def categories_images_dir() -> str:
    return os.path.join(app_base_dir(), "data", "images", "categories")


def load_category_pixmap(cat_id: str, img_ref: str = "", w: int = 300, h: int = 260) -> QPixmap:
    base = categories_images_dir()

    # Prefer explicit image ref from DB (manager supports this key).
    img_ref = os.path.basename((img_ref or "").strip())
    if img_ref:
        p = os.path.join(base, img_ref)
        if os.path.exists(p):
            pix = QPixmap(p)
            if not pix.isNull():
                return pix.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )

    # Fallback to slug/id-based file names for backward compatibility.
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = os.path.join(base, f"{cat_id}{ext}")
        if os.path.exists(p):
            pix = QPixmap(p)
            if not pix.isNull():
                return pix.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )

    placeholder = QPixmap(w, h)
    placeholder.fill(Qt.GlobalColor.darkGray)
    return placeholder

# -------------------------
# Language + flags
# -------------------------

class Lang:
    AR = "AR"
    EN = "EN"


def tr(lang: str, en: str, ar: str) -> str:
    return ar if lang == Lang.AR else en


def apply_direction(widget: QWidget, lang: str) -> None:
    direction = (
        Qt.LayoutDirection.RightToLeft
        if lang == Lang.AR
        else Qt.LayoutDirection.LeftToRight
    )
    widget.setLayoutDirection(direction)

def make_lang_toggle(get_lang, set_lang) -> QPushButton:
    btn = QPushButton()
    btn.setObjectName("langBtn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    # smaller so it doesn't bully titles
    btn.setFixedSize(84, 32)

    base_style = """
        QPushButton#langBtn {
            border: 1px solid #444;
            border-radius: 10px;
            padding-left: 6px;
            padding-right: 2px;
            background: #222;
            color: #eee;
            font-weight: bold;
        }
        QPushButton#langBtn:hover { background: #2a2a2a; }
        QPushButton#langBtn:pressed { background: #1c1c1c; }
    """
    btn.setStyleSheet(base_style)

    def render():
        lang = get_lang()
        btn.setText("AR" if lang == Lang.AR else "EN")


    def toggle():
        cur = get_lang()
        new_lang = Lang.EN if cur == Lang.AR else Lang.AR
        set_lang(new_lang)   # this will call refresh_language on pages
        render()             # keep this button synced immediately too

    btn.clicked.connect(toggle)

    # expose a tiny sync method so pages can force-render it
    btn.sync_lang = render  # type: ignore

    render()
    return btn





def make_qr_pixmap(payload: str, size_px: int = 320) -> QPixmap:
    """
    Robust conversion: generate QR as PNG bytes, let Qt decode it.
    Avoids raw RGB/QImage alignment issues that crash on some setups.
    """
    import io

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")  # PIL image
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    pix = QPixmap()
    pix.loadFromData(buf.getvalue(), "PNG")
    return pix.scaled(
        size_px, size_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )


# -------------------------
# Game model
# -------------------------


@dataclass
class Category:
    id: str
    name: str
    name_ar: str
    img: str
    words: List[dict]


@dataclass
class PlayerAssignment:
    name: str
    is_imposter: bool


@dataclass
class GameState:
    category: Category
    word_en: str
    word_ar: str
    hint_en: str
    hint_ar: str
    assignments: List[PlayerAssignment]
    alive: Dict[str, bool]
    imposters_left: int


def build_categories(db: dict) -> List[Category]:
    cats = []
    for c in db.get("categories", []):
        words = c.get("words", [])
        cid = str(c.get("id", "")).strip()
        name = str(c.get("name", "")).strip() or cid
        name_ar = str(c.get("name_ar", "")).strip() or name
        img = str(c.get("img", "")).strip()
        cats.append(Category(
            id=cid,
            name=name,
            name_ar=name_ar,
            img=img,
            words=words
        ))
    return cats


def pick_word_both(cat: Category) -> Tuple[str, str, str, str]:
    if not cat.words:
        raise ValueError("Category has no words.")
    item = random.choice(cat.words)

    raw_word_en = str(item.get("word", "")).strip()
    raw_word_ar = str(item.get("word_ar", "")).strip()
    raw_hint_en = str(item.get("hint", "")).strip()
    raw_hint_ar = str(item.get("hint_ar", "")).strip()

    # Symmetric fallback keeps both languages usable even if one side is missing in JSON.
    word_en = raw_word_en or raw_word_ar
    word_ar = raw_word_ar or word_en
    hint_en = raw_hint_en or raw_hint_ar
    hint_ar = raw_hint_ar or hint_en

    if not word_en and not word_ar:
        raise ValueError("Selected word is empty.")

    return word_en, word_ar, hint_en, hint_ar



def assign_players(
    names: List[str],
    category: Category,
    num_imposters: int,
) -> GameState:
    word_en, word_ar, hint_en, hint_ar = pick_word_both(category)

    n = len(names)
    if n < 3:
        raise ValueError("Need at least 3 players.")
    if num_imposters < 1 or num_imposters >= n:
        raise ValueError("Number of imposters must be at least 1 and less than number of players.")

    imposter_set = set(random.sample(names, k=num_imposters))

    assignments: List[PlayerAssignment] = []
    for name in names:
        assignments.append(PlayerAssignment(
            name=name,
            is_imposter=(name in imposter_set),
        ))
    alive = {p.name: True for p in assignments}
    return GameState(
        category=category,
        word_en=word_en,
        word_ar=word_ar,
        hint_en=hint_en,
        hint_ar=hint_ar,
        assignments=assignments,
        alive=alive,
        imposters_left=num_imposters
    )


def count_alive(alive: Dict[str, bool]) -> int:
    return sum(1 for v in alive.values() if v)


def check_winner(state: GameState) -> Optional[str]:
    alive_imposters = sum(
        1 for p in state.assignments
        if p.is_imposter and state.alive.get(p.name, False)
    )
    alive_crew = sum(
        1 for p in state.assignments
        if (not p.is_imposter) and state.alive.get(p.name, False)
    )

    # crew win: all imposters eliminated
    if alive_imposters == 0:
        return "CREW"

    # imposter win: all crew eliminated
    if alive_crew == 0:
        return "IMPOSTERS"

    # otherwise game continues (even if tie)
    return None

def build_qr_payload(state: GameState, player_name: str, is_imposter: bool, include_hint: bool, lang: str) -> str:
    if lang == Lang.AR:
        word = state.word_ar
        hint = state.hint_ar
    else:
        word = state.word_en
        hint = state.hint_en

    if is_imposter:
        if lang == Lang.AR:
            if include_hint and hint:
                payload = f"{player_name}، أنت المحتال!\nتلميح: {hint}"
            else:
                payload = f"{player_name}، أنت المحتال!"
        else:
            if include_hint and hint:
                payload = f"{player_name}, you are an IMPOSTER!\nHINT: {hint}"
            else:
                payload = f"{player_name}, you are an IMPOSTER!"
    else:
        payload = (
            f"{player_name}\nالكلمة: {word}"
            if lang == Lang.AR
            else f"{player_name}\nWORD: {word}"
        )

    return payload


class CategorySelectPage(QWidget):
    def __init__(self, categories: List[Category], on_start_setup_with_category, get_lang, set_lang):
        super().__init__()
        self.get_lang = get_lang
        self.set_lang = set_lang
        self.categories = categories
        self.on_start_setup_with_category = on_start_setup_with_category
        self.selected: Optional[Category] = None
        self.selected_ids: set[str] = set()

        root = QVBoxLayout(self)

        header = QHBoxLayout()

        self.title = QLabel("Choose Category")
        self.title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lang_btn = make_lang_toggle(self.get_lang, self.set_lang)

        # ✅ invisible left spacer with SAME width as lang button
        left_stub = QWidget()
        left_stub.setFixedSize(self.lang_btn.sizeHint())

        header.addWidget(left_stub)  # left
        header.addWidget(self.title, 1)  # center (true center now)
        header.addWidget(self.lang_btn)  # right

        root.addLayout(header)

        root.addSpacing(8)

        root.addWidget(hr())

        # scrollable grid of category cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        root.addWidget(hr())

        # chosen category label row
        chosen_row = QHBoxLayout()

        self.chosen_lbl = QLabel("Chosen category:")
        self.chosen_lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))

        self.chosen_value = QLabel("-")
        self.chosen_value.setFont(QFont("Arial", 11))
        self.chosen_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        chosen_row.addWidget(self.chosen_lbl)
        chosen_row.addWidget(self.chosen_value, 1)
        root.addLayout(chosen_row)

        # buttons
        self.random_btn = QPushButton("Choose Randomly (From ALL Categories)")
        self.random_btn.clicked.connect(self.choose_random)
        self.random_btn.setMinimumHeight(44)
        root.addWidget(self.random_btn)

        self.start_btn = QPushButton("Start (Choose Randomly from Selected Categories)")
        self.start_btn.clicked.connect(self.start_selected)
        self.start_btn.setMinimumHeight(44)
        root.addWidget(self.start_btn)

        self.populate_grid()

    def refresh_language(self):
        if hasattr(self.lang_btn, "sync_lang"):
            self.lang_btn.sync_lang()
        lang = self.get_lang()

        is_ar = (lang == Lang.AR)
        apply_direction(self, lang)
        self.title.setText("اختر الفئة" if is_ar else "Choose Category")
        self.chosen_lbl.setText("الفئة المختارة:" if is_ar else "Chosen category:")
        self.random_btn.setText("اختيار عشوائي (من كل الفئات)" if is_ar else "Choose Randomly (From ALL Categories)")
        self.start_btn.setText(
            "ابدأ (اختيار عشوائي من الفئات المحددة)" if is_ar else "Start (Choose Randomly from Selected Categories)")

        # update chosen categories label value
        if not self.selected_ids:
            self.chosen_value.setText("-")
        else:
            names = []
            for c in self.categories:
                if c.id in self.selected_ids:
                    names.append(c.name_ar if lang == Lang.AR else c.name)
            self.chosen_value.setText(", ".join(names))

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self.lang_btn, "sync_lang"):
            self.lang_btn.sync_lang()
        self.refresh_language()

    def populate_grid(self):
        # 3 columns grid
        cols = 1
        for i, cat in enumerate(self.categories):
            r = i // cols
            c = i % cols

            btn = QToolButton()

            # no label
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setText("")  # just to be extra sure nothing shows
            btn.setProperty("cat_id", cat.id)

            # bigger image
            btn.setIcon(QIcon(load_category_pixmap(cat.id, cat.img, w=360, h=220)))
            btn.setIconSize(QSize(360, 220))

            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setFixedWidth(310)  # tweak this number
            btn.setMinimumHeight(155)

            # store cat on button
            btn.toggled.connect(lambda checked, cc=cat: self.toggle_category(cc, checked))

            self.grid.addWidget(btn, r, c, alignment=Qt.AlignmentFlag.AlignHCenter)

        # stretch columns
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    def select_category(self, cat: Category):
        # force a single selection (used by Choose Randomly)
        self.selected_ids = {cat.id}

        # update button states
        for i in range(self.grid.count()):
            w = self.grid.itemAt(i).widget()
            if isinstance(w, QToolButton):
                w.blockSignals(True)
                w.setChecked(w.property("cat_id") == cat.id)
                w.blockSignals(False)

        self.chosen_value.setText(cat.name_ar if self.get_lang() == Lang.AR else cat.name)

    def choose_random(self):
        if not self.categories:
            return
        playable = [c for c in self.categories if c.words]
        if not playable:
            QMessageBox.information(
                self,
                tr(self.get_lang(), "No categories", "لا توجد فئات"),
                tr(
                    self.get_lang(),
                    "No playable categories found. Add words in Imposter Manager first.",
                    "لا توجد فئات قابلة للعب. أضف كلمات في Imposter Manager أولاً.",
                ),
            )
            return
        cat = random.choice(playable)

        # show what got picked (label only), but DO NOT select anything
        self.chosen_value.setText(cat.name_ar if self.get_lang() == Lang.AR else cat.name)

        # clear any existing selections visually + logically
        self.selected_ids.clear()
        for i in range(self.grid.count()):
            w = self.grid.itemAt(i).widget()
            if isinstance(w, QToolButton):
                w.blockSignals(True)
                w.setChecked(False)
                w.blockSignals(False)

        # go start setup with that random category
        self.on_start_setup_with_category(cat)

    def toggle_category(self, cat: Category, checked: bool):
        if checked:
            self.selected_ids.add(cat.id)
        else:
            self.selected_ids.discard(cat.id)

        # update label
        if not self.selected_ids:
            self.chosen_value.setText("-")
        else:
            lang = self.get_lang()
            names = [(c.name_ar if lang == Lang.AR else c.name) for c in self.categories if c.id in self.selected_ids]
            self.chosen_value.setText(", ".join(names))

    def start_selected(self):
        if not self.selected_ids:
            QMessageBox.information(
                self,
                tr(self.get_lang(), "Pick one", "تنبيه"),
                tr(self.get_lang(), "Select at least one category first.", "اختَر فئة واحدة على الأقل أولاً."),
            )
            return

        playable = [c for c in self.categories if c.id in self.selected_ids and c.words]
        if not playable:
            QMessageBox.information(
                self,
                tr(self.get_lang(), "No words", "لا توجد كلمات"),
                tr(
                    self.get_lang(),
                    "Selected categories have no words. Add words in Imposter Manager first.",
                    "الفئات المحددة لا تحتوي على كلمات. أضف كلمات في Imposter Manager أولاً.",
                ),
            )
            return

        chosen_cat = random.choice(playable)
        if not chosen_cat:
            QMessageBox.critical(
                self,
                tr(self.get_lang(), "Error", "خطأ"),
                tr(self.get_lang(), "Selected category not found.", "لم يتم العثور على الفئة المحددة."),
            )
            return

        self.on_start_setup_with_category(chosen_cat)

    def reset_selection(self):
        self.selected_ids.clear()
        self.chosen_value.setText("-")

        # uncheck all buttons in the grid
        for i in range(self.grid.count()):
            w = self.grid.itemAt(i).widget()
            if isinstance(w, QToolButton):
                w.blockSignals(True)
                w.setChecked(False)
                w.blockSignals(False)

# -------------------------
# UI
# -------------------------

class SetupPage(QWidget):
    def __init__(self, on_start, on_back_to_categories, get_lang, set_lang):
        super().__init__()
        self.on_start = on_start
        self.get_lang = get_lang
        self.set_lang = set_lang
        self.on_back_to_categories = on_back_to_categories
        self.category: Optional[Category] = None

        root = QVBoxLayout(self)

        top_row = QHBoxLayout()

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedHeight(35)
        self.back_btn.clicked.connect(self.on_back_to_categories)
        top_row.addWidget(self.back_btn)

        top_row.addStretch(1)

        self.cat_label = QLabel("Category: (hidden)")
        self.cat_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.cat_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cat_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.cat_label.mousePressEvent = self.toggle_category_visibility  # type: ignore
        self._cat_revealed = False
        top_row.addWidget(self.cat_label, 1, Qt.AlignmentFlag.AlignCenter)

        top_row.addStretch(1)

        # language toggle far right
        self.lang_btn = make_lang_toggle(self.get_lang, self.set_lang)
        top_row.addWidget(self.lang_btn)

        root.addLayout(top_row)

        root.addSpacing(4)
        root.addWidget(hr())
        root.addSpacing(6)

        self.add_players_title = QLabel("~ Add Players ~")
        self.add_players_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_players_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        root.addWidget(self.add_players_title)

        add_row = QHBoxLayout()
        add_row.addStretch(1)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Type a name and press Enter")
        self.name_input.setFixedWidth(200)  # narrower
        self.name_input.setFixedHeight(44)  # taller
        self.name_input.setAlignment(Qt.AlignmentFlag.AlignCenter)  # text centered in box
        self.name_input.returnPressed.connect(self.add_name)

        add_row.addWidget(self.name_input)

        add_row.addStretch(1)
        root.addLayout(add_row)
        root.addSpacing(8)  # space above the list

        self.names_list = QListWidget()
        self.names_list.setStyleSheet("QListWidget::item { text-align: center; }")
        self.names_list.setFixedWidth(200)
        list_row = QHBoxLayout()
        list_row.addStretch(1)
        list_row.addWidget(self.names_list)
        list_row.addStretch(1)
        root.addLayout(list_row, 1)
        root.addSpacing(8)  # space below the list
        self.names_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.names_list.customContextMenuRequested.connect(self.on_names_context_menu)

        row2 = QHBoxLayout()

        self.imposters_lbl = QLabel("# Imposters:")
        row2.addWidget(self.imposters_lbl)

        self.imposters_spin = QSpinBox()
        self.imposters_spin.setMinimum(1)
        self.imposters_spin.setMaximum(10)
        self.imposters_spin.setValue(1)
        self._sync_imposters_limits()
        row2.addWidget(self.imposters_spin)

        row2.addSpacing(8)

        self.minutes_lbl = QLabel("Meeting Minutes:")
        row2.addWidget(self.minutes_lbl)

        self.minutes_spin = QSpinBox()
        self.minutes_spin.setMinimum(1)
        self.minutes_spin.setMaximum(30)
        self.minutes_spin.setValue(3)
        row2.addWidget(self.minutes_spin)

        row2_host = QHBoxLayout()
        row2_host.addStretch(1)
        row2_host.addLayout(row2)
        row2_host.addStretch(1)
        root.addLayout(row2_host)

        self.hint_check = QCheckBox("Include hint for imposters")
        self.hint_check.setChecked(True)

        hint_row = QHBoxLayout()
        hint_row.addStretch(1)
        hint_row.addWidget(self.hint_check)
        hint_row.addStretch(1)
        root.addLayout(hint_row)

        root.addWidget(hr())

        start_row = QHBoxLayout()
        start_row.addStretch(1)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_game)
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setMinimumWidth(220)
        start_row.addWidget(self.start_btn)

        start_row.addStretch(1)
        root.addLayout(start_row)

    def set_category(self, category: Category):
        self.category = category
        if self._cat_revealed:
            lang = self.get_lang()
            name = category.name_ar if lang == Lang.AR else category.name
            self.cat_label.setText(f"Category: {name}")
        else:
            self.cat_label.setText("Category: (hidden)")

    def showEvent(self, event):
        super().showEvent(event)

        if hasattr(self.lang_btn, "sync_lang"):
            self.lang_btn.sync_lang()
        self.refresh_language()

        QTimer.singleShot(0, self.name_input.setFocus)

    def refresh_language(self):
        if hasattr(self.lang_btn, "sync_lang"):
            self.lang_btn.sync_lang()
        lang = self.get_lang()
        is_ar = (self.get_lang() == Lang.AR)
        apply_direction(self, lang)

        self.back_btn.setText("رجوع" if is_ar else "Back")
        self.add_players_title.setText("~ إضافة لاعبين ~" if is_ar else "~ Add Players ~")
        self.name_input.setPlaceholderText("اكتب الاسم واضغط Enter" if is_ar else "Type a name and press Enter")
        self.imposters_lbl.setText("عدد المحتالين:" if is_ar else "# Imposters:")
        self.minutes_lbl.setText("دقائق الاجتماع:" if is_ar else "Meeting Minutes:")
        self.hint_check.setText("إظهار تلميح للمحتالين" if is_ar else "Include hint for imposters")
        self.start_btn.setText("ابدأ" if is_ar else "Start")

        # category label text (respects hidden/revealed)
        hidden = "الفئة: (مخفي)" if is_ar else "Category: (hidden)"
        prefix = "الفئة:" if is_ar else "Category:"

        if not self.category:
            self.cat_label.setText(hidden)
            return

        if self._cat_revealed:
            name = self.category.name_ar if is_ar else self.category.name
            self.cat_label.setText(f"{prefix} {name}")
        else:
            self.cat_label.setText(hidden)

    def toggle_category_visibility(self, event):
        self._cat_revealed = not self._cat_revealed
        self.refresh_language()

    def add_name(self):
        name = self.name_input.text().strip()
        if not name:
            return
        existing = {
            (self.names_list.item(i).data(Qt.ItemDataRole.UserRole) or self.names_list.item(
                i).text()).strip().casefold()
            for i in range(self.names_list.count())
        }
        if name.casefold() in existing:
            is_ar = (self.get_lang() == Lang.AR)
            QMessageBox.information(
                self,
                "تنبيه" if is_ar else "Nope",
                "هذا الاسم موجود بالفعل." if is_ar else "That name already exists."
            )
            return

        raw = name

        item = QListWidgetItem(display_name(raw))  # emoji version for UI
        item.setData(Qt.ItemDataRole.UserRole, raw)  # raw name for logic
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        self.names_list.addItem(item)
        self._sync_imposters_limits()
        self.name_input.clear()

    def _max_imposters_for_players(self, n: int) -> int:
        # hard cap
        if n < 4:
            return 1  # doesn't really matter since game won't start <3 anyway
        if n == 4:
            return 1
        if 5 <= n <= 8:
            return 2
        if 9 <= n <= 10:
            return 3
        return 4  # 11+

    def _sync_imposters_limits(self):
        n = self.names_list.count()
        max_imp = min(4, self._max_imposters_for_players(n))
        max_imp = max(1, max_imp)

        self.imposters_spin.setMaximum(max_imp)

        # clamp current value if it became illegal
        if self.imposters_spin.value() > max_imp:
            self.imposters_spin.setValue(max_imp)

    def on_names_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        item = self.names_list.itemAt(pos)
        is_ar = (self.get_lang() == Lang.AR)

        if item is not None:
            act_remove = menu.addAction("حذف" if is_ar else "Remove")
            chosen = menu.exec(self.names_list.mapToGlobal(pos))
            if chosen == act_remove:
                self.names_list.takeItem(self.names_list.row(item))
                self._sync_imposters_limits()
        else:
            if self.names_list.count() == 0:
                return
            act_clear = menu.addAction("مسح الكل" if is_ar else "Clear All")
            chosen = menu.exec(self.names_list.mapToGlobal(pos))
            if chosen == act_clear:
                self.names_list.clear()
                self._sync_imposters_limits()

    def start_game(self):
        is_ar = (self.get_lang() == Lang.AR)
        if not self.category:
            QMessageBox.critical(
                self,
                "خطأ" if is_ar else "Error",
                "لم يتم اختيار أي فئة." if is_ar else "No category selected."
            )
            return

        if not self.category.words:
            QMessageBox.information(
                self,
                "تنبيه" if is_ar else "No words",
                "الفئة المختارة لا تحتوي على كلمات. أضف كلمات في Imposter Manager أولاً."
                if is_ar else
                "Selected category has no words. Add words in Imposter Manager first."
            )
            return

        names = [
            (self.names_list.item(i).data(Qt.ItemDataRole.UserRole) or self.names_list.item(i).text()).strip()
            for i in range(self.names_list.count())
        ]

        num_imposters = int(self.imposters_spin.value())
        minutes = int(self.minutes_spin.value())
        include_hint = self.hint_check.isChecked()

        try:
            if self.names_list.count() < 3:
                is_ar = (self.get_lang() == Lang.AR)
                QMessageBox.information(
                    self,
                    "تنبيه" if is_ar else "Nope",
                    "لازم على الأقل 3 لاعبين." if is_ar else "You need at least 3 players."
                )
                return

            max_imp = min(4, self._max_imposters_for_players(len(names)))
            if num_imposters > max_imp:
                is_ar = (self.get_lang() == Lang.AR)
                QMessageBox.information(
                    self,
                    "تنبيه" if is_ar else "Nope",
                    f"الحد الأقصى للمحتالين هو {max_imp}." if is_ar else f"Max imposters is {max_imp}."
                )
                return

            self.on_start(self.category, names, num_imposters, include_hint, minutes)

        except Exception as e:
            QMessageBox.critical(self, "خطأ" if is_ar else "Error", str(e))


class RevealPage(QWidget):
    def __init__(self, on_done_reveal, on_abort_to_setup, get_lang, set_lang):
        super().__init__()
        self.on_done_reveal = on_done_reveal
        self.on_abort_to_setup = on_abort_to_setup
        self.get_lang = get_lang
        self.set_lang = set_lang
        self.include_hint = True

        self.state: Optional[GameState] = None
        self.idx = 0
        self._qr_cache: Dict[str, QPixmap] = {}

        root = QVBoxLayout(self)

        header = QHBoxLayout()

        self.title = QLabel("Scan Your QR")
        self.title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lang_btn = make_lang_toggle(self.get_lang, self.set_lang)

        # ✅ invisible left placeholder with same size as lang button
        left_stub = QWidget()
        left_stub.setFixedSize(self.lang_btn.sizeHint())

        header.addWidget(left_stub)  # left
        header.addWidget(self.title, 1)  # center (true center)
        header.addWidget(self.lang_btn)  # right

        root.addLayout(header)

        root.addSpacing(8)
        root.addWidget(hr())
        root.addSpacing(8)

        self.name_label = QLabel("")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        root.addWidget(self.name_label)

        self.qr_label = QLabel("")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.qr_label, 1)

        root.addWidget(hr())

        btn_row = QHBoxLayout()
        self.abort_btn = QPushButton("Back")
        self.abort_btn.setFixedHeight(40)
        self.abort_btn.clicked.connect(self.on_abort_to_setup)
        btn_row.addWidget(self.abort_btn)

        btn_row.addStretch(1)
        root.addSpacing(10)

        self.next_btn = QPushButton("Next")
        self.next_btn.setFixedHeight(40)
        self.next_btn.clicked.connect(self.next_player)
        self.next_btn.setEnabled(True)
        btn_row.addWidget(self.next_btn)

        root.addLayout(btn_row)

    def load_state(self, state: GameState, include_hint: bool):
        self.state = state
        self.include_hint = include_hint
        self.idx = 0
        self._qr_cache.clear()
        self.next_btn.setEnabled(True)
        self.update_view()

    def refresh_language(self):
        if hasattr(self.lang_btn, "sync_lang"):
            self.lang_btn.sync_lang()
        lang = self.get_lang()
        apply_direction(self, lang)

        self.title.setText("امسح رمز QR" if lang == Lang.AR else "Scan Your QR")
        self.update_view()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self.lang_btn, "sync_lang"):
            self.lang_btn.sync_lang()
        self.refresh_language()

    def update_view(self):
        if not self.state:
            return
        if self.idx < 0 or self.idx >= len(self.state.assignments):
            return

        self.name_label.setText(display_name(self.state.assignments[self.idx].name))

        ass = self.state.assignments[self.idx]
        payload = build_qr_payload(self.state, ass.name, ass.is_imposter, self.include_hint, self.get_lang())
        pix = self._qr_cache.get(payload)
        if pix is None:
            pix = make_qr_pixmap(payload, size_px=360)
            self._qr_cache[payload] = pix
        if pix.isNull():
            QMessageBox.critical(
                self,
                tr(self.get_lang(), "QR Error", "خطأ QR"),
                tr(self.get_lang(), "Failed to load QR pixmap.", "فشل تحميل صورة رمز QR."),
            )
        self.qr_label.setPixmap(pix)

        # 👇 NEW: update button labels based on position
        lang = self.get_lang()
        is_last = self.idx == len(self.state.assignments) - 1

        if lang == Lang.AR:
            self.next_btn.setText("ابدأ الاجتماع" if is_last else "التالي")
            self.abort_btn.setText("العودة للإعدادات" if self.idx == 0 else "السابق")
        else:
            self.next_btn.setText("Begin Meeting" if is_last else "Next")
            self.abort_btn.setText("Back to Setup" if self.idx == 0 else "Previous")

    def next_player(self):
        if not self.state:
            return

        self.idx += 1
        if self.idx >= len(self.state.assignments):
            self.on_done_reveal()
            return
        self.update_view()

class PlayPage(QWidget):
    def __init__(self, on_elimination, on_game_over, get_lang):
        super().__init__()
        self.get_lang = get_lang
        self.on_elimination = on_elimination
        self.on_game_over = on_game_over

        self.state: Optional[GameState] = None
        self.round_num = 1
        self.total_seconds = 0
        self.remaining = 0

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(20)

        # 1) Top center: Discussion -> Round -> line
        self.title = QLabel("Discussion")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.title.setFixedHeight(34)
        root.addWidget(self.title)

        root.setSpacing(16)

        self.round_label = QLabel("Round 1")
        self.round_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.round_label.setFont(QFont("Arial", 12))
        self.round_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.round_label.setFixedHeight(22)
        root.addWidget(self.round_label)

        root.addWidget(hr())

        # --- BIG TIMER + BUTTON DIRECTLY UNDER IT (CENTERED AS A GROUP) ---
        timer_block = QWidget()
        timer_layout = QVBoxLayout(timer_block)
        timer_layout.setContentsMargins(0, 0, 0, 0)
        timer_layout.setSpacing(6)  # tight gap so the button hugs the time

        # push the group to vertical center of the big block
        timer_layout.addStretch(1)

        self.timer_label = QLabel("00:00")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setFont(QFont("Arial", 74, QFont.Weight.Bold))
        self.timer_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # optional: if your font gets clipped, bump this slightly (130-150)
        self.timer_label.setFixedHeight(140)
        timer_layout.addWidget(self.timer_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.start_timer_btn = QPushButton("Start Timer")
        self.start_timer_btn.setMinimumHeight(50)
        self.start_timer_btn.setMinimumWidth(200)
        self.start_timer_btn.clicked.connect(self.toggle_timer)
        timer_layout.addWidget(self.start_timer_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        # push the group to vertical center
        timer_layout.addStretch(1)

        # give the whole block most of the page height
        root.addWidget(timer_block, 10)

        root.addWidget(hr())

        # 4) Vote row, with controllable dropdown size
        vote_row = QHBoxLayout()
        self.eliminate_lbl = QLabel("Eliminate:")
        vote_row.addWidget(self.eliminate_lbl)

        self.elim_combo = QComboBox()
        # 👇 YOU control size here
        self.elim_combo.setFixedWidth(200)
        self.elim_combo.setFixedHeight(40)
        vote_row.addWidget(self.elim_combo)

        self.skip_check = QCheckBox("Skip elimination this round")
        self.skip_check.setChecked(False)
        self.skip_check.stateChanged.connect(self.on_skip_toggle)
        vote_row.addWidget(self.skip_check)

        root.addLayout(vote_row)

        # 5) Remove back button, center confirm, taller
        self.eliminate_btn = QPushButton("Confirm")
        self.eliminate_btn.setMinimumHeight(50)
        self.eliminate_btn.setMinimumWidth(100)
        self.eliminate_btn.clicked.connect(self.confirm_round)

        confirm_row = QHBoxLayout()
        confirm_row.addStretch(1)
        confirm_row.addWidget(self.eliminate_btn)
        confirm_row.addStretch(1)
        root.addLayout(confirm_row)

        # 6) allow confirm BEFORE timer finishes
        self.eliminate_btn.setEnabled(False)

    def load_state(self, state: GameState, minutes: int):
        self.state = state
        self.round_num = 1
        self.total_seconds = max(1, minutes * 60)
        self.remaining = self.total_seconds
        self.timer.stop()

        is_ar = (self.get_lang() == Lang.AR)
        self.start_timer_btn.setText("ابدأ المؤقت" if is_ar else "Start Timer")
        self.skip_check.setChecked(False)

        self.populate_elim_list()
        self.update_round_label()
        self.update_timer_label()
        self.update_confirm_enabled()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "refresh_language"):
            self.refresh_language()

    def refresh_language(self):
        is_ar = (self.get_lang() == Lang.AR)
        apply_direction(self, self.get_lang())

        self.title.setText("نقاش" if is_ar else "Discussion")
        self.eliminate_lbl.setText("إخراج:" if is_ar else "Eliminate:")
        self.skip_check.setText("تخطي الإخراج هذه الجولة" if is_ar else "Skip elimination this round")
        self.eliminate_btn.setText("تأكيد" if is_ar else "Confirm")

        # round label
        self.round_label.setText(f"الجولة {self.round_num}" if is_ar else f"Round {self.round_num}")

        # timer button depends on running state
        if self.timer.isActive():
            self.start_timer_btn.setText("إيقاف المؤقت" if is_ar else "Stop Timer")
        else:
            self.start_timer_btn.setText("ابدأ المؤقت" if is_ar else "Start Timer")

    def populate_elim_list(self):
        if not self.state:
            return
        self.elim_combo.clear()

        alive_names = [p.name for p in self.state.assignments if self.state.alive.get(p.name)]
        for n in alive_names:
            self.elim_combo.addItem(n)

        self.elim_combo.setEnabled(not self.skip_check.isChecked())

    def update_round_label(self):
        is_ar = (self.get_lang() == Lang.AR)
        self.round_label.setText(f"الجولة {self.round_num}" if is_ar else f"Round {self.round_num}")

    def update_timer_label(self):
        mm = self.remaining // 60
        ss = self.remaining % 60
        self.timer_label.setText(f"{mm:02d}:{ss:02d}")

    def toggle_timer(self):
        if not self.state:
            return

        is_ar = (self.get_lang() == Lang.AR)
        if self.timer.isActive():
            # stop
            self.timer.stop()
            self.start_timer_btn.setText("ابدأ المؤقت" if is_ar else "Start Timer")
            return

        # start (or restart fresh)
        self.remaining = self.total_seconds
        self.update_timer_label()
        self.timer.start()
        self.start_timer_btn.setText("إيقاف المؤقت" if is_ar else "Stop Timer")

    def tick(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            self.remaining = 0
            self.update_timer_label()
            is_ar = (self.get_lang() == Lang.AR)
            self.start_timer_btn.setText("ابدأ المؤقت" if is_ar else "Start Timer")
            return
        self.update_timer_label()

    def on_skip_toggle(self):
        self.elim_combo.setEnabled(not self.skip_check.isChecked())
        self.update_confirm_enabled()

    def update_confirm_enabled(self):
        # 6) enable confirm if skip is checked OR a name exists
        if self.skip_check.isChecked():
            self.eliminate_btn.setEnabled(True)
            return
        self.eliminate_btn.setEnabled(self.elim_combo.count() > 0 and bool(self.elim_combo.currentText().strip()))

    def confirm_round(self):
        if not self.state:
            return

        # allow confirm anytime (timer can be running)
        if self.skip_check.isChecked():
            winner = check_winner(self.state)
            if winner:
                self.on_game_over(winner, self.state)
                return

            self.round_num += 1
            self.skip_check.setChecked(False)
            self.populate_elim_list()
            self.update_round_label()
            self.update_confirm_enabled()

            # reset timer for the next round (skip path)
            self.timer.stop()
            self.remaining = self.total_seconds
            self.update_timer_label()
            is_ar = (self.get_lang() == Lang.AR)
            self.start_timer_btn.setText("ابدأ المؤقت" if is_ar else "Start Timer")
            return

        name = self.elim_combo.currentText().strip()
        if not name:
            return
        if not self.state.alive.get(name):
            return

        # eliminate
        self.state.alive[name] = False
        was_imposter = next((p.is_imposter for p in self.state.assignments if p.name == name), False)
        if was_imposter:
            self.state.imposters_left -= 1

        self.on_elimination(name, was_imposter)
        return

class EliminationPage(QWidget):
    def __init__(self, on_next_round, get_lang):
        super().__init__()
        self.get_lang = get_lang
        self.on_next_round = on_next_round

        self.elim_name: Optional[str] = None
        self.was_imposter: Optional[bool] = None
        self.revealed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)

        root.addSpacing(16)

        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        root.addWidget(self.title)

        root.addSpacing(16)

        root.addWidget(hr())

        # big clickable reveal text
        self.reveal_label = QLabel("click to reveal")
        self.reveal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reveal_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.reveal_label.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.reveal_label, 1)

        root.addWidget(hr())

        root.addSpacing(16)

        # next button centered bottom
        self.next_btn = QPushButton("Next Round")
        self.next_btn.setMinimumHeight(52)
        self.next_btn.setMinimumWidth(220)
        self.next_btn.clicked.connect(self.on_next_round)
        self.next_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.next_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # make label clickable
        self.reveal_label.mousePressEvent = self._on_reveal_click  # type: ignore

    def set_result(self, name: str, was_imposter: bool):
        self.elim_name = name
        self.was_imposter = was_imposter
        self.revealed = False

        is_ar = (self.get_lang() == Lang.AR)
        self.title.setText(f"تم إخراج {name}!" if is_ar else f"{name} was eliminated!")
        self.reveal_label.setText("اضغط للكشف" if is_ar else "Click to reveal")
        self.next_btn.setText("الجولة التالية" if is_ar else "Next Round")

        self.next_btn.setEnabled(True)

    def _on_reveal_click(self, event):
        if self.revealed or self.was_imposter is None:
            return
        self.revealed = True
        is_ar = (self.get_lang() == Lang.AR)

        if self.was_imposter:
            self.reveal_label.setText("محتال ✅" if is_ar else "IMPOSTER ✅")
        else:
            self.reveal_label.setText("ليس محتال ❌" if is_ar else "NOT IMPOSTER ❌")

        self.next_btn.setEnabled(True)  # ✅ always

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "refresh_language"):
            self.refresh_language()

    def refresh_language(self):
        is_ar = (self.get_lang() == Lang.AR)
        apply_direction(self, self.get_lang())

        # if no current result yet, keep things simple
        if self.elim_name is None:
            self.reveal_label.setText("اضغط للكشف" if is_ar else "Click to reveal")
            self.next_btn.setText("الجولة التالية" if is_ar else "Next Round")
            return

        self.title.setText(f"تم إخراج {self.elim_name}!" if is_ar else f"{self.elim_name} was eliminated!")

        if not self.revealed:
            self.reveal_label.setText("اضغط للكشف" if is_ar else "Click to reveal")
        else:
            self.reveal_label.setText("محتال ✅" if is_ar else "IMPOSTER ✅") if self.was_imposter else \
                self.reveal_label.setText("ليس محتال ❌" if is_ar else "NOT IMPOSTER ❌")

        self.next_btn.setText("الجولة التالية" if is_ar else "Next Round")



class GameOverPage(QWidget):
    def __init__(self, on_restart, get_lang):
        super().__init__()
        self.on_restart = on_restart
        self.get_lang = get_lang
        self.state: Optional[GameState] = None


        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        root.addSpacing(8)

        self.title = QLabel("Game Over")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFont(QFont("Arial", 26, QFont.Weight.Bold))
        root.addWidget(self.title)

        self.result = QLabel("")
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        root.addWidget(self.result)

        root.addWidget(hr())
        root.addSpacing(6)

        # "card" container
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet("""
        QFrame {
            background: #1e1e1e;
            border: 1px solid #333;
            border-radius: 14px;
        }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)

        self.details = QLabel("")
        self.details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details.setWordWrap(True)
        self.details.setFont(QFont("Arial", 12))
        card_layout.addWidget(self.details)

        root.addWidget(card, 1)

        root.addSpacing(10)

        self.play_again_btn = QPushButton("Play Again")
        self.play_again_btn.clicked.connect(self.on_restart)
        self.play_again_btn.setMinimumHeight(52)
        self.play_again_btn.setMinimumWidth(240)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.play_again_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    def show_result(self, winner: str, state: GameState):
        self.state = state
        is_ar = (self.get_lang() == Lang.AR)

        if winner == "CREW":
            self.result.setText("فاز الفريق." if is_ar else "Crew wins.")
            winners = [p.name for p in state.assignments if (not p.is_imposter) and state.alive.get(p.name, False)]
            winners_title = "الفائزون:" if is_ar else "Winning crew:"
        else:
            self.result.setText("فاز المحتالون." if is_ar else "Imposters win.")
            winners = [p.name for p in state.assignments if p.is_imposter and state.alive.get(p.name, False)]
            winners_title = "المحتالون:" if is_ar else "Imposters:"

        winners_block = "\n".join(winners) if winners else ("(لا أحد)" if is_ar else "(none)")

        lang = self.get_lang()
        cat_name = state.category.name_ar if lang == Lang.AR else state.category.name
        secret_word = state.word_ar if lang == Lang.AR else state.word_en

        self.details.setText(
            (f"الفئة: {cat_name}\n" if is_ar else f"Category: {cat_name}\n") +
            (f"الكلمة السرية: {secret_word}\n" if is_ar else f"Secret word: {secret_word}\n") +
            f"{winners_title}\n{winners_block}"
        )

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "refresh_language"):
            self.refresh_language()

    def refresh_language(self):
        is_ar = (self.get_lang() == Lang.AR)
        apply_direction(self, self.get_lang())
        self.title.setText("انتهت اللعبة" if is_ar else "Game Over")
        self.play_again_btn.setText("العب مرة أخرى" if is_ar else "Play Again")

        # if result already shown, re-render it in the current language
        if self.state is not None:
            winner = check_winner(self.state)
            if winner:
                self.show_result(winner, self.state)



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Imposter")
        icon_path = app_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(500, 700)

        data_path = words_db_path()
        db = load_words_db(data_path)
        self.categories = build_categories(db)
        if not self.categories:
            raise ValueError(f"No categories found in {os.path.basename(data_path)}")

        self.state: Optional[GameState] = None
        self.minutes = 3

        self.lang = Lang.EN
        self._apply_layout_direction()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.category_page = CategorySelectPage(
            self.categories,
            self.go_to_setup_with_category,
            get_lang=lambda: self.lang,
            set_lang=self.set_lang
        )
        self.setup_page = SetupPage(
            self.start_game,
            self.back_to_categories,
            get_lang=lambda: self.lang,
            set_lang=self.set_lang
        )
        self.reveal_page = RevealPage(
            self.on_done_reveal,
            self.reveal_back,
            get_lang=lambda: self.lang,
            set_lang=self.set_lang
        )

        self.play_page = PlayPage(self.on_elimination, self.on_game_over, get_lang=lambda: self.lang)
        self.elim_page = EliminationPage(self.on_next_round, get_lang=lambda: self.lang)

        self.over_page = GameOverPage(
            self.back_to_setup_after_game_over,
            get_lang=lambda: self.lang
        )
        self.stack.addWidget(self.category_page)  # 0
        self.stack.addWidget(self.setup_page)  # 1
        self.stack.addWidget(self.reveal_page)  # 2
        self.stack.addWidget(self.play_page)  # 3
        self.stack.addWidget(self.elim_page)  # 4
        self.stack.addWidget(self.over_page)  # 5

        self.stack.setCurrentIndex(0)

    def set_lang(self, lang: str):
        if lang not in (Lang.AR, Lang.EN):
            return
        self.lang = lang
        self._apply_layout_direction()

        # refresh ONLY the page currently shown
        w = self.stack.currentWidget()
        if hasattr(w, "refresh_language"):
            w.refresh_language()

    def _apply_layout_direction(self):
        direction = (
            Qt.LayoutDirection.RightToLeft
            if self.lang == Lang.AR
            else Qt.LayoutDirection.LeftToRight
        )
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(direction)
        self.setLayoutDirection(direction)

    def start_game(self, category: Category, names: List[str], num_imposters: int, include_hint: bool, minutes: int):
        # build state
        self.state = assign_players(names, category, num_imposters)
        self.minutes = minutes

        # go reveal
        self.reveal_page.load_state(self.state, include_hint)
        self.stack.setCurrentIndex(2)

    def on_done_reveal(self):
        if not self.state:
            return
        self.play_page.load_state(self.state, self.minutes)
        self.stack.setCurrentIndex(3)

        # ✅ prevent off-screen refresh crashes
        self.reveal_page.state = None
        self.reveal_page.idx = 0

    def reveal_back(self):
        # if no state, just go back to setup
        if not self.state:
            self.stack.setCurrentIndex(1)
            return

        # if we're at first player, go back to setup
        if self.reveal_page.idx <= 0:
            self.stack.setCurrentIndex(1)
            return

        # otherwise go to previous player
        self.reveal_page.idx -= 1
        self.reveal_page.update_view()

    def on_elimination(self, name: str, was_imposter: bool):
        self.elim_page.set_result(name, was_imposter)
        self.stack.setCurrentIndex(4)  # elim_page

    def on_next_round(self):
        if not self.state:
            self.stack.setCurrentIndex(0)
            return

        winner = check_winner(self.state)
        if winner:
            self.on_game_over(winner, self.state)
            return

        # go back to play page
        self.play_page.round_num += 1
        self.play_page.skip_check.setChecked(False)
        self.play_page.populate_elim_list()
        self.play_page.update_round_label()
        self.play_page.update_confirm_enabled()

        # reset timer so they can start again
        self.play_page.timer.stop()
        self.play_page.remaining = self.play_page.total_seconds
        self.play_page.update_timer_label()
        is_ar = (self.lang == Lang.AR)
        self.play_page.start_timer_btn.setText("ابدأ المؤقت" if is_ar else "Start Timer")
        self.stack.setCurrentIndex(3)  # play_page

    def on_game_over(self, winner: str, state: GameState):
        self.over_page.show_result(winner, state)
        self.stack.setCurrentIndex(5)  # over_page

    def back_to_setup_after_game_over(self):
        self.state = None
        self.category_page.reset_selection()

        # ✅ clear reveal leftovers
        self.reveal_page.state = None
        self.reveal_page.idx = 0

        self.stack.setCurrentIndex(0)

        # ✅ force correct language + toggle rendering
        self.category_page.refresh_language()

    def back_to_categories(self):
        self.state = None

        # ✅ clear reveal leftovers
        self.reveal_page.state = None
        self.reveal_page.idx = 0

        self.stack.setCurrentIndex(0)
        self.category_page.refresh_language()

    def go_to_setup_with_category(self, category: Category):
        self.setup_page.set_category(category)
        self.stack.setCurrentIndex(1)


def main():
    app = QApplication(sys.argv)

    icon_path = app_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
