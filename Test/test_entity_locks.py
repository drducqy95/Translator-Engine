from Script.entity_locks import apply_locked_terms_to_output
from Script.foreign_converter import analyze_and_convert_entity
from Script.qc_checker import QCChecker


def test_foreign_converter_latn_jp_kr():
    assert analyze_and_convert_entity('Pette Chinar') == {'type': 'Latin', 'converted': 'Pette Chinar'}
    assert analyze_and_convert_entity('佐藤健') == {'type': 'Japanese', 'converted': 'Sato Takeru'}
    assert analyze_and_convert_entity('朴智星') == {'type': 'Korean', 'converted': 'Park Ji-sung'}
    assert analyze_and_convert_entity('金秀贤') == {'type': 'Korean', 'converted': 'Kim Soo-hyun'}


def test_locked_terms_applied_to_output():
    context_pack = {
        'raw_segments': [{'id': 1, 'text': '培特 和 佐藤健'}],
        'locked_dictionary': {'characters': {'培特': 'Pette Chinar', '佐藤健': 'Sato Takeru'}, 'glossary': {}},
    }
    ai_output = {'refined_segments': [{'id': 1, 'refined_translation': 'Bồi Đặc gặp 佐藤健.'}]}
    normalized = apply_locked_terms_to_output(ai_output, context_pack)
    assert normalized['refined_segments'][0]['refined_translation'] == 'Pette Chinar gặp Sato Takeru.'


def test_qc_fails_missing_locked_term():
    context_pack = {
        'raw_segments': [{'id': 1, 'text': '培特'}],
        'locked_dictionary': {'characters': {'培特': 'Pette Chinar'}, 'glossary': {}},
    }
    ai_output = {'refined_segments': [{'id': 1, 'refined_translation': 'Bản dịch khác.'}]}
    result = QCChecker(context_pack, ai_output).check()
    assert result['passed'] is False
    assert any('Thiếu term đã khóa' in err for err in result['errors'])
