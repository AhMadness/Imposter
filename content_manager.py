from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QGuiApplication, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QDragMoveEvent
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMenu, QDialog, QDialogButtonBox, QFrame,
)

# -------------------------
# Paths / IO
# -------------------------

def app_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


WORDS_FILENAMES = ("words.json", "words.JSON")


def find_words_json_in_dir(dir_path: Path) -> Optional[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return None

    # Prefer canonical names first.
    for name in WORDS_FILENAMES:
        p = dir_path / name
        if p.exists() and p.is_file():
            return p

    # Case-insensitive fallback for uncommon casing.
    try:
        for p in dir_path.iterdir():
            if p.is_file() and p.name.lower() == "words.json":
                return p
    except OSError:
        return None
    return None


def resolve_words_json_from_selection(sel: Path) -> Optional[Path]:
    """
    Accepts:
      - a folder that has data/words.json (or words.JSON)
      - a folder that has content/data/words.json (or words.JSON)
      - a direct path to words.json (any case variant)
    Returns the path to the words file if found, else None.
    """
    sel = sel.expanduser().resolve()

    if sel.is_file() and sel.name.lower() == "words.json":
        return sel

    if not sel.exists():
        return None

    for data_dir in (sel / "data", sel / "content" / "data"):
        found = find_words_json_in_dir(data_dir)
        if found:
            return found

    return None


def safe_load_words_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"categories": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("words.json root must be an object { categories: [...] }")
    cats = raw.get("categories", [])
    if not isinstance(cats, list):
        raise ValueError("'categories' must be a list.")
    return raw


def safe_save_words_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line

# -------------------------
# Category helpers (slug/name)
# -------------------------

_SMALL_WORDS = {"and", "or", "the", "of", "in", "on", "at", "to", "for", "a", "an"}

def label_to_slug(label: str) -> str:
    s = (label or "").strip().lower().replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    return s.replace(" ", "_")

def slug_to_label(slug: str) -> str:
    parts = [p for p in re.split(r"[_\s]+", (slug or "").strip().lower()) if p]
    if not parts:
        return ""
    out = []
    for i, w in enumerate(parts):
        if i != 0 and w in _SMALL_WORDS:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)

def is_english_name(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9 _\-]+", s))


def data_categories_image_dir(content_dir: Path) -> Path:
    # per your request: data/images/categories
    return content_dir / "data" / "images" / "categories"

def find_category_image(content_dir: Path, slug: str) -> Path | None:
    d = data_categories_image_dir(content_dir)
    if not d.exists():
        return None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = d / f"{slug}{ext}"
        if p.exists() and p.is_file():
            return p
    for p in d.glob(f"{slug}.*"):
        if p.is_file() and re.search(r"\.(png|jpg|jpeg|webp)$", p.name, re.I):
            return p
    return None

def copy_image_overwrite(src: Path, dest_dir: Path, dest_stem: str) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() if src.suffix else ".png"
    dest = dest_dir / f"{dest_stem}{ext}"
    shutil.copy2(src, dest)
    return dest.name

# -------------------------
# Model helpers
# -------------------------

@dataclass
class CatRef:
    idx: int
    id: str
    name: str
    name_ar: str
    img: str  # stored filename or ""


def norm_str(v: Any) -> str:
    return str(v or "").strip()


def normalize_word_item(obj: Any) -> dict[str, str]:
    if not isinstance(obj, dict):
        obj = {}
    return {
        "word": norm_str(obj.get("word")),
        "hint": norm_str(obj.get("hint")),
        "word_ar": norm_str(obj.get("word_ar")),
        "hint_ar": norm_str(obj.get("hint_ar")),
    }


def category_display(c: CatRef) -> str:
    left = c.id or "?"
    en = c.name or c.id
    ar = c.name_ar or ""
    if ar:
        return f"{left} | {en} / {ar}"
    return f"{left} | {en}"


def build_cat_refs(words_db: dict[str, Any]) -> list[CatRef]:
    cats: list[CatRef] = []
    raw = words_db.get("categories", [])
    if not isinstance(raw, list):
        return cats

    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            continue
        cid = norm_str(c.get("id"))
        name = norm_str(c.get("name")) or cid
        name_ar = norm_str(c.get("name_ar")) or ""
        img = norm_str(c.get("img")) or ""
        cats.append(CatRef(idx=i, id=cid, name=name, name_ar=name_ar, img=img))
    return cats


# -------------------------
# Clickable image-path field
# -------------------------

class ClickableLineEdit(QLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setClearButtonEnabled(True)
        self.setReadOnly(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        self.setAcceptDrops(True)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Copy) or e.matches(QKeySequence.StandardKey.SelectAll):
            return super().keyPressEvent(e)
        e.accept()

    def mousePressEvent(self, e):
        if self._clicked_clear_button(e.pos()):
            return super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            # emit-like behavior via a virtual hook: we just call a callback if set
            if hasattr(self, "_on_clicked") and callable(getattr(self, "_on_clicked")):
                getattr(self, "_on_clicked")()
        return super().mousePressEvent(e)

    def _clicked_clear_button(self, pos) -> bool:
        if not self.isClearButtonEnabled():
            return False
        if not self.text():
            return False
        zone = max(18, self.height() - 6)
        return pos.x() >= (self.width() - zone)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if self._event_has_valid_image_file(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e: QDragMoveEvent):
        if self._event_has_valid_image_file(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        p = self._first_local_file_path(e)
        if not p:
            e.ignore()
            return
        if not re.search(r"\.(png|jpg|jpeg|webp)$", p, re.IGNORECASE):
            e.ignore()
            return
        self.setText(p)
        e.acceptProposedAction()

    def _event_has_valid_image_file(self, e) -> bool:
        p = self._first_local_file_path(e)
        if not p:
            return False
        return bool(re.search(r"\.(png|jpg|jpeg|webp)$", p, re.IGNORECASE))

    @staticmethod
    def _first_local_file_path(e) -> str | None:
        md = e.mimeData()
        if not md.hasUrls():
            return None
        for url in md.urls():
            if url.isLocalFile():
                return url.toLocalFile()
        return None


# -------------------------
# Add/Edit Category dialogs
# -------------------------

class AddCategoryDialog(QDialog):
    def __init__(self, *, parent: QWidget, content_dir: Path, existing_slugs: set[str]):
        super().__init__(parent)
        self.setWindowTitle("Add Category")
        self.resize(520, 260)

        self.content_dir = content_dir
        self.existing_slugs = existing_slugs
        self.created_slug: str | None = None
        self.created_name: str | None = None
        self.created_name_ar: str | None = None
        self.created_img_file: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        FIELD_H = 30
        root.setSpacing(8)

        lbl = QLabel("Category Name (English):")
        root.addWidget(lbl)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Animal Kingdom")
        self.name_edit.setFixedHeight(FIELD_H)
        root.addWidget(self.name_edit)

        lbl = QLabel("Category Name (Arabic) (Optional):")
        root.addWidget(lbl)

        self.name_ar_edit = QLineEdit()
        self.name_ar_edit.setPlaceholderText("مثال: مملكة الحيوان")
        self.name_ar_edit.setFixedHeight(FIELD_H)
        root.addWidget(self.name_ar_edit)

        root.addWidget(hline())

        # ---- Image label + row
        root.addWidget(QLabel("Category Image (Optional):"))

        self.img_path = ClickableLineEdit()
        self.img_path.setPlaceholderText("Pick or drop an image…")
        self.img_path.setFixedHeight(FIELD_H)
        self.img_path._on_clicked = self.on_pick_image  # type: ignore
        self.img_path.textChanged.connect(self.update_preview_btn)

        self.btn_pick = QPushButton("Pick")
        self.btn_pick.setFixedHeight(FIELD_H)
        self.btn_pick.clicked.connect(self.on_pick_image)

        self.btn_prev = QPushButton("Preview")
        self.btn_prev.setFixedHeight(FIELD_H)
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(lambda: self.preview_image(self.img_path.text()))

        row_img = QHBoxLayout()
        row_img.setSpacing(6)
        row_img.addWidget(self.img_path, 1)
        row_img.addWidget(self.btn_pick)
        row_img.addWidget(self.btn_prev)
        root.addLayout(row_img)

        root.addWidget(hline())

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.on_save)
        btns.rejected.connect(self.reject)

        r = QHBoxLayout()
        r.addStretch(1)
        r.addWidget(btns)
        r.addStretch(1)
        root.addLayout(r)
        self.update_preview_btn()


    def update_preview_btn(self):
        p = Path((self.img_path.text() or "").strip())
        self.btn_prev.setEnabled(p.exists() and p.is_file())

    def on_pick_image(self):
        file, _ = QFileDialog.getOpenFileName(self, "Pick Image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if file:
            self.img_path.setText(file)

    def preview_image(self, path: str):
        p = Path((path or "").strip())
        if p.exists() and p.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            return
        QMessageBox.warning(self, "Nope", f"File not found:\n{(path or '').strip()}")

    def on_save(self):
        name = (self.name_edit.text() or "").strip()
        if not is_english_name(name):
            QMessageBox.warning(self, "Nope", "Category name must be English letters/numbers/spaces only.")
            return

        slug = label_to_slug(name)
        if not slug:
            QMessageBox.warning(self, "Nope", "Invalid category name.")
            return
        if slug in self.existing_slugs:
            QMessageBox.warning(self, "Nope", f"Category already exists:\n{slug}")
            return

        name_ar = (self.name_ar_edit.text() or "").strip()

        # optional image
        img_file = ""
        img_val = (self.img_path.text() or "").strip()
        if img_val:
            src = Path(img_val)
            if not (src.exists() and src.is_file()):
                QMessageBox.warning(self, "Nope", f"Cannot find image:\n{img_val}")
                return

            # always name image based on category slug
            img_file = copy_image_overwrite(src, data_categories_image_dir(self.content_dir), slug)

        self.created_slug = slug
        self.created_name = name
        self.created_name_ar = name_ar
        self.created_img_file = img_file
        self.accept()


class EditCategoryDialog(QDialog):
    def __init__(self, *, parent: QWidget, content_dir: Path, cat: CatRef, existing_slugs: set[str]):
        super().__init__(parent)
        self.setWindowTitle("Edit Category")
        self.resize(520, 290)

        self.content_dir = content_dir
        self.old_slug = (cat.id or "").strip().lower()
        self.existing_slugs = existing_slugs

        self.updated_slug: str | None = None
        self.updated_name: str | None = None
        self.updated_name_ar: str | None = None
        self.updated_img_file: str | None = None
        self.deleted_slug: str | None = None

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # top row label + delete button
        top_row = QHBoxLayout()
        top_row.addStretch(1)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setFixedHeight(24)
        self.btn_delete.setFixedWidth(80)
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background: #7a1f1f;
                color: white;
                font-weight: 600;
                border-radius: 6px;
                padding: 0 10px;
            }
            QPushButton:hover { background: #922828; }
        """)
        self.btn_delete.clicked.connect(self.on_delete_category)
        top_row.addWidget(self.btn_delete)

        root.addLayout(top_row)

        FIELD_H = 30
        root.setSpacing(8)

        self.name_edit = QLineEdit(cat.name or slug_to_label(self.old_slug))
        self.name_edit.setFixedHeight(FIELD_H)

        self.name_ar_edit = QLineEdit(cat.name_ar or "")
        self.name_ar_edit.setFixedHeight(FIELD_H)

        root.addWidget(QLabel("Category Name (English):"))
        root.addWidget(self.name_edit)

        root.addWidget(QLabel("Category Name (Arabic) (Optional):"))
        root.addWidget(self.name_ar_edit)

        root.addWidget(hline())

        # ---- Image label + row
        root.addWidget(QLabel("Category Image (Optional):"))

        self.img_path = ClickableLineEdit()
        self.img_path.setPlaceholderText("Pick or drop an image…")
        self.img_path.setFixedHeight(FIELD_H)

        existing = find_category_image(self.content_dir, self.old_slug)
        if existing:
            self.img_path.setText(str(existing))

        self._img_user_picked = False
        self._orig_img_path = str(existing) if existing else ""

        self.img_path._on_clicked = self.on_pick_image  # type: ignore
        self.img_path.textChanged.connect(self._mark_img_user_changed)  # includes preview update

        self.btn_pick = QPushButton("Pick")
        self.btn_pick.setFixedHeight(FIELD_H)
        self.btn_pick.clicked.connect(self.on_pick_image)

        self.btn_prev = QPushButton("Preview")
        self.btn_prev.setFixedHeight(FIELD_H)
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(lambda: self.preview_image(self.img_path.text()))

        row_img = QHBoxLayout()
        row_img.setSpacing(6)
        row_img.addWidget(self.img_path, 1)
        row_img.addWidget(self.btn_pick)
        row_img.addWidget(self.btn_prev)
        root.addLayout(row_img)

        root.addWidget(hline())

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.on_save)
        btns.rejected.connect(self.reject)

        r = QHBoxLayout()
        r.addStretch(1)
        r.addWidget(btns)
        r.addStretch(1)
        root.addLayout(r)

        self.update_preview_btn()

    def update_preview_btn(self):
        p = Path((self.img_path.text() or "").strip())
        self.btn_prev.setEnabled(p.exists() and p.is_file())

    def on_pick_image(self):
        file, _ = QFileDialog.getOpenFileName(self, "Pick Image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if file:
            self._img_user_picked = True
            self.img_path.setText(file)

    def preview_image(self, path: str):
        p = Path((path or "").strip())
        if p.exists() and p.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            return
        QMessageBox.warning(self, "Nope", f"File not found:\n{(path or '').strip()}")

    def on_save(self):
        name = (self.name_edit.text() or "").strip()
        if not is_english_name(name):
            QMessageBox.warning(self, "Nope", "Category name must be English letters/numbers/spaces only.")
            return

        new_slug = label_to_slug(name)
        if not new_slug:
            QMessageBox.warning(self, "Nope", "Invalid category name.")
            return

        if new_slug != self.old_slug and new_slug in self.existing_slugs:
            QMessageBox.warning(self, "Nope", f"That name already exists:\n{new_slug}")
            return

        name_ar = (self.name_ar_edit.text() or "").strip()

        # handle category image
        img_dir = data_categories_image_dir(self.content_dir)

        # cleared -> delete original + any slug-named images
        img_val = (self.img_path.text() or "").strip()
        if img_val == "":
            # delete exact original (covers custom stems too)
            try:
                if self._orig_img_path:
                    p = Path(self._orig_img_path)
                    if p.exists() and p.is_file():
                        p.unlink()
            except:
                pass

            # also delete any slug.* for the OLD slug (and NEW slug if changed)
            try:
                for s in {self.old_slug, new_slug}:
                    for p in img_dir.glob(f"{s}.*"):
                        if p.is_file() and re.search(r"\.(png|jpg|jpeg|webp)$", p.name, re.I):
                            try:
                                p.unlink()
                            except:
                                pass
            except:
                pass

            img_file = ""

        # picked/dropped -> overwrite
        else:
            img_file = ""
            if self._img_user_picked:
                src = Path(img_val)
                if not (src.exists() and src.is_file()):
                    QMessageBox.warning(self, "Nope", f"Cannot find image:\n{img_val}")
                    return

                # also delete any old slug images (covers rename cases)
                try:
                    for p in img_dir.glob(f"{self.old_slug}.*"):
                        if p.is_file() and re.search(r"\.(png|jpg|jpeg|webp)$", p.name, re.I):
                            try:
                                p.unlink()
                            except:
                                pass
                except:
                    pass

                # delete any existing <new_slug>.* first (handles ext changes)
                try:
                    for p in img_dir.glob(f"{new_slug}.*"):
                        if p.is_file() and re.search(r"\.(png|jpg|jpeg|webp)$", p.name, re.I):
                            try:
                                p.unlink()
                            except:
                                pass
                except:
                    pass

                img_file = copy_image_overwrite(src, img_dir, new_slug)


            else:
                img_file = None

        self.updated_slug = new_slug
        self.updated_name = name
        self.updated_name_ar = name_ar
        self.updated_img_file = img_file
        self.accept()

    def on_delete_category(self):
        ok = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete category '{self.old_slug}'?\n\nThis will remove it from words.json and delete its image.",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return

        self.deleted_slug = self.old_slug
        self.accept()

    def _mark_img_user_changed(self):
        # if user changed it from the original preloaded value, treat as picked
        cur = (self.img_path.text() or "").strip()
        if cur != (self._orig_img_path or ""):
            self._img_user_picked = True
        self.update_preview_btn()


# -------------------------
# Add/Edit Word dialog
# -------------------------

class WordDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        cats: list[CatRef],
        default_cat_idx: int,
        title: str,
        initial: Optional[dict[str, str]] = None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 260)

        self.cats = cats
        self.result_cat_idx: Optional[int] = None
        self.result_item: Optional[dict[str, str]] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        row_cat = QHBoxLayout()
        row_cat.addWidget(QLabel("Category:"))
        self.cb_cat = QComboBox()
        self.cb_cat.addItems([category_display(c) for c in cats])
        self.cb_cat.setCurrentIndex(max(0, min(default_cat_idx, len(cats) - 1)))
        self.cb_cat.setFixedHeight(30)
        row_cat.addWidget(self.cb_cat, 1)
        root.addLayout(row_cat)

        root.addWidget(hline())

        self.le_word = QLineEdit()
        self.le_hint = QLineEdit()
        self.le_word_ar = QLineEdit()
        self.le_hint_ar = QLineEdit()

        self.le_word.setPlaceholderText("Word (EN)")
        self.le_hint.setPlaceholderText("Hint (EN)")
        self.le_word_ar.setPlaceholderText("Word (AR) (optional)")
        self.le_hint_ar.setPlaceholderText("Hint (AR) (optional)")

        for w in (self.le_word, self.le_hint, self.le_word_ar, self.le_hint_ar):
            w.setFixedHeight(30)

        if initial:
            self.le_word.setText(initial.get("word", ""))
            self.le_hint.setText(initial.get("hint", ""))
            self.le_word_ar.setText(initial.get("word_ar", ""))
            self.le_hint_ar.setText(initial.get("hint_ar", ""))

        root.addWidget(self.le_word)
        root.addWidget(self.le_hint)
        root.addWidget(self.le_word_ar)
        root.addWidget(self.le_hint_ar)

        root.addWidget(hline())

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.on_save)
        btns.rejected.connect(self.reject)

        row_btn = QHBoxLayout()
        row_btn.addStretch(1)
        row_btn.addWidget(btns)
        row_btn.addStretch(1)
        root.addLayout(row_btn)

        QTimer.singleShot(0, self.le_word.setFocus)

    def on_save(self):
        word = self.le_word.text().strip()
        hint = self.le_hint.text().strip()
        word_ar = self.le_word_ar.text().strip()
        hint_ar = self.le_hint_ar.text().strip()

        if not word and not word_ar:
            QMessageBox.warning(self, "Nope", "Enter at least a Word in EN or AR.")
            return

        # Keep both language fields usable for game clients even if one side is omitted.
        if not word:
            word = word_ar
        if not word_ar:
            word_ar = word
        if not hint:
            hint = hint_ar
        if not hint_ar:
            hint_ar = hint

        self.result_cat_idx = int(self.cb_cat.currentIndex())
        self.result_item = {
            "word": word,
            "hint": hint,
            "word_ar": word_ar,
            "hint_ar": hint_ar,
        }
        self.accept()


# -------------------------
# Main UI
# -------------------------

class ImposterManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Imposter Manager")
        self.resize(980, 720)

        self.content_dir: Optional[Path] = None
        self.words_path: Optional[Path] = None

        self.db: dict[str, Any] = {"categories": []}
        self.cats: list[CatRef] = []
        self.current_cat_idx: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---- Content folder row
        row_root = QHBoxLayout()
        self.root_lbl = QLabel("Content: (Not Selected)")
        self.btn_pick = QPushButton("Choose Content")
        self.btn_pick.clicked.connect(self.pick_root)

        self.btn_open = QPushButton("Open Folder")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_root_folder)

        row_root.addWidget(self.root_lbl, 1)
        row_root.addWidget(self.btn_pick)
        row_root.addWidget(self.btn_open)
        root.addLayout(row_root)

        root.addWidget(hline())

        # ---- Category + (settings/add cat) + Search + Add word
        row_top = QHBoxLayout()

        row_top.addWidget(QLabel("Category:"))
        self.cb_cat = QComboBox()
        self.cb_cat.setFixedWidth(250)
        self.cb_cat.currentIndexChanged.connect(self.on_category_changed)
        row_top.addWidget(self.cb_cat)

        self.btn_cat_settings = QPushButton("⚙")
        self.btn_cat_settings.setFixedWidth(34)
        self.btn_cat_settings.setFixedHeight(28)
        self.btn_cat_settings.setStyleSheet("font-size: 12px; padding-bottom: 0px;")
        self.btn_cat_settings.clicked.connect(self.open_edit_category_dialog)
        row_top.addWidget(self.btn_cat_settings)

        self.btn_add_category = QPushButton("+")
        self.btn_add_category.setFixedWidth(34)
        self.btn_add_category.setFixedHeight(28)
        self.btn_add_category.setStyleSheet("font-size: 18px; padding-bottom: 4px;")
        self.btn_add_category.clicked.connect(self.open_add_category_dialog)
        row_top.addWidget(self.btn_add_category)

        row_top.addStretch(1)

        row_top.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter rows...")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.setFixedHeight(28)
        self.search.textChanged.connect(self.apply_filter)
        row_top.addWidget(self.search)

        self.btn_add = QPushButton("+")
        self.btn_add.setFixedWidth(34)
        self.btn_add.setFixedHeight(28)
        self.btn_add.setStyleSheet("font-size: 18px; padding-bottom: 4px;")
        self.btn_add.clicked.connect(self.open_add_dialog)
        row_top.addWidget(self.btn_add)

        root.addLayout(row_top)

        # ---- Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Word (EN)", "Hint (EN)", "Word (AR)", "Hint (AR)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.table.cellDoubleClicked.connect(self.on_table_double_click)

        root.addWidget(self.table, 1)

        self.set_enabled(False)

        QTimer.singleShot(0, self._startup_autoload)

    # --------- enable/disable
    def set_enabled(self, enabled: bool):
        for w in (self.cb_cat, self.btn_cat_settings, self.btn_add_category, self.search, self.btn_open, self.btn_add, self.table):
            w.setEnabled(enabled)

    # --------- startup autoload
    def _startup_autoload(self):
        base = app_base_dir()
        for sel in (base, base / "content"):
            wp = resolve_words_json_from_selection(sel)
            if wp:
                self.load_content(wp.parent.parent)
                return

    # --------- root picking
    def pick_root(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder (game root or content folder that contains data/words.json or words.JSON)"
        )
        if not folder:
            return

        sel = Path(folder)
        words_path = resolve_words_json_from_selection(sel)

        if not words_path:
            QMessageBox.warning(
                self,
                "Nope",
                "Couldn’t find words.json / words.JSON.\n\nExpected one of:\n"
                "- <selected>/data/words.json (or words.JSON)\n"
                "- <selected>/content/data/words.json (or words.JSON)\n"
            )
            return

        self.load_content(words_path.parent.parent)

    def open_root_folder(self):
        if not self.content_dir:
            return
        import subprocess, platform
        path_str = str(self.content_dir)
        if platform.system() == "Windows":
            os.startfile(path_str)  # type: ignore
        elif platform.system() == "Darwin":
            subprocess.run(["open", path_str])
        else:
            subprocess.run(["xdg-open", path_str])

    # --------- load/save
    def load_content(self, content_dir: Path):
        self.content_dir = content_dir
        data_dir = content_dir / "data"
        self.words_path = find_words_json_in_dir(data_dir) or (data_dir / "words.json")

        try:
            self.db = safe_load_words_json(self.words_path)
        except Exception as e:
            QMessageBox.warning(self, "Bad words.json", f"Failed loading:\n{self.words_path}\n\n{e}")
            self.db = {"categories": []}

        self.cats = build_cat_refs(self.db)
        if not self.cats:
            QMessageBox.warning(self, "Nope", "No categories found in words.json.")
            self.cb_cat.clear()
            self.table.setRowCount(0)
            self.set_enabled(False)
            self.root_lbl.setText(f"Content Folder: {content_dir} (no categories)")
            self.btn_open.setEnabled(True)
            return

        self.root_lbl.setText(f"Content Folder: {content_dir}")
        self.btn_open.setEnabled(True)
        self.set_enabled(True)

        self.refresh_categories_dropdown(keep_slug=self.cats[0].id)

    def save_db(self):
        if not self.words_path:
            return
        safe_save_words_json(self.words_path, self.db)

    def refresh_categories_dropdown(self, *, keep_slug: str | None = None):
        keep_slug = (keep_slug or "").strip().lower()

        self.cats = build_cat_refs(self.db)

        self.cb_cat.blockSignals(True)
        self.cb_cat.clear()
        self.cb_cat.addItems([category_display(c) for c in self.cats])
        self.cb_cat.blockSignals(False)

        # restore selection if possible
        if keep_slug:
            for i, c in enumerate(self.cats):
                if (c.id or "").strip().lower() == keep_slug:
                    self.cb_cat.setCurrentIndex(i)
                    self.current_cat_idx = i
                    self.refresh_table()
                    self.apply_filter(self.search.text())
                    return

        if self.cats:
            self.cb_cat.setCurrentIndex(0)
            self.current_cat_idx = 0
            self.refresh_table()
            self.apply_filter(self.search.text())

    # --------- category selection
    def on_category_changed(self, idx: int):
        if idx < 0:
            return
        self.current_cat_idx = idx
        self.refresh_table()
        self.apply_filter(self.search.text())

    # --------- category actions
    def existing_category_slugs(self) -> set[str]:
        out = set()
        raw = self.db.get("categories", [])
        if isinstance(raw, list):
            for c in raw:
                if isinstance(c, dict):
                    out.add(norm_str(c.get("id")).lower())
        return out

    def open_add_category_dialog(self):
        if not self.content_dir:
            QMessageBox.warning(self, "Nope", "Choose the content folder first.")
            return

        dlg = AddCategoryDialog(parent=self, content_dir=self.content_dir, existing_slugs=self.existing_category_slugs())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        slug = dlg.created_slug or ""
        name = dlg.created_name or slug_to_label(slug)
        name_ar = dlg.created_name_ar or ""
        img_file = dlg.created_img_file or ""

        raw = self.db.get("categories", [])
        if not isinstance(raw, list):
            raw = []
            self.db["categories"] = raw

        raw.append({
            "id": slug,
            "name": name,
            "name_ar": name_ar,
            "img": img_file,
            "words": [],
        })
        self.save_db()
        self.refresh_categories_dropdown(keep_slug=slug)

    def open_edit_category_dialog(self):
        if not self.content_dir or not self.cats:
            return

        cur = self.cats[self.current_cat_idx]
        dlg = EditCategoryDialog(parent=self, content_dir=self.content_dir, cat=cur, existing_slugs=self.existing_category_slugs())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        raw = self.db.get("categories", [])
        if not isinstance(raw, list):
            return

        # delete
        if dlg.deleted_slug:
            slug = dlg.deleted_slug.strip().lower()

            # Keep at least one category so the game remains launchable.
            valid_count = sum(1 for c in raw if isinstance(c, dict))
            if valid_count <= 1:
                QMessageBox.warning(
                    self,
                    "Nope",
                    "At least one category must remain. Add another category before deleting this one.",
                )
                return

            # remove from JSON
            new_list = []
            removed_obj = None
            for c in raw:
                if isinstance(c, dict) and norm_str(c.get("id")).lower() == slug:
                    removed_obj = c
                    continue
                new_list.append(c)
            self.db["categories"] = new_list
            self.save_db()

            # delete image(s)
            try:
                img_dir = data_categories_image_dir(self.content_dir)
                # if words.json had img filename, delete it too
                if removed_obj and isinstance(removed_obj, dict):
                    img_ref = norm_str(removed_obj.get("img"))
                    if img_ref:
                        p = img_dir / img_ref
                        if p.exists() and p.is_file():
                            try:
                                p.unlink()
                            except:
                                pass
                # also delete slug.*
                if img_dir.exists():
                    for p in img_dir.glob(f"{slug}.*"):
                        if p.is_file() and re.search(r"\.(png|jpg|jpeg|webp)$", p.name, re.I):
                            try:
                                p.unlink()
                            except:
                                pass
            except:
                pass

            # refresh selection to first available
            self.refresh_categories_dropdown(keep_slug=None)
            return

        # edit/save
        old_slug = cur.id.strip().lower()
        new_slug = (dlg.updated_slug or old_slug).strip().lower()
        new_name = (dlg.updated_name or cur.name or slug_to_label(new_slug)).strip()
        new_name_ar = (dlg.updated_name_ar or "").strip()

        # locate object
        target = None
        for c in raw:
            if isinstance(c, dict) and norm_str(c.get("id")).lower() == old_slug:
                target = c
                break
        if not target:
            return

        # update slug/name fields
        target["id"] = new_slug
        target["name"] = new_name
        target["name_ar"] = new_name_ar

        # update image field if dialog says so
        if dlg.updated_img_file is None:
            # None => user didn't change image, keep as-is
            pass
        else:
            # "" => cleared, or filename => overwritten
            target["img"] = dlg.updated_img_file

        self.save_db()

        # if slug changed: rename image by img ref OR old slug fallback, then update json
        if new_slug != old_slug:
            try:
                img_dir = data_categories_image_dir(self.content_dir)
                old_img: Path | None = None
                img_ref = Path(norm_str(target.get("img"))).name

                if img_ref:
                    candidate = img_dir / img_ref
                    if candidate.exists() and candidate.is_file() and re.search(r"\.(png|jpg|jpeg|webp)$", candidate.name, re.I):
                        old_img = candidate

                if old_img is None:
                    fallback = find_category_image(self.content_dir, old_slug)
                    if fallback and fallback.exists() and fallback.is_file():
                        old_img = fallback

                if old_img is not None:
                    new_img_name = f"{new_slug}{old_img.suffix.lower()}"
                    new_img = img_dir / new_img_name

                    # if destination exists, replace it
                    try:
                        if new_img.exists() and new_img.is_file():
                            new_img.unlink()
                    except:
                        pass

                    try:
                        old_img.rename(new_img)
                        target["img"] = new_img_name
                        self.save_db()
                    except:
                        pass
            except:
                pass


        self.refresh_categories_dropdown(keep_slug=new_slug)

    # --------- table content
    def current_words_list(self) -> list[dict[str, Any]]:
        if not self.cats:
            return []
        raw_cats = self.db.get("categories", [])
        if not isinstance(raw_cats, list):
            return []
        ci = self.current_cat_idx
        if ci < 0 or ci >= len(self.cats):
            return []
        cat = raw_cats[self.cats[ci].idx]
        if not isinstance(cat, dict):
            return []
        words = cat.get("words", [])
        if not isinstance(words, list):
            words = []
            cat["words"] = words
        return words

    def refresh_table(self):
        words = self.current_words_list()
        normed = [normalize_word_item(x) for x in words]

        self.table.setRowCount(0)
        self.table.setRowCount(len(normed))

        for r, it in enumerate(normed):
            vals = [it["word"], it["hint"], it["word_ar"], it["hint_ar"]]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c in (2, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, cell)

        self.table.resizeRowsToContents()

    # --------- filtering
    def apply_filter(self, text: str):
        text = (text or "").strip().lower()
        if not text:
            for r in range(self.table.rowCount()):
                self.table.setRowHidden(r, False)
            return

        for r in range(self.table.rowCount()):
            match = False
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it and text in it.text().lower():
                    match = True
                    break
            self.table.setRowHidden(r, not match)

    # --------- add/edit/delete words
    def open_add_dialog(self):
        if not self.cats:
            return
        dlg = WordDialog(
            parent=self,
            cats=self.cats,
            default_cat_idx=self.current_cat_idx,
            title="Add Word"
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if dlg.result_cat_idx is None or dlg.result_item is None:
            return

        raw_cats = self.db.get("categories", [])
        cat_ref = self.cats[dlg.result_cat_idx]
        cat_obj = raw_cats[cat_ref.idx]
        if not isinstance(cat_obj, dict):
            return
        words = cat_obj.get("words", [])
        if not isinstance(words, list):
            words = []
            cat_obj["words"] = words

        words.append(dlg.result_item)
        self.save_db()

        if dlg.result_cat_idx != self.current_cat_idx:
            self.cb_cat.setCurrentIndex(dlg.result_cat_idx)
        else:
            self.refresh_table()
            self.apply_filter(self.search.text())

    def on_table_double_click(self, row: int, col: int):
        self.edit_row(row)

    def on_table_context_menu(self, pos: QPoint):
        row = self.table.indexAt(pos).row()
        if row < 0:
            return

        menu = QMenu(self)
        act_edit = menu.addAction("Edit")
        act_del = menu.addAction("Delete")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self.edit_row(row)
        elif chosen == act_del:
            self.delete_row(row)

    def edit_row(self, table_row: int):
        words = self.current_words_list()
        if table_row < 0 or table_row >= len(words):
            return

        initial = normalize_word_item(words[table_row])

        dlg = WordDialog(
            parent=self,
            cats=self.cats,
            default_cat_idx=self.current_cat_idx,
            title="Edit Word",
            initial=initial
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.result_item is None or dlg.result_cat_idx is None:
            return

        dest_idx = int(dlg.result_cat_idx)
        if dest_idx == self.current_cat_idx:
            words[table_row] = dlg.result_item
            self.save_db()
            self.refresh_table()
            self.apply_filter(self.search.text())
            return

        # Move entry across categories when user changes category in edit dialog.
        raw_cats = self.db.get("categories", [])
        if not isinstance(raw_cats, list):
            return
        if dest_idx < 0 or dest_idx >= len(self.cats):
            return

        dest_ref = self.cats[dest_idx]
        dest_cat_obj = raw_cats[dest_ref.idx]
        if not isinstance(dest_cat_obj, dict):
            return

        moved_item = dlg.result_item
        words.pop(table_row)

        dest_words = dest_cat_obj.get("words", [])
        if not isinstance(dest_words, list):
            dest_words = []
            dest_cat_obj["words"] = dest_words
        dest_words.append(moved_item)

        self.save_db()
        self.cb_cat.setCurrentIndex(dest_idx)

    def delete_row(self, table_row: int):
        words = self.current_words_list()
        if table_row < 0 or table_row >= len(words):
            return

        it = normalize_word_item(words[table_row])
        preview = it["word"] or it["word_ar"] or "(empty)"

        ok = QMessageBox.question(self, "Confirm Delete", f"Delete this entry?\n\n{preview}")
        if ok != QMessageBox.StandardButton.Yes:
            return

        words.pop(table_row)
        self.save_db()
        self.refresh_table()
        self.apply_filter(self.search.text())

    # --------- center
    def center_on_screen(self):
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2 - 16
        self.move(x, y)


def main():
    import sys
    app = QApplication(sys.argv)
    w = ImposterManager()
    w.show()

    QGuiApplication.processEvents()
    w.center_on_screen()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
