"""Synthetic end-to-end smoke tests; no production model loading / no network."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
import shutil

from app.github_model_release import _extract_verified, _manifest, sync_render_models
from app.git_model_sync import sync_git_models


def sha(x):
    return hashlib.sha256(x).hexdigest()


def run():
    import importlib.metadata
    version = importlib.metadata.version('scikit-learn')
    old_env = {k:os.getenv(k) for k in ('PRIX_EXPECTED_SKLEARN_VERSION','PRIX_GIT_SYNC_MIN_BASE_ENTRIES')}
    os.environ['PRIX_EXPECTED_SKLEARN_VERSION'] = version
    os.environ['PRIX_GIT_SYNC_MIN_BASE_ENTRIES'] = '1'
    try:
        with tempfile.TemporaryDirectory() as temp:
            top = Path(temp)
            repo, disk = top/'repo', top/'disk'
            new, old = 'test-new-league', 'test-old-league'
            delta = {new:{'model_folder':new,'footystats_season_id':23456,'model_family':'main_league','model_version':'test-v0.6.4','enabled':True}}
            old_registry = {old:{'model_folder':old,'footystats_season_id':12345,'enabled':True}}
            (repo/'deploy_models').mkdir(parents=True)
            (disk/old).mkdir(parents=True)
            (disk/'leagues.json').write_text(json.dumps({'leagues':old_registry}))
            registry = json.dumps({'leagues':delta}).encode()
            (repo/'deploy_models'/'leagues.json').write_bytes(registry)
            cfg = {'league_slug':new,'model_version':'test-v0.6.4','model_family':'main_league','feature_columns_file':'feature_columns.json','models':{'market':'model.pkl'}}
            metadata = {'league_slug':new,'sklearn_training_version':version}
            binary = b'FAKE MODEL BYTES, NOT A LOADABLE PICKLE' * 8
            files = {'model_config.json':json.dumps(cfg).encode(),'model_metadata_v064.json':json.dumps(metadata).encode(),'feature_columns.json':b'[]','model.pkl':binary}
            manifest = {'format':1,'registry_sha256':sha(registry),'folders':[new], 'files':{f'{new}/{k}':{'sha256':sha(v),'size':len(v)} for k,v in files.items()}}
            (repo/'deploy_models'/'model_manifest.json').write_text(json.dumps(manifest))
            _manifest(repo)
            archive = top/'models.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for name, value in files.items():
                    z.writestr(f'models/{new}/{name}',value)
            stage=top/'unpacked'
            stage.mkdir()
            _extract_verified(archive,stage,manifest)
            first=sync_git_models(repo_root=repo,disk_root=disk,source_models_override=stage)
            assert first['installed']==[new] and first['registry_entries_after']==2,first
            assert old in json.loads((disk/'leagues.json').read_text())['leagues']
            second=sync_git_models(repo_root=repo,disk_root=disk,source_models_override=stage)
            assert second['installed']==[] and second['unchanged']==[new],second
            (disk/new/'model.pkl').write_bytes(b'OLD DIFFERENT FILE')
            try:
                sync_git_models(repo_root=repo,disk_root=disk,source_models_override=stage)
                raise AssertionError('Existing model replacement should be blocked')
            except ValueError as e:
                assert 'Replacement is blocked' in str(e),str(e)
            bad = top/'malicious.zip'
            with zipfile.ZipFile(bad,'w') as z:
                z.writestr('../escape', b'unsafe')
            try:
                _extract_verified(bad,top/'unsafe',manifest)
                raise AssertionError('Zip traversal should be blocked')
            except ValueError:
                pass
            # Re-run from the original source as though GitHub had published it.
            (disk / new / 'model.pkl').write_bytes(binary)
            calls = []
            def fake_download(repo_name, tag, archive_path):
                calls.append((repo_name, tag))
                shutil.copy2(archive, archive_path)
                return {'release_tag':tag, 'archive_sha256':sha(archive.read_bytes()), 'download_bytes':archive.stat().st_size}
            with patch.dict(os.environ, {'PRIX_GITHUB_MODEL_REPO':'fake-owner/fake-repo',
                                          'PRIX_GITHUB_MODEL_RELEASE_TAG':'prix-models-latest'}), \
                 patch('app.config.project_root',return_value=repo), \
                 patch('app.config.model_root_path',return_value=disk), \
                 patch('app.github_model_release._download_release_zip',side_effect=fake_download):
                cold = sync_render_models()
                warm = sync_render_models()
                assert cold['source']=='github_release' and warm['source']=='github_release_cached', (cold, warm)
                assert len(calls)==1,calls
            print('PASS: archive, GitHub download stub, startup sync, cached restart, idempotence, replacement protection, traversal rejection')
    finally:
        for k,v in old_env.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k] = v


if __name__=='__main__':run()
