"""pytest 公共配置：无显示环境下以 offscreen 运行 Qt（C 线所有）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from original_words.application.services import ServiceContainer  # noqa: E402
from original_words.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 18, 12, 0, 0)


@pytest.fixture
def container(now: datetime) -> ServiceContainer:
    return ServiceContainer(now=now)


@pytest.fixture
def window(qtbot, container: ServiceContainer) -> MainWindow:
    win = MainWindow(container)
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(20)
    return win
