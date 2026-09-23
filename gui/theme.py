"""Visual themes for the GODAS Regional Data Tool GUI.

This module contains presentation-only styles. No scientific algorithms or
processing behavior depend on the selected theme.
"""

DARK_QSS = r"""
QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
    color: #d9e2ec;
    background: #0f1822;
}
QMainWindow {
    background: #0b141e;
}
QLabel {
    background: transparent;
    color: #d9e2ec;
}
QGroupBox {
    background: #142231;
    border: 1px solid #2b4054;
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #8fc8f4;
    background: #0f1822;
}
QTabWidget::pane {
    background: #111d2a;
    border: 1px solid #2b4054;
    border-radius: 10px;
}
QTabBar::tab {
    background: #13202d;
    color: #9fb2c4;
    min-width: 185px;
    min-height: 40px;
    padding: 8px 12px;
    margin: 3px 6px 3px 0;
    border: 1px solid transparent;
    border-radius: 8px;
    text-align: left;
}
QTabBar::tab:hover {
    color: #e8f3fb;
    background: #1b3042;
    border-color: #284457;
}
QTabBar::tab:selected {
    color: #ffffff;
    background: #1e6fa5;
    border-color: #398fbe;
    font-weight: 700;
}
QTabBar::scroller {
    background: transparent;
}
QPushButton {
    background: #1b2b3b;
    color: #dce8f2;
    border: 1px solid #355067;
    border-radius: 7px;
    padding: 7px 14px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton:hover {
    background: #243b50;
    border-color: #4a82ab;
}
QPushButton:pressed {
    background: #122433;
}
QPushButton:disabled {
    color: #60758a;
    background: #16212b;
    border-color: #263746;
}
QPushButton:checked {
    color: #ffffff;
    background: #1e73aa;
    border-color: #48a0d8;
}
QComboBox, QLineEdit, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #0d1721;
    color: #dce8f2;
    border: 1px solid #32495d;
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: #255f86;
    selection-color: #ffffff;
}
QComboBox:hover, QLineEdit:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover {
    border-color: #4386b2;
}
QComboBox:focus, QLineEdit:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {
    border-color: #62b1e5;
}
QComboBox::drop-down, QDateEdit::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background: #11202d;
    color: #dce8f2;
    border: 1px solid #3a5369;
    selection-background-color: #1e5f89;
    selection-color: #ffffff;
}
QRadioButton, QCheckBox {
    background: transparent;
    color: #d9e2ec;
    spacing: 6px;
}
QRadioButton:disabled, QCheckBox:disabled {
    color: #60758a;
}
QProgressBar {
    background: #0d1721;
    border: 1px solid #32495d;
    border-radius: 6px;
    text-align: center;
    color: #dce8f2;
    min-height: 16px;
}
QProgressBar::chunk {
    background: #2786c6;
    border-radius: 5px;
}
QPlainTextEdit {
    background: #0a131c;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    border-radius: 5px;
    min-height: 28px;
}
QFrame#navPanel {
    background: #101e2b;
    border: 1px solid #294052;
    border-radius: 12px;
}
QLabel#navSectionTitle {
    color: #7faecb;
    font-size: 8.5pt;
    font-weight: 700;
    padding: 4px 8px 7px 8px;
    letter-spacing: 1px;
}
QPushButton#navButton {
    text-align: left;
    min-height: 54px;
    padding: 7px 10px;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #d6e2ec;
    font-weight: 600;
}
QPushButton#navButton[tone="blue"] { background: #152a3c; }
QPushButton#navButton[tone="teal"] { background: #15302d; }
QPushButton#navButton[tone="purple"] { background: #261f38; }
QPushButton#navButton[tone="orange"] { background: #35291c; }
QPushButton#navButton[tone="gold"] { background: #37311d; }
QPushButton#navButton[tone="indigo"] { background: #1d2540; }
QPushButton#navButton[tone="blue"]:hover { background: #1b3a52; border-color: #2c6a8e; }
QPushButton#navButton[tone="teal"]:hover { background: #1d433e; border-color: #2d7a6f; }
QPushButton#navButton[tone="purple"]:hover { background: #352951; border-color: #68539d; }
QPushButton#navButton[tone="orange"]:hover { background: #4b3824; border-color: #9a6c37; }
QPushButton#navButton[tone="gold"]:hover { background: #4e4522; border-color: #9a8a45; }
QPushButton#navButton[tone="indigo"]:hover { background: #2b355c; border-color: #4e63a5; }
QPushButton#navButton[tone="blue"]:checked { background: #1c6c9e; border-color: #49a6d9; color: #ffffff; }
QPushButton#navButton[tone="teal"]:checked { background: #1e8071; border-color: #52c5b2; color: #ffffff; }
QPushButton#navButton[tone="purple"]:checked { background: #6748a4; border-color: #ab8be8; color: #ffffff; }
QPushButton#navButton[tone="orange"]:checked { background: #b56d2e; border-color: #e7a463; color: #ffffff; }
QPushButton#navButton[tone="gold"]:checked { background: #a48626; border-color: #ddc25c; color: #ffffff; }
QPushButton#navButton[tone="indigo"]:checked { background: #465fa6; border-color: #8198df; color: #ffffff; }
QPushButton#navButton:hover {
    background: #1a3041;
    color: #ecf7ff;
    border-color: #27465c;
}
QPushButton#navButton:checked {
    background: #155d8f;
    color: #ffffff;
    border-color: #2a8dca;
    font-weight: 700;
}
QLabel#navFooter {
    color: #71879a;
    padding: 7px 8px;
    border-top: 1px solid #253a4c;
}
QLabel#appWordmark {
    font-size: 20pt;
    font-weight: 800;
    color: #4ba9de;
    letter-spacing: 1px;
}
QLabel#appProductName {
    font-size: 12pt;
    font-weight: 700;
    color: #dceef9;
}
QLabel#fieldHint {
    color: #8ea7b9;
    font-size: 9pt;
    font-weight: 400;
    padding: 4px 2px;
}
QStatusBar {
    background: #0c151f;
    color: #9fb2c4;
    border-top: 1px solid #253747;
}
QHeaderView::section {
    background: #1a2b3b;
    color: #dce8f2;
    border: none;
    border-right: 1px solid #2b4054;
    border-bottom: 1px solid #2b4054;
    padding: 6px;
    font-weight: 600;
}
QTableWidget, QListView {
    background: #0e1822;
    color: #dce8f2;
    alternate-background-color: #132230;
    gridline-color: #253a4c;
    border: 1px solid #32495d;
    border-radius: 6px;
    selection-background-color: #1d597e;
}
QLabel#appTitle {
    font-size: 19pt;
    font-weight: 700;
}
QLabel#appSubtitle {
    font-size: 9.5pt;
}
QLabel#sectionCaption {
    padding: 8px 10px;
    border-radius: 8px;
    background: #13283a;
    color: #a8cde7;
}
QLabel#appVersion {
    padding: 4px 9px;
    border-radius: 9px;
    font-weight: 700;
}
QPushButton#primaryButton {
    min-height: 38px;
    border-radius: 9px;
    font-weight: 700;
    color: #ffffff;
    background: #1e73aa;
    border-color: #48a0d8;
}
QPushButton#primaryButton:hover {
    background: #2584bd;
}
QPushButton#secondaryButton {
    min-height: 34px;
    border-radius: 8px;
}
QFrame#logPanel {
    background: #142231;
    border: 1px solid #294052;
    border-radius: 8px;
}
QLabel#logPanelTitle {
    color: #8fc8f4;
    font-weight: 700;
}
QPushButton#logToggleButton {
    min-width: 30px;
    min-height: 24px;
    max-width: 30px;
    max-height: 24px;
    padding: 1px 5px;
    border-radius: 12px;
    background: #152a3c;
    border-color: #2c6a8e;
    color: #a9d8f4;
}
QPushButton#logToggleButton:hover {
    background: #1c3d54;
}
QProgressBar#processIndicator {
    min-height: 18px;
    max-height: 20px;
    background: #0d1721;
    border: 1px solid #32495d;
    border-radius: 8px;
    text-align: center;
    color: #dce8f2;
    font-weight: 600;
}
QProgressBar#processIndicator::chunk {
    background: #2aa876;
    border-radius: 7px;
}
QLabel#processStatus {
    color: #8fa7b9;
    font-size: 9pt;
    padding: 0 4px;
}
QPushButton#variableSelectButton {
    min-height: 28px;
    padding: 4px 10px;
}
QPushButton#themeLightButton, QPushButton#themeDarkButton {
    min-width: 76px;
    min-height: 26px;
    padding: 4px 10px;
    border-radius: 13px;
    font-weight: 600;
}
QPushButton#themeLightButton {
    color: #9eb3c5;
    background: #142231;
    border-color: #30475a;
}
QPushButton#themeDarkButton {
    color: #ffffff;
    background: #1e73aa;
    border-color: #48a0d8;
}
QPushButton#themeLightButton:checked, QPushButton#themeDarkButton:checked {
    color: #ffffff;
    background: #1e73aa;
    border-color: #48a0d8;
}
"""

LIGHT_QSS = r"""
QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
    color: #25384a;
    background: #f4f7fa;
}
QMainWindow {
    background: #edf3f7;
}
QLabel {
    background: transparent;
    color: #25384a;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #c9d7e2;
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #0b5f95;
    background: #f4f7fa;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #c9d7e2;
    border-radius: 10px;
}
QTabBar::tab {
    background: #eef3f7;
    color: #597083;
    min-width: 185px;
    min-height: 40px;
    padding: 8px 12px;
    margin: 3px 6px 3px 0;
    border: 1px solid transparent;
    border-radius: 8px;
    text-align: left;
}
QTabBar::tab:hover {
    color: #164c6d;
    background: #e0eef6;
    border-color: #ccdde7;
}
QTabBar::tab:selected {
    color: #ffffff;
    background: #1d78b4;
    border-color: #1d78b4;
    font-weight: 700;
}
QTabBar::scroller {
    background: transparent;
}
QPushButton {
    background: #ffffff;
    color: #2c4356;
    border: 1px solid #b7c9d7;
    border-radius: 7px;
    padding: 7px 14px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton:hover {
    background: #eef7fc;
    border-color: #6aa6c9;
}
QPushButton:pressed {
    background: #e1eef6;
}
QPushButton:disabled {
    color: #95a6b4;
    background: #edf2f5;
    border-color: #d5e0e7;
}
QPushButton:checked {
    color: #ffffff;
    background: #1d78b4;
    border-color: #1d78b4;
}
QComboBox, QLineEdit, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #ffffff;
    color: #25384a;
    border: 1px solid #b7c9d7;
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: #b7ddf4;
    selection-color: #163c57;
}
QComboBox:hover, QLineEdit:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover {
    border-color: #72abc9;
}
QComboBox:focus, QLineEdit:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {
    border-color: #2d8bc5;
}
QComboBox::drop-down, QDateEdit::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #25384a;
    border: 1px solid #b7c9d7;
    selection-background-color: #d8edf9;
    selection-color: #153f5a;
}
QRadioButton, QCheckBox {
    background: transparent;
    color: #304a5f;
    spacing: 6px;
}
QRadioButton:disabled, QCheckBox:disabled {
    color: #9aaab7;
}
QProgressBar {
    background: #eef3f6;
    border: 1px solid #bdcdd8;
    border-radius: 6px;
    text-align: center;
    color: #2c4356;
    min-height: 16px;
}
QProgressBar::chunk {
    background: #2a8ac4;
    border-radius: 5px;
}
QPlainTextEdit {
    background: #fbfdfe;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    border-radius: 5px;
    min-height: 28px;
}
QFrame#navPanel {
    background: #ffffff;
    border: 1px solid #cbd9e3;
    border-radius: 12px;
}
QLabel#navSectionTitle {
    color: #6a879b;
    font-size: 8.5pt;
    font-weight: 700;
    padding: 4px 8px 7px 8px;
    letter-spacing: 1px;
}
QPushButton#navButton {
    text-align: left;
    min-height: 54px;
    padding: 7px 10px;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #466177;
    font-weight: 600;
}
QPushButton#navButton[tone="blue"] { background: #eaf4fb; }
QPushButton#navButton[tone="teal"] { background: #eaf8f2; }
QPushButton#navButton[tone="purple"] { background: #f2ecfb; }
QPushButton#navButton[tone="orange"] { background: #fff2e5; }
QPushButton#navButton[tone="gold"] { background: #fff7de; }
QPushButton#navButton[tone="indigo"] { background: #eceffd; }
QPushButton#navButton[tone="blue"]:hover { background: #dbeef9; border-color: #afd5e8; }
QPushButton#navButton[tone="teal"]:hover { background: #d9f0e8; border-color: #a8d7c9; }
QPushButton#navButton[tone="purple"]:hover { background: #e8ddf6; border-color: #c9b4e7; }
QPushButton#navButton[tone="orange"]:hover { background: #ffe7d1; border-color: #f1c49f; }
QPushButton#navButton[tone="gold"]:hover { background: #fff0bd; border-color: #e7d37f; }
QPushButton#navButton[tone="indigo"]:hover { background: #e0e5fb; border-color: #bac7ef; }
QPushButton#navButton[tone="blue"]:checked { background: #cfe9f8; border-color: #89c7e6; color: #075f92; }
QPushButton#navButton[tone="teal"]:checked { background: #ccecdf; border-color: #84c7b4; color: #126c5f; }
QPushButton#navButton[tone="purple"]:checked { background: #e2d5f4; border-color: #b69bdb; color: #644091; }
QPushButton#navButton[tone="orange"]:checked { background: #ffe1c0; border-color: #eab17b; color: #96551e; }
QPushButton#navButton[tone="gold"]:checked { background: #f9eab0; border-color: #d9bf55; color: #7d6813; }
QPushButton#navButton[tone="indigo"]:checked { background: #d9def6; border-color: #a1afe3; color: #435690; }
QPushButton#navButton:hover {
    background: #edf6fb;
    color: #164e72;
    border-color: #d2e3ed;
}
QPushButton#navButton:checked {
    background: #d8edf9;
    color: #0e6395;
    border-color: #9ecce6;
    font-weight: 700;
}
QLabel#navFooter {
    color: #788f9f;
    padding: 7px 8px;
    border-top: 1px solid #d9e3e9;
}
QLabel#appWordmark {
    font-size: 20pt;
    font-weight: 800;
    color: #176fa9;
    letter-spacing: 1px;
}
QLabel#appProductName {
    font-size: 12pt;
    font-weight: 700;
    color: #264b63;
}
QLabel#fieldHint {
    color: #647f92;
    font-size: 9pt;
    font-weight: 400;
    padding: 4px 2px;
}
QStatusBar {
    background: #edf3f7;
    color: #587082;
    border-top: 1px solid #cbd8e1;
}
QHeaderView::section {
    background: #e8f0f5;
    color: #334c60;
    border: none;
    border-right: 1px solid #c9d7e2;
    border-bottom: 1px solid #c9d7e2;
    padding: 6px;
    font-weight: 600;
}
QTableWidget, QListView {
    background: #ffffff;
    color: #25384a;
    alternate-background-color: #f3f7fa;
    gridline-color: #d5e0e7;
    border: 1px solid #bdcdd8;
    border-radius: 6px;
    selection-background-color: #d9edf8;
}
QLabel#appTitle {
    font-size: 19pt;
    font-weight: 700;
}
QLabel#appSubtitle {
    font-size: 9.5pt;
}
QLabel#sectionCaption {
    padding: 8px 10px;
    border-radius: 8px;
    background: #edf6fb;
    color: #35617b;
}
QLabel#appVersion {
    padding: 4px 9px;
    border-radius: 9px;
    font-weight: 700;
}
QPushButton#primaryButton {
    min-height: 38px;
    border-radius: 9px;
    font-weight: 700;
    color: #ffffff;
    background: #1d78b4;
    border-color: #1d78b4;
}
QPushButton#primaryButton:hover {
    background: #2c8bc3;
}
QPushButton#secondaryButton {
    min-height: 34px;
    border-radius: 8px;
}
QFrame#logPanel {
    background: #ffffff;
    border: 1px solid #cbd9e3;
    border-radius: 8px;
}
QLabel#logPanelTitle {
    color: #0b5f95;
    font-weight: 700;
}
QPushButton#logToggleButton {
    min-width: 30px;
    min-height: 24px;
    max-width: 30px;
    max-height: 24px;
    padding: 1px 5px;
    border-radius: 12px;
    background: #edf6fb;
    border-color: #9ecce6;
    color: #176fa9;
}
QPushButton#logToggleButton:hover {
    background: #dbeef9;
}
QProgressBar#processIndicator {
    min-height: 18px;
    max-height: 20px;
    background: #eef3f6;
    border: 1px solid #bdcdd8;
    border-radius: 8px;
    text-align: center;
    color: #2c4356;
    font-weight: 600;
}
QProgressBar#processIndicator::chunk {
    background: #2a9d6f;
    border-radius: 7px;
}
QLabel#processStatus {
    color: #627d90;
    font-size: 9pt;
    padding: 0 4px;
}
QPushButton#variableSelectButton {
    min-height: 28px;
    padding: 4px 10px;
}
QPushButton#themeLightButton, QPushButton#themeDarkButton {
    min-width: 76px;
    min-height: 26px;
    padding: 4px 10px;
    border-radius: 13px;
    font-weight: 600;
}
QPushButton#themeLightButton {
    color: #ffffff;
    background: #1d78b4;
    border-color: #1d78b4;
}
QPushButton#themeDarkButton {
    color: #64798a;
    background: #ffffff;
    border-color: #bfd0dc;
}
QPushButton#themeLightButton:checked, QPushButton#themeDarkButton:checked {
    color: #ffffff;
    background: #1d78b4;
    border-color: #1d78b4;
}
"""


def apply_theme(app, theme: str) -> str:
    """Apply a supported theme and return the normalized theme key."""
    theme = "light" if str(theme).lower() == "light" else "dark"
    app.setStyle("Fusion")
    app.setStyleSheet(LIGHT_QSS if theme == "light" else DARK_QSS)
    return theme
