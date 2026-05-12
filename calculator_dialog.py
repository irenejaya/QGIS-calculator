# -*- coding: utf-8 -*-
"""Calculator dialog widget. Qt6 / QGIS 4 compatible (uses qgis.PyQt).

A compact windowed calculator styled to resemble a hand-held calculator's
LCD: a soft green screen showing the expression on the top line and the
result on the bottom-right line.

Features:
  - Number / operator buttons
  - Keyboard input
  - Parentheses (with implicit multiplication, auto-balancing on '=')
  - Percent, sign toggle, decimal
  - Memory: MC, MR, M+, M-
  - History panel (collapsible)
  - Safe expression evaluation (AST-based, no `eval` on raw input)
"""

from __future__ import annotations

import ast
import operator
from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QKeySequence, QShortcut
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval(expression: str) -> float:
    """Evaluate an arithmetic expression safely via AST walking.

    Allowed: numeric literals, + - * / // % **, parentheses, unary +/-.
    Raises ValueError for anything else.
    """
    if not expression or not expression.strip():
        raise ValueError("empty expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"syntax error: {exc.msg}") from exc

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"unsupported literal: {node.value!r}")
        if isinstance(node, ast.BinOp):
            op_fn = _BIN_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"unsupported operator: {type(node.op).__name__}")
            return op_fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_fn = _UNARY_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
            return op_fn(_eval(node.operand))
        raise ValueError(f"unsupported expression node: {type(node).__name__}")

    return _eval(tree)


def _format_number(value: float) -> str:
    """Format a numeric result without trailing .0 for integers."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.12g}"


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
class CalculatorDialog(QDialog):
    """Calculator dialog."""

    # Pretty operator characters used in the on-screen display.
    _MUL = "×"
    _DIV = "÷"
    _SUB = "−"  # U+2212 MINUS SIGN (not ASCII hyphen)
    _OPERATORS = {"+", _SUB, _MUL, _DIV, "%"}

    # Map ASCII operator (from keyboard / button key) -> display character.
    _ASCII_TO_PRETTY = {"*": _MUL, "/": _DIV, "-": _SUB}
    # Reverse, used before evaluation.
    _PRETTY_TO_ASCII = {_MUL: "*", _DIV: "/", _SUB: "-"}

    @classmethod
    def _to_eval(cls, text: str) -> str:
        """Translate the display string into a string safe_eval understands."""
        for pretty, ascii_ch in cls._PRETTY_TO_ASCII.items():
            text = text.replace(pretty, ascii_ch)
        return text

    _SCREEN_QSS = """
        QFrame#screen {
            background-color: #cfe1c8;
            border: 1px solid #6c8a63;
            border-radius: 6px;
        }
        QLineEdit#display, QLabel#resultLabel {
            background: transparent;
            border: none;
            color: #1a1a1a;
        }
    """

    _BUTTON_BASE_QSS = """
        QPushButton {
            background-color: #f5f5f5;
            border: 1px solid #c8c8c8;
            border-radius: 6px;
            padding: 6px;
            font-size: 11pt;
        }
        QPushButton:hover  { background-color: #eaeaea; }
        QPushButton:pressed{ background-color: #d8d8d8; }
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calculator")
        self.setMinimumWidth(340)

        self._memory: float = 0.0
        self._just_evaluated: bool = False
        self._history_visible: bool = False
        self._last_result_text: str = ""

        self._build_ui()
        self._wire_shortcuts()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # -- LCD-style screen ------------------------------------------------
        screen = QFrame()
        screen.setObjectName("screen")
        screen.setStyleSheet(self._SCREEN_QSS)
        screen.setMinimumHeight(110)

        screen_layout = QVBoxLayout(screen)
        screen_layout.setContentsMargins(12, 10, 12, 10)
        screen_layout.setSpacing(4)

        # Top line: the expression the user is typing (editable, transparent).
        self.display = QLineEdit("")
        self.display.setObjectName("display")
        self.display.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        font_top = QFont("Consolas")
        font_top.setPointSize(14)
        self.display.setFont(font_top)
        self.display.setPlaceholderText("0")
        self.display.returnPressed.connect(self._on_equals)
        screen_layout.addWidget(self.display)

        screen_layout.addStretch()

        # Bottom line: the latest result (right-aligned, large).
        self.result_label = QLabel("0")
        self.result_label.setObjectName("resultLabel")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        font_bot = QFont("Consolas")
        font_bot.setPointSize(22)
        font_bot.setBold(True)
        self.result_label.setFont(font_bot)
        screen_layout.addWidget(self.result_label)

        root.addWidget(screen)

        # -- Memory indicator + history toggle row ---------------------------
        info_row = QHBoxLayout()
        self.mem_indicator = QLabel("")
        self.mem_indicator.setStyleSheet("color: #c0392b; font-weight: bold;")
        info_row.addWidget(self.mem_indicator)
        info_row.addStretch()
        self.history_toggle = QPushButton("History ▾")
        self.history_toggle.setFlat(True)
        self.history_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_toggle.clicked.connect(self._toggle_history)
        info_row.addWidget(self.history_toggle)
        root.addLayout(info_row)

        # -- Button grid -----------------------------------------------------
        grid_host = QWidget()
        grid_host.setStyleSheet(self._BUTTON_BASE_QSS)
        grid = QGridLayout(grid_host)
        grid.setSpacing(6)

        buttons = [
            ("MC", 0, 0, "mc",      "mem"),
            ("MR", 0, 1, "mr",      "mem"),
            ("M+", 0, 2, "mplus",   "mem"),
            ("M-", 0, 3, "mminus",  "mem"),

            ("C",  1, 0, "clear",       "fn"),
            ("CE", 1, 1, "clear_entry", "fn"),
            ("⌫", 1, 2, "backspace",    "fn"),
            ("±",  1, 3, "sign",        "fn"),

            ("(",  2, 0, "lparen",  "op"),
            (")",  2, 1, "rparen",  "op"),
            ("%",  2, 2, "percent", "op"),
            ("÷",  2, 3, "/",       "op"),

            ("7", 3, 0, "7", "num"),
            ("8", 3, 1, "8", "num"),
            ("9", 3, 2, "9", "num"),
            ("×", 3, 3, "*", "op"),

            ("4", 4, 0, "4", "num"),
            ("5", 4, 1, "5", "num"),
            ("6", 4, 2, "6", "num"),
            ("−", 4, 3, "-", "op"),

            ("1", 5, 0, "1", "num"),
            ("2", 5, 1, "2", "num"),
            ("3", 5, 2, "3", "num"),
            ("+", 5, 3, "+", "op"),
        ]
        for label, r, c, key, kind in buttons:
            grid.addWidget(self._make_button(label, key, kind), r, c)

        grid.addWidget(self._make_button("0", "0", "num"), 6, 0, 1, 2)
        grid.addWidget(self._make_button(".", ".", "num"), 6, 2)
        grid.addWidget(self._make_button("=", "equals", "equals"), 6, 3)

        root.addWidget(grid_host)

        # -- History panel (hidden by default) -------------------------------
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        self.history_list.itemDoubleClicked.connect(self._reuse_history_item)
        self.history_list.setVisible(False)
        root.addWidget(self.history_list)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _make_button(self, label: str, key: str, kind: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setMinimumSize(64, 44)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        style = ""
        if kind == "mem":
            style = "QPushButton { color: #c0392b; font-weight: 600; }"
        elif kind == "fn":
            style = "QPushButton { color: #2c3e50; font-weight: 600; }"
        elif kind == "op":
            style = (
                "QPushButton { color: #d35400; font-weight: 700;"
                " background-color: #fcf3e6; border-color: #e5c391; }"
                "QPushButton:hover  { background-color: #f7e7c8; }"
                "QPushButton:pressed{ background-color: #efd6a4; }"
            )
        elif kind == "num":
            style = "QPushButton { color: #1f3a93; font-weight: 600; font-size: 13pt; }"
        elif kind == "equals":
            style = (
                "QPushButton { background-color: #27ae60; color: white;"
                " font-weight: 700; font-size: 13pt; border: 1px solid #1e8449; }"
                "QPushButton:hover  { background-color: #2ecc71; }"
                "QPushButton:pressed{ background-color: #1e8449; }"
            )
        if style:
            btn.setStyleSheet(style)
        btn.clicked.connect(lambda _checked=False, k=key: self._handle_key(k))
        return btn

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("Esc"), self, activated=lambda: self._handle_key("clear"))

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def _handle_key(self, key: str) -> None:
        if key in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "."}:
            self._append_text(key)
        elif key in {"+", "-", "*", "/"} or key in self._OPERATORS:
            self._append_operator(key)
        elif key == "lparen":
            self._append_paren("(")
        elif key == "rparen":
            self._append_paren(")")
        elif key == "percent":
            self._apply_percent()
        elif key == "sign":
            self._toggle_sign()
        elif key == "backspace":
            self._backspace()
        elif key == "clear_entry":
            self.display.setText("")
            self._just_evaluated = False
        elif key == "clear":
            self.display.setText("")
            self.result_label.setText("0")
            self._last_result_text = ""
            self._just_evaluated = False
        elif key == "equals":
            self._on_equals()
        elif key == "mc":
            self._memory = 0.0
            self._refresh_memory_indicator()
        elif key == "mr":
            self._append_text(_format_number(self._memory))
        elif key == "mplus":
            self._memory += self._current_value_or_result()
            self._refresh_memory_indicator()
        elif key == "mminus":
            self._memory -= self._current_value_or_result()
            self._refresh_memory_indicator()

    # ------------------------------------------------------------------
    # Token appenders
    # ------------------------------------------------------------------
    def _append_text(self, ch: str) -> None:
        current = self.display.text()
        if self._just_evaluated:
            current = ""
            self._just_evaluated = False
        if ch == "." and self._current_token_has_dot(current):
            return
        # Replace a lone trailing "0" token so we don't get "01", "02"...
        if ch.isdigit() and self._trailing_token_is_zero(current):
            current = current[:-1]
        self.display.setText(current + ch)

    def _append_operator(self, op: str) -> None:
        # Normalize: accept either the ASCII (`*`, `/`, `-`) or the pretty form.
        op = self._ASCII_TO_PRETTY.get(op, op)
        current = self.display.text()
        if self._just_evaluated and self._last_result_text:
            current = self._last_result_text
            self._just_evaluated = False
        if not current:
            if op == self._SUB:
                self.display.setText(self._SUB)
                return
            current = "0"
        if current[-1] in self._OPERATORS:
            if op == self._SUB and current[-1] != self._SUB:
                # Allow a unary minus right after another operator (e.g. 5×−3).
                self.display.setText(current + op)
                return
            current = current[:-1] + op
        else:
            current = current + op
        self.display.setText(current)

    def _append_paren(self, paren: str) -> None:
        current = self.display.text()
        if self._just_evaluated:
            if paren == "(":
                current = ""
            else:
                current = self._last_result_text or current
            self._just_evaluated = False

        if paren == "(":
            # Implicit multiplication if a digit, ".", or ")" precedes "(".
            if current and (current[-1].isdigit() or current[-1] in {".", ")"}):
                current = current + "*("
            else:
                current = current + "("
        else:  # ")"
            if current.count("(") <= current.count(")"):
                return
            if not current or current[-1] in self._OPERATORS or current[-1] == "(":
                return
            current = current + ")"
        self.display.setText(current)

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------
    def _backspace(self) -> None:
        if self._just_evaluated:
            self.display.setText("")
            self._just_evaluated = False
            return
        text = self.display.text()
        self.display.setText(text[:-1])

    def _toggle_sign(self) -> None:
        text = self.display.text()
        if not text:
            if self._last_result_text:
                self.display.setText(
                    self._last_result_text[1:]
                    if self._last_result_text.startswith(self._SUB)
                    else self._SUB + self._last_result_text
                )
            return
        i = len(text) - 1
        while i >= 0 and (text[i].isdigit() or text[i] == "."):
            i -= 1
        token_start = i + 1
        token = text[token_start:]
        if not token:
            return
        prefix = text[:token_start]
        if prefix.endswith(self._SUB) and (
            len(prefix) == 1
            or prefix[-2] in self._OPERATORS
            or prefix[-2] == "("
        ):
            new_text = prefix[:-1] + token
        else:
            new_text = prefix + self._SUB + token
        self.display.setText(new_text)

    def _apply_percent(self) -> None:
        try:
            value = self._current_value_or_result()
        except ValueError:
            return
        formatted = _format_number(value / 100.0)
        self.display.setText(formatted)
        self.result_label.setText(formatted)
        self._last_result_text = formatted
        self._just_evaluated = True

    def _on_equals(self) -> None:
        display_expr = self.display.text().strip()
        if not display_expr:
            return
        while display_expr and display_expr[-1] in self._OPERATORS:
            display_expr = display_expr[:-1]
        opens = display_expr.count("(")
        closes = display_expr.count(")")
        if opens > closes:
            display_expr = display_expr + (")" * (opens - closes))
        if not display_expr:
            return

        eval_expr = self._to_eval(display_expr)
        try:
            result = safe_eval(eval_expr)
        except ZeroDivisionError:
            self.result_label.setText("Error: ÷0")
            self._just_evaluated = True
            return
        except ValueError as exc:
            self.result_label.setText(f"Error: {exc}")
            self._just_evaluated = True
            return

        formatted = _format_number(result)
        self.display.setText(display_expr)
        self.result_label.setText(formatted)
        self.history_list.insertItem(0, f"{display_expr} = {formatted}")
        self._last_result_text = formatted
        self._just_evaluated = True

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def _current_value_or_result(self) -> float:
        text = self.display.text().strip()
        if not text:
            if self._last_result_text:
                try:
                    return float(self._last_result_text)
                except ValueError:
                    return 0.0
            return 0.0
        try:
            return float(safe_eval(self._to_eval(text)))
        except (ValueError, ZeroDivisionError):
            return 0.0

    def _current_token_has_dot(self, text: str) -> bool:
        i = len(text) - 1
        while i >= 0 and (text[i].isdigit() or text[i] == "."):
            if text[i] == ".":
                return True
            i -= 1
        return False

    def _trailing_token_is_zero(self, text: str) -> bool:
        if not text or text[-1] != "0":
            return False
        if len(text) == 1:
            return True
        prev = text[-2]
        return not (prev.isdigit() or prev == ".")

    def _refresh_memory_indicator(self) -> None:
        self.mem_indicator.setText("M" if self._memory != 0.0 else "")

    def _toggle_history(self) -> None:
        self._history_visible = not self._history_visible
        self.history_list.setVisible(self._history_visible)
        self.history_toggle.setText("History ▴" if self._history_visible else "History ▾")
        self.adjustSize()

    def _reuse_history_item(self, item) -> None:
        text = item.text()
        if "=" in text:
            expr = text.split("=", 1)[0].strip()
            self.display.setText(expr)
            self._just_evaluated = False

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):  # noqa: N802 (Qt naming)
        key = event.key()
        text = event.text()

        if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Equal):
            self._on_equals()
            return
        if key == Qt.Key.Key_Backspace:
            self._backspace()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Escape):
            self._handle_key("clear")
            return
        if text:
            if text.isdigit() or text == ".":
                self._append_text(text)
                return
            if text in {"+", "-", "*", "/", "%"}:
                self._append_operator(text)
                return
            if text == "(":
                self._append_paren("(")
                return
            if text == ")":
                self._append_paren(")")
                return
        super().keyPressEvent(event)
