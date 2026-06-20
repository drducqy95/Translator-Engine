import pytest
import sys
from pathlib import Path

# Thêm Script vào path
engine_dir = Path(__file__).parent.parent
sys.path.append(str(engine_dir / "Script"))

from qt_engine import QTEngine

@pytest.fixture
def qt():
    engine = QTEngine()
    yield engine
    engine.close()

def test_basic_translation(qt):
    source = "我是一个人。"
    draft, cov, unk, known = qt.translate(source)
    assert len(draft) > 0
    assert cov > 0

def test_number_translation(qt):
    source = "三十五"
    draft, cov, unk, known = qt.translate(source)
    assert "35" in draft

def test_translation_memory_bypass(qt):
    # Dùng chuỗi siêu lạ để test
    source = "THIS IS A VERY UNIQUE STRING FOR TM TEST"
    # Lừa TM engine lưu nó
    qt.tm_engine.save(source, "ĐÂY LÀ CHUỖI ĐÃ ĐƯỢC TM LƯU")
    
    draft, cov, unk, known = qt.translate(source)
    assert draft == "ĐÂY LÀ CHUỖI ĐÃ ĐƯỢC TM LƯU"
    assert cov == 1.0
