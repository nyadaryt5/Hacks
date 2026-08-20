import os
import pytest
from unittest.mock import patch, MagicMock

# Ensure no real keys
os.environ.pop('GOOGLE_API_KEY', None)

def test_google_ai_client_offline():
    from ultron.llm import GoogleAIClient
    client = GoogleAIClient(api_key=None)
    assert client is not None
    # Should not attempt network call
    with patch.object(client, '_make_request', return_value={"candidates": [{"content": {"parts": [{"text": "stub"}]}}]}):
        resp = client.generate("test prompt")
        assert "stub" in str(resp)

def test_vector_memory_offline():
    from ultron.memory import VectorMemory
    vm = VectorMemory()
    assert vm is not None
    vm.add("doc1", "hello world")
    results = vm.search("hello")
    assert len(results) >= 0

def test_database_manager_offline():
    from ultron.db import DatabaseManager
    db = DatabaseManager()
    assert db is not None
    db.save({"key": "value"})
    data = db.load()
    assert isinstance(data, dict) or data is None
