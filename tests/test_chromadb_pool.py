import pytest
import os
import tempfile
import shutil
from scripts.chromadb_pool import ChromaDBPool

def test_chromadb_pool_singleton():
    """プールのシングルトン動作と再利用のテスト"""
    pool1 = ChromaDBPool()
    pool2 = ChromaDBPool()
    
    # 同じインスタンスであること（シングルトン）
    assert pool1 is pool2

def test_chromadb_get_client():
    """指定したパスのクライアントが正しく取得・キャッシュされること"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool = ChromaDBPool()
        client1 = pool.get_client(tmpdir)
        client2 = pool.get_client(tmpdir)
        
        # 同じパスなら同じクライアントを返すこと
        assert client1 is client2
        assert client1.get_settings().is_persistent is True

def test_chromadb_operations():
    """ChromaDBへの書き込みと検索の基本テスト"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool = ChromaDBPool()
        client = pool.get_client(tmpdir)
        
        # コレクション作成
        collection = client.get_or_create_collection(name="test_collection")
        
        # データ追加
        collection.add(
            documents=["This is a test document", "Hello world"],
            metadatas=[{"source": "test"}, {"source": "manual"}],
            ids=["id1", "id2"]
        )
        
        # 検索
        results = collection.query(
            query_texts=["test document"],
            n_results=1
        )
        
        assert "This is a test document" in results['documents'][0]
        assert results['ids'][0][0] == "id1"

@pytest.fixture(autouse=True)
def cleanup():
    """テストごとにプールをクリア（テスト間の独立性を確保）"""
    pool = ChromaDBPool()
    # 内部変数は _clients と _collections
    pool._clients = {}
    pool._collections = {}
    yield 
    # テスト終了後にもクリアしておく
    pool._clients = {}
    pool._collections = {}

def test_chromadb_get_client():
    """指定したパスのクライアントが正しく取得・キャッシュされること"""
    tmpdir = tempfile.mkdtemp()
    try:
        pool = ChromaDBPool()
        client1 = pool.get_client(tmpdir)
        client2 = pool.get_client(tmpdir)
        
        # 同じパスなら同じクライアントを返すこと
        assert client1 is client2
    finally:
        # poolの参照を消さないとWindowsでは削除できない
        pool = ChromaDBPool()
        pool._clients = {}
        pool._collections = {}
        import gc
        gc.collect() # 参照を強制解放
        try:
            shutil.rmtree(tmpdir)
        except:
            pass # 閉じた直後だとまだロックされていることがあるので無視

def test_chromadb_operations():
    """ChromaDBへの書き込みと検索の基本テスト"""
    tmpdir = tempfile.mkdtemp()
    try:
        pool = ChromaDBPool()
        client = pool.get_client(tmpdir)
        
        # コレクション作成
        collection = client.get_or_create_collection(name="test_collection")
        
        # データ追加
        collection.add(
            documents=["This is a test document", "Hello world"],
            metadatas=[{"source": "test"}, {"source": "manual"}],
            ids=["id1", "id2"]
        )
        
        # 検索
        results = collection.query(
            query_texts=["test document"],
            n_results=1
        )
        
        assert "This is a test document" in results['documents'][0]
        assert results['ids'][0][0] == "id1"
    finally:
        pool = ChromaDBPool()
        pool._clients = {}
        pool._collections = {}
        import gc
        gc.collect()
        try:
            shutil.rmtree(tmpdir)
        except:
            pass
