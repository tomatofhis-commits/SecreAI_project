import pytest
import os
import tempfile
import time
from scripts.api_cache_system import APICache

def test_api_cache_basic():
    """基本機能のテスト: セットした値が取得できること"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = APICache(tmpdir, ttl_hours=1)
        prompt = "Hello, how are you?"
        response = "I am fine, thank you."
        
        cache.set(prompt, response, None, "gemini", "flash")
        result = cache.get(prompt, None, "gemini", "flash")
        
        assert result == response

def test_api_cache_different_models():
    """モデルが異なる場合はキャッシュがヒットしないこと"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = APICache(tmpdir, ttl_hours=1)
        prompt = "test prompt"
        
        cache.set(prompt, "resp1", None, "gemini", "flash")
        result = cache.get(prompt, None, "openai", "gpt-4")
        
        assert result is None

def test_api_cache_expiry():
    """有効期限（TTL）が切れた場合にキャッシュが取得できないこと"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # TTLを極端に短く設定（実際には hours 単位だが、テスト用にモックするか、0を指定して挙動を確認）
        # 現状の APICache は time.time() > expire_time で判定している
        # 簡易的に expire を 0 にして即死させるテスト（実装が ttl_hours * 3600 なので 0 なら即死か）
        cache = APICache(tmpdir, ttl_hours=0) 
        prompt = "expired prompt"
        
        cache.set(prompt, "expired resp", None, "gemini", "flash")
        time.sleep(0.1) # 念のため
        result = cache.get(prompt, None, "gemini", "flash")
        
        assert result is None

def test_api_cache_with_image():
    """画像付きキャッシュのテスト: 画像ハッシュが考慮されること"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = APICache(tmpdir, ttl_hours=1)
        prompt = "Look at this image"
        
        # ダミー画像ファイル作成
        img1_path = os.path.join(tmpdir, "img1.png")
        with open(img1_path, "wb") as f:
            f.write(b"dummy image data 1")
            
        img2_path = os.path.join(tmpdir, "img2.png")
        with open(img2_path, "wb") as f:
            f.write(b"dummy image data 2")

        # 画像1で保存
        cache.set(prompt, "response with img1", img1_path, "gemini", "pro")
        
        # 画像1で取得 -> ヒットすべき
        assert cache.get(prompt, img1_path, "gemini", "pro") == "response with img1"
        
        # 画像2で取得 -> ヒットしないべき
        assert cache.get(prompt, img2_path, "gemini", "pro") is None
        
        # 画像なしで取得 -> ヒットしないべき
        assert cache.get(prompt, None, "gemini", "pro") is None
