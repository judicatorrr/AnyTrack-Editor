"""Keyboard-accessible, exclusive two-position controls."""
from PySide6 import QtCore, QtWidgets


class SegmentedControl(QtWidgets.QFrame):
    currentIndexChanged = QtCore.Signal(int)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setObjectName('segmentedControl')
        self.set_theme('dark')
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self._data = []
        for i, (label, data) in enumerate(items):
            button = QtWidgets.QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setFocusPolicy(QtCore.Qt.StrongFocus)
            button.setCursor(QtCore.Qt.PointingHandCursor)
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            button.setIconSize(QtCore.QSize(20, 20))
            button.setMinimumHeight(32)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.group.addButton(button, i)
            layout.addWidget(button)
            self._data.append(data)
        self.group.button(0).setChecked(True)
        self.group.idToggled.connect(lambda i, checked: checked and self.currentIndexChanged.emit(i))

    def currentIndex(self):
        return self.group.checkedId()

    def setCurrentIndex(self, index):
        button = self.group.button(index)
        if button is not None:
            button.setChecked(True)

    def currentData(self):
        return self._data[self.currentIndex()]

    def setItemText(self, index, text):
        self.group.button(index).setText(text)
        self.group.button(index).setAccessibleName(text)

    def setItemIcon(self, index, icon):
        self.group.button(index).setIcon(icon)

    def set_theme(self, theme):
        if theme == 'light':
            self.setStyleSheet(
                'QFrame#segmentedControl { background:#e8edf3; border:1px solid #b7c0cc; border-radius:8px; }'
                'QToolButton { background:transparent; border:0; border-radius:6px; padding:6px 9px; color:#526071; }'
                'QToolButton:checked { background:#2f6fa8; color:#ffffff; }'
                'QToolButton:hover { color:#17202b; }'
                'QToolButton:checked:hover { color:#ffffff; }'
                'QToolButton:focus { border:1px solid #2f6fa8; padding:5px 8px; }'
            )
        else:
            self.setStyleSheet(
                'QFrame#segmentedControl { background:#191d24; border:1px solid #39414d; border-radius:8px; }'
                'QToolButton { background:transparent; border:0; border-radius:6px; padding:6px 9px; color:#9ca7b7; }'
                'QToolButton:checked { background:#385778; color:#ffffff; }'
                'QToolButton:hover { color:#ffffff; }'
                'QToolButton:focus { border:1px solid #80b6ec; padding:5px 8px; }'
            )
