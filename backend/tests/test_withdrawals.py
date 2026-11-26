"""End-to-end behaviour for whole-batch training withdrawals (SQLite, no worker)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/test.db')
    monkeypatch.setenv('SEED_DEMO', 'true')
    for name in list(sys.modules):
        if name in ('src', 'migrations', 'scripts') or name.startswith(('src.', 'migrations.', 'scripts.')):
            del sys.modules[name]
    from src.main import app
    with TestClient(app) as test_client:
        yield test_client


def login(client, email):
    response = client.post('/api/auth/login', json={'email': email, 'password': 'Demo-2611!'})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def run_job(client):
    from src.services.execution import claim, execute
    for _ in range(20):
        job = claim()
        if job is None:
            return
        execute(job)


def queued_run(client, headers, label='重算'):
    response = client.post('/api/runs', json={'label': label, 'dataset_id': 1, 'settings': {}}, headers=headers)
    assert response.status_code == 202, response.text
    run_job(client)
    run = client.get(f"/api/runs/{response.json()['id']}", headers=headers)
    assert run.status_code == 200, run.text
    return run.json()


def approve(client, headers, run_id):
    response = client.post(f'/api/runs/{run_id}/review',
                           json={'decision': 'approved', 'note': '撤回后核对重算结果'}, headers=headers)
    assert response.status_code == 201, response.text


def test_withdrawal_blocks_only_affected_class(client):
    analyst = login(client, 'analyst@demo.local')
    admin = login(client, 'admin@demo.local')
    first = queued_run(client, analyst)
    approve(client, admin, first['id'])
    assert second_sheet(client, first['id'], analyst).status_code == 200

    # Withdraw one training batch: every class in that batch is suspended.
    response = client.post('/api/datasets/1/withdrawals',
                           json={'batch_id': 'TR-01', 'reason': '探头漂移，整批读数作废'}, headers=analyst)
    assert response.status_code == 201, response.text
    assert set(response.json()['affected_classes']) == {'mesh30', 'mesh60'}

    # The previously approved sheet is withheld for affected classes...
    blocked = client.get(f"/api/runs/{first['id']}/export/missing_cells", headers=analyst)
    assert blocked.status_code == 200
    assert blocked.headers['X-Withheld-Shade-Classes'] == 'mesh30,mesh60'
    assert 'mesh30' not in blocked.text and 'mesh60' not in blocked.text
    assert 'mesh80' in blocked.text

    # ...while an unaffected class still downloads its own handover sheet.
    unaffected = client.get(f"/api/runs/{first['id']}/export/missing_cells?shade_class=mesh80", headers=analyst)
    assert unaffected.status_code == 200
    assert 'mesh80' in unaffected.text
    assert 'mesh30' not in unaffected.text
    pinned_blocked = client.get(f"/api/runs/{first['id']}/export/missing_cells?shade_class=mesh30", headers=analyst)
    assert pinned_blocked.status_code == 409

    # ...but the run view explains per-class delivery.
    detail = client.get(f"/api/runs/{first['id']}", headers=analyst).json()
    assert detail['deliverable'] is False
    assert detail['delivery']['mesh30']['deliverable'] is False
    assert detail['delivery']['mesh80']['deliverable'] is True

    recomputed = queued_run(client, analyst)
    approve(client, admin, recomputed['id'])
    sheet = second_sheet(client, recomputed['id'], analyst)
    assert sheet.status_code == 200
    frozen = client.get(f"/api/runs/{recomputed['id']}/export/frozen_reference", headers=analyst)
    assert frozen.status_code == 200
    assert 'TR-01' in frozen.text


def second_sheet(client, run_id, headers):
    return client.get(f'/api/runs/{run_id}/export/missing_cells', headers=headers)


def test_second_withdrawal_during_recompute_invalidates_partial(client):
    analyst = login(client, 'analyst@demo.local')
    admin = login(client, 'admin@demo.local')

    client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-01', 'reason': '第一批探头漂移'}, headers=analyst)
    partial = queued_run(client, analyst)
    approve(client, admin, partial['id'])

    # Second withdrawal arrives after the run that only dropped TR-01 completed.
    client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-02', 'reason': '第二批探头漂移'}, headers=analyst)

    stale = client.get(f"/api/runs/{partial['id']}/export/missing_cells", headers=analyst)
    assert stale.status_code == 409 or 'TR-02' not in stale.text
    detail = client.get(f"/api/runs/{partial['id']}", headers=analyst).json()
    assert detail['delivery']['mesh30']['current_withdrawals'] == ['TR-01', 'TR-02']

    complete = queued_run(client, analyst)
    approve(client, admin, complete['id'])
    assert client.get(f"/api/runs/{complete['id']}/export/missing_cells", headers=analyst).status_code == 200
    stale_again = client.get(f"/api/runs/{partial['id']}/export/missing_cells", headers=analyst)
    assert stale_again.headers['X-Withheld-Shade-Classes'] == 'mesh30,mesh60'


def test_withdrawal_mid_computation_uses_all_batches(client, monkeypatch):
    analyst = login(client, 'analyst@demo.local')
    from src.config.database import Session
    from src.models.dataset import Dataset
    from src.services.withdrawals import current_state

    with Session.begin() as session:
        dataset_id, rows = 1, session.get(Dataset, 1).rows
        state = current_state(session, session.get(Dataset, dataset_id))
    assert state == {}

    # A withdrawal lands between claim() and the first analyze() pass.
    client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-03', 'reason': '复算途中探头漂移'}, headers=analyst)

    # And a second one lands after the first pass but before the re-check.
    import src.services.execution as execution
    original = execution.analyze
    calls = {'n': 0}

    def analyze_then_second(rows, settings, applied):
        result = original(rows, settings, applied)
        calls['n'] += 1
        if calls['n'] == 1:
            client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-04', 'reason': '复算途中又撤一批'},
                        headers=analyst)
        return result

    monkeypatch.setattr(execution, 'analyze', analyze_then_second)
    result, applied = execution.compute_latest(dataset_id, rows, {}, state)
    assert calls['n'] >= 2
    assert applied == {'mesh30': ['TR-03', 'TR-04'], 'mesh60': ['TR-03', 'TR-04']}
    assert result['withdrawals'] == applied


def test_viewer_gets_unaffected_class_and_cannot_withdraw(client):
    analyst = login(client, 'analyst@demo.local')
    admin = login(client, 'admin@demo.local')
    viewer = login(client, 'viewer@demo.local')
    first = queued_run(client, analyst)
    approve(client, admin, first['id'])
    assert client.post('/api/datasets/1/withdrawals',
                       json={'batch_id': 'TR-01', 'reason': '探头漂移作废'}, headers=viewer).status_code == 403

    client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-01', 'reason': '探头漂移作废'}, headers=analyst)
    sheet = client.get(f"/api/runs/{first['id']}/export/missing_cells", headers=viewer)
    assert sheet.status_code == 200
    assert 'mesh80' in sheet.text and 'mesh30' not in sheet.text
    pinned = client.get(f"/api/runs/{first['id']}/export/missing_cells?shade_class=mesh30", headers=viewer)
    assert pinned.status_code == 409


def test_review_refuses_stale_withdrawal_snapshot(client):
    """A run whose result predates a withdrawal cannot be signed off as-is."""
    analyst = login(client, 'analyst@demo.local')
    admin = login(client, 'admin@demo.local')
    first = queued_run(client, analyst)
    # Withdrawal lands before review, so the completed result no longer reflects the ledger.
    client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-01', 'reason': '签核前发现探头漂移'},
                headers=analyst)
    response = client.post(f"/api/runs/{first['id']}/review",
                           json={'decision': 'approved', 'note': '试图签核过时结果'}, headers=admin)
    assert response.status_code == 409

    recomputed = queued_run(client, analyst)
    approve(client, admin, recomputed['id'])


def test_rejects_non_train_batch_and_duplicates(client):
    analyst = login(client, 'analyst@demo.local')
    bad = client.post('/api/datasets/1/withdrawals', json={'batch_id': 'PE-01', 'reason': '不应撤回待补测次'}, headers=analyst)
    assert bad.status_code == 422
    missing = client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-99', 'reason': '不存在训练批'}, headers=analyst)
    assert missing.status_code == 422
    ok = client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-01', 'reason': '探头漂移作废'}, headers=analyst)
    assert ok.status_code == 201
    dup = client.post('/api/datasets/1/withdrawals', json={'batch_id': 'TR-01', 'reason': '重复登记'}, headers=analyst)
    assert dup.status_code == 409
    listed = client.get('/api/datasets/1/withdrawals', headers=analyst).json()
    assert [item['batch_id'] for item in listed] == ['TR-01']
    assert listed[0]['affected_classes'] == ['mesh30', 'mesh60']


def test_single_class_withdrawal_keeps_other_class_available(client):
    """A batch that only holds one shade class suspends just that class."""
    analyst = login(client, 'analyst@demo.local')
    admin = login(client, 'admin@demo.local')
    csv = _csv_with_one_class_batch()
    dataset_id = client.post('/api/datasets', json={'name': '单档训练批台账', 'csv': csv},
                             headers=analyst).json()['id']
    run = client.post('/api/runs', json={'label': '单档撤回', 'dataset_id': dataset_id, 'settings': {}},
                      headers=analyst)
    run_job(client)
    run_id = run.json()['id']
    approve(client, admin, run_id)

    registered = client.post(f'/api/datasets/{dataset_id}/withdrawals',
                             json={'batch_id': 'TR-01', 'reason': '只有 mesh30 的探头漂移'}, headers=analyst)
    assert registered.json()['affected_classes'] == ['mesh30']

    sheet = client.get(f'/api/runs/{run_id}/export/missing_cells', headers=analyst)
    assert sheet.status_code == 200
    assert sheet.headers.get('X-Withheld-Shade-Classes') == 'mesh30'
    assert 'mesh60' in sheet.text and 'mesh30' not in sheet.text
    detail = client.get(f'/api/runs/{run_id}', headers=analyst).json()
    assert detail['delivery']['mesh30']['deliverable'] is False
    assert detail['delivery']['mesh60']['deliverable'] is True


def _csv_with_one_class_batch():
    """TR-01 holds only mesh30; TR-02 onward are mesh60 training plus a holdout/pending."""
    import csv as _csv
    import io

    from src.domain.settings import COLUMNS

    rows = []
    for i in range(6):
        rows.append({'reading_id': f'TR-01-0{i + 1}', 'batch_id': 'TR-01', 'partition': 'train',
                     'shade_class': 'mesh30', 'temp_c': 20.0 + i, 'rh_pct': 70.0 + i, 'par': 200.0 + i})
    for i in range(6):
        rows.append({'reading_id': f'TR-02-0{i + 1}', 'batch_id': 'TR-02', 'partition': 'train',
                     'shade_class': 'mesh60', 'temp_c': 24.0 + i, 'rh_pct': 74.0 + i, 'par': 240.0 + i})
    for i in range(6):
        rows.append({'reading_id': f'HO-01-0{i + 1}', 'batch_id': 'HO-01', 'partition': 'holdout',
                     'shade_class': 'mesh60', 'temp_c': 20.5 + i, 'rh_pct': 70.5 + i, 'par': 205.0 + i})
    rows.append({'reading_id': 'PE-01-01', 'batch_id': 'PE-01', 'partition': 'pending',
                 'shade_class': 'mesh30', 'temp_c': None, 'rh_pct': 70.0, 'par': 200.0})
    rows.append({'reading_id': 'PE-01-02', 'batch_id': 'PE-01', 'partition': 'pending',
                 'shade_class': 'mesh60', 'temp_c': None, 'rh_pct': 70.0, 'par': 200.0})
    buffer = io.StringIO()
    writer = _csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def test_insufficient_readings_switch_to_manual_recheck(client):
    analyst = login(client, 'analyst@demo.local')
    csv = _csv_with_thinned_mesh30()
    imported = client.post('/api/datasets', json={'name': '撤回后不足台账', 'csv': csv}, headers=analyst)
    assert imported.status_code == 201, imported.text
    dataset_id = imported.json()['id']

    before = client.post('/api/runs', json={'label': '撤回前', 'dataset_id': dataset_id, 'settings': {}},
                         headers=analyst)
    run_job(client)
    before_detail = client.get(f"/api/runs/{before.json()['id']}", headers=analyst).json()
    assert before_detail['result']['tables'][0]['rows'][0]['proposed_value'] is not None

    client.post(f'/api/datasets/{dataset_id}/withdrawals',
                json={'batch_id': 'TR-01', 'reason': '整批探头漂移'}, headers=analyst)
    after = client.post('/api/runs', json={'label': '撤回后', 'dataset_id': dataset_id, 'settings': {}},
                        headers=analyst)
    run_job(client)
    detail = client.get(f"/api/runs/{after.json()['id']}", headers=analyst).json()
    assert detail['status'] == 'completed'
    cells = detail['result']['tables'][0]['rows']
    mesh30 = [cell for cell in cells if cell['shade_class'] == 'mesh30']
    assert mesh30 and all(cell['proposed_value'] is None for cell in mesh30)
    assert all('同档训练读数不足' in cell['reason'] and '改派人工补测' in cell['reason'] for cell in mesh30)
    assert 'TR-01' in mesh30[0]['reason']
    assert '同档训练读数不足，已改派人工补测：mesh30' in detail['result']['summary']


def _csv_with_thinned_mesh30():
    """Two mesh30 training batches; withdrawing the first leaves 4 rows, below the 5 neighbours."""
    import csv as _csv
    import io

    from src.domain.settings import COLUMNS

    rows = []
    for i in range(5):
        rows.append({'reading_id': f'TR-01-0{i + 1}', 'batch_id': 'TR-01', 'partition': 'train',
                     'shade_class': 'mesh30', 'temp_c': 20.0 + i, 'rh_pct': 70.0 + i, 'par': 200.0 + i})
    for i in range(4):
        rows.append({'reading_id': f'TR-02-0{i + 1}', 'batch_id': 'TR-02', 'partition': 'train',
                     'shade_class': 'mesh30', 'temp_c': 24.0 + i, 'rh_pct': 74.0 + i, 'par': 240.0 + i})
    for i in range(6):
        rows.append({'reading_id': f'HO-01-0{i + 1}', 'batch_id': 'HO-01', 'partition': 'holdout',
                     'shade_class': 'mesh30', 'temp_c': 20.5 + i, 'rh_pct': 70.5 + i, 'par': 205.0 + i})
    rows.append({'reading_id': 'PE-01-01', 'batch_id': 'PE-01', 'partition': 'pending',
                 'shade_class': 'mesh30', 'temp_c': None, 'rh_pct': 70.0, 'par': 200.0})
    buffer = io.StringIO()
    writer = _csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()

