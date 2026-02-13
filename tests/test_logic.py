import pytest
import re
from unittest.mock import MagicMock, patch

def test_search_tag_filtering():
    """履歴保存時の [SEARCH: ...] タグ除去ロジックのテスト"""
    processing_target = [
        "あなた: こんにちは [SEARCH: hello]",
        "AI: こんにちは、何かお手伝いしましょうか？",
        "あなた: 今日の天気は？ [SEARCH: today weather Tokyo]",
        "AI: 晴れのち曇りです。[SEARCH: weather Tokyo report]"
    ]
    
    filtered_target = []
    for line in processing_target:
        # update_memory.py と同じロジック
        clean_line = re.sub(r'\[SEARCH:.*?\]', '', line).strip()
        if clean_line:
            filtered_target.append(clean_line)
            
    assert len(filtered_target) == 4
    assert "[SEARCH:" not in filtered_target[0]
    assert "こんにちは" in filtered_target[0]
    assert "[SEARCH:" not in filtered_target[2]
    assert "今日の天気は？" in filtered_target[2]

@patch('ollama.chat')
def test_should_execute_search_logic(mock_chat):
    """ゲートキーパーAIの判定ロジックのテスト"""
    from scripts.game_ai import should_execute_search
    
    # モックの戻り値を設定 (必要と判断)
    mock_chat.return_value = {
        'message': {
            'content': '{"necessary": true, "optimized_query": "Tokyo weather", "reason": "Latest info needed"}'
        }
    }
    
    config = {"MODEL_ID_SUMMARY": "test-model"}
    # log_m 引数として {} を追加
    res = should_execute_search("東京の天気教えて", config, {})
    
    assert res["necessary"] is True
    assert res["optimized_query"] == "Tokyo weather"
    
    # モックの戻り値を設定 (不要と判断)
    mock_chat.return_value = {
        'message': {
            'content': '{"necessary": false, "optimized_query": "", "reason": "Common knowledge"}'
        }
    }
    
    res = should_execute_search("1+1は？", config, {})
    assert res["necessary"] is False

def test_gatekeeper_error_fallback():
    """ゲートキーパーAIがエラーを吐いた際のフォールバックテスト"""
    from scripts.game_ai import should_execute_search
    
    # ollama.chat を直接モック化
    with patch('ollama.chat', side_effect=Exception("API Error")):
        # エラー時は True を返して検索を許可するはず
        res = should_execute_search("test query", {}, {})
        assert res["necessary"] is True
        assert res["reason"] == "Gatekeeper failed"
