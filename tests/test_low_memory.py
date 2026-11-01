from __future__ import annotations
import os
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_test_root = Path(__file__).resolve().parent.parent if Path(__file__).resolve().parent.name == 'tests' else Path(__file__).resolve().parent
_project_root = _test_root if (_test_root / 'app').is_dir() else _test_root / 'api'
sys.path.insert(0, str(_project_root))
from app import storage
from app.config import settings
from app.main import _cache_info, _classify_matches, _sync_league_matches
from app.model_registry import ModelRegistry
from fastapi.testclient import TestClient
from app.main import app


class Smoke(unittest.TestCase):
    def test_write_cache_roundtrip_and_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            with patch.object(storage, 'cache_root_path', return_value=Path(tempdir)), patch('app.main.cache_path', storage.cache_path):
                payload = [{'n': n, 's': 'data'*10} for n in range(1500)]
                storage.write_cache('large', payload, metadata={'league': 'test'})
                self.assertEqual(storage.read_cache('large'), payload)
                self.assertTrue(_cache_info('large')['cached_at'])
                self.assertTrue(storage.cache_path('large').exists())
                self.assertFalse(list(Path(tempdir).glob('*.tmp')))

    def test_model_evicted_before_next_load(self):
        from app import model_registry as module
        registry = ModelRegistry()
        observed_lengths = []
        def fake_model(slug):
            observed_lengths.append(len(registry._cache))
            return {'slug': slug}
        with patch.object(module.league_registry, 'get', side_effect=lambda slug: {}), patch.object(module, 'LoadedLeagueModel', side_effect=fake_model), patch.object(settings, 'max_cached_league_models', 1):
            registry.get('one')
            registry.get('two')
            self.assertEqual(observed_lengths, [0, 0])
            self.assertEqual(list(registry._cache), ['two'])

    def test_sync_preserves_classification(self):
        rows = [
            {'id': 1, 'date_unix': 1, 'status': 'complete'},
            {'id': 2, 'date_unix': 2000000000, 'status': 'scheduled'},
        ]
        # Compare against the canonical classification function on a representative data sample,
        # using mocks for the actual normalization/FootyStats calls.
        from app import main
        mapped = {
            1: {'status':'complete', 'kickoff_time':'2020-01-01T12:00:00Z', 'match_date':'2020-01-01'},
            2: {'status':'scheduled', 'kickoff_time':'2030-01-01T12:00:00Z', 'match_date':'2030-01-01'},
        }
        completed, upcoming = None, None
        with patch.object(main, 'normalize_footystats_match', side_effect=lambda row: mapped[row['id']]), \
             patch.object(main, 'is_completed_status', side_effect=lambda status: status == 'complete'), \
             patch.object(main, 'is_cancelled_status', return_value=False), \
             patch.object(main, '_registry_identifier', return_value=({'display_name':'Example'}, '123')), \
             patch.object(main.footystats_client, 'league_matches', return_value=rows), \
             patch.object(main, 'write_cache'), \
             patch.object(main, '_cache_info', return_value={'exists':True}):
            completed, upcoming = _classify_matches(rows,'2030-01-01','2030-01-01')
            result = _sync_league_matches('example','2030-01-01','2030-01-01')
            self.assertEqual(result['completed_raw'], completed)
            self.assertEqual(result['fixtures_raw'], upcoming)
            self.assertEqual(result['fixture_count'], 1)
            self.assertEqual(result['completed_count'], 1)

    def test_memory_gate_rejects_overlapping_heavy_request(self):
        class BusyLock:
            async def acquire(self):
                await asyncio.sleep(5)
        from app import main
        with patch.object(main, '_heavy_request_lock', BusyLock()), patch.object(settings, 'heavy_request_wait_seconds', 0.1):
            with TestClient(app) as client:
                response = client.get('/models')
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['code'], 'MODEL_BUSY')
                self.assertEqual(response.headers['retry-after'], '5')

    def test_health_untouched(self):
        with TestClient(app) as client:
            result = client.get('/health')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['status'], 'ok')

if __name__ == '__main__':
    unittest.main(verbosity=2)
