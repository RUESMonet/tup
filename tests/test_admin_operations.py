import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.dependencies as dependencies
from src.api import image_routes as routes
from src.config import Settings
from src.main import create_app
from src.models.project import AssetKind, TaskKind
from src.services.database import SQLiteDatabase
from src.services.project_repository import ProjectRepository


def _client(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = Settings(
        auth_required=False,
        rate_limit_requests=1000,
        database_path=tmp_path / 'app.db',
        asset_upload_dir=tmp_path / 'uploads',
        use_mock_images=True,
        use_mock_videos=True,
        secure_session_cookies=False,
    )
    dependencies.get_storage.cache_clear()
    dependencies._database_for_path.cache_clear()
    routes._rate_limit_hits.clear()
    return TestClient(create_app(settings)), settings


def _register(client: TestClient, username: str) -> str:
    response = client.post(
        '/api/auth/register',
        json={'username': username, 'email': f'{username}@example.com', 'password': 'correct horse battery staple'},
    )
    assert response.status_code == 201
    return response.json()['user']['id']


def _promote(settings: Settings, username: str) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute('UPDATE users SET role = \'admin\' WHERE username = ?', (username,))


def test_uploaded_or_repository_created_assets_default_to_pending_review(tmp_path):
    client, settings = _client(tmp_path)
    user_id = _register(client, 'ada')
    project_id = client.post('/api/projects', json={'name': 'Review project'}).json()['id']
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))

    asset = repository.create_asset(user_id, project_id, AssetKind.image, 'mock://image.png', 'image/png', {'source': 'test'})
    response = client.get(f'/api/projects/{project_id}/assets')

    assert asset.review_status == 'pending'
    assert response.json()['assets'][0]['review_status'] == 'pending'


def test_admin_review_queue_requires_admin_and_can_approve_asset(tmp_path):
    user_client, settings = _client(tmp_path)
    admin_client, _ = _client(tmp_path)
    user_id = _register(user_client, 'ada')
    _register(admin_client, 'admin')
    _promote(settings, 'admin')
    project_id = user_client.post('/api/projects', json={'name': 'Review project'}).json()['id']
    asset = ProjectRepository(SQLiteDatabase(settings.database_path)).create_asset(user_id, project_id, AssetKind.image, 'mock://image.png', 'image/png', {'source': 'test'})

    forbidden = user_client.get('/api/admin/assets/review-queue')
    queue = admin_client.get('/api/admin/assets/review-queue')
    update = admin_client.post(f'/api/admin/assets/{asset.id}/review', json={'review_status': 'approved', 'review_notes': 'safe product image'})
    updated_queue = admin_client.get('/api/admin/assets/review-queue?review_status=approved')

    assert forbidden.status_code == 403
    assert queue.status_code == 200
    assert queue.json()['assets'][0]['id'] == asset.id
    assert update.status_code == 200
    assert update.json()['review_status'] == 'approved'
    assert updated_queue.json()['assets'][0]['review_notes'] == 'safe product image'


def test_resetting_asset_review_to_pending_clears_reviewer_fields(tmp_path):
    user_client, settings = _client(tmp_path)
    admin_client, _ = _client(tmp_path)
    user_id = _register(user_client, 'ada')
    _register(admin_client, 'admin')
    _promote(settings, 'admin')
    project_id = user_client.post('/api/projects', json={'name': 'Review project'}).json()['id']
    asset = ProjectRepository(SQLiteDatabase(settings.database_path)).create_asset(user_id, project_id, AssetKind.image, 'mock://image.png', 'image/png', {'source': 'test'})

    approved = admin_client.post(f'/api/admin/assets/{asset.id}/review', json={'review_status': 'approved', 'review_notes': 'safe product image'})
    pending = admin_client.post(f'/api/admin/assets/{asset.id}/review', json={'review_status': 'pending', 'review_notes': ' needs another pass '})

    assert approved.status_code == 200
    assert pending.status_code == 200
    assert pending.json()['review_status'] == 'pending'
    assert pending.json()['review_notes'] == 'needs another pass'
    assert pending.json()['reviewed_by'] is None
    assert pending.json()['reviewed_at'] is None


def test_admin_review_queue_handles_corrupt_asset_metadata(tmp_path):
    user_client, settings = _client(tmp_path)
    admin_client, _ = _client(tmp_path)
    user_id = _register(user_client, 'ada')
    _register(admin_client, 'admin')
    _promote(settings, 'admin')
    project_id = user_client.post('/api/projects', json={'name': 'Review project'}).json()['id']
    asset = ProjectRepository(SQLiteDatabase(settings.database_path)).create_asset(user_id, project_id, AssetKind.image, 'mock://image.png', 'image/png', {'source': 'test'})

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute('UPDATE assets SET metadata_json = ? WHERE id = ?', ('not-json', asset.id))

    response = admin_client.get('/api/admin/assets/review-queue')

    assert response.status_code == 200
    assert response.json()['assets'][0]['id'] == asset.id
    assert response.json()['assets'][0]['metadata'] == {}


def test_create_asset_rejects_project_owned_by_different_user(tmp_path):
    client, settings = _client(tmp_path)
    user_a_id = _register(client, 'ada')
    user_b_id = _register(client, 'grace')
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))
    project_id = repository.create_project(user_a_id, 'Owner project').id

    with pytest.raises(sqlite3.IntegrityError, match='Asset project owner mismatch'):
        repository.create_asset(user_b_id, project_id, AssetKind.image, 'mock://image.png', 'image/png', {'source': 'test'})


def test_create_task_rejects_project_owned_by_different_user(tmp_path):
    client, settings = _client(tmp_path)
    user_a_id = _register(client, 'ada')
    user_b_id = _register(client, 'grace')
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))
    project_id = repository.create_project(user_a_id, 'Owner project').id

    with pytest.raises(sqlite3.IntegrityError, match='Task project owner mismatch'):
        repository.create_task(user_b_id, project_id, TaskKind.image, {'prompt': 'test prompt'})


def test_database_initialization_removes_legacy_cross_owner_assets_and_tasks(tmp_path):
    client, settings = _client(tmp_path)
    user_a_id = _register(client, 'ada')
    user_b_id = _register(client, 'grace')
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))
    project_id = repository.create_project(user_a_id, 'Owner project').id
    invalid_asset_id = 'legacy-invalid-asset'
    invalid_task_id = 'legacy-invalid-task'

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute('DROP TRIGGER IF EXISTS trg_assets_project_owner_insert')
        connection.execute('DROP TRIGGER IF EXISTS trg_assets_project_owner_update')
        connection.execute('DROP TRIGGER IF EXISTS trg_generation_tasks_project_owner_insert')
        connection.execute('DROP TRIGGER IF EXISTS trg_generation_tasks_project_owner_update')
        connection.execute(
            """
            INSERT INTO assets (id, owner_id, project_id, kind, url, media_type, metadata_json, review_status, review_notes, reviewed_by, reviewed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (invalid_asset_id, user_b_id, project_id, 'image', 'mock://legacy-image.png', 'image/png', '{}', 'pending', '', None, None, '2026-05-21T00:00:00+00:00'),
        )
        connection.execute(
            """
            INSERT INTO generation_tasks (
                id, owner_id, project_id, kind, status, input_json, result_json, history_json, error,
                cost_estimate, charged_credits, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (invalid_task_id, user_b_id, project_id, 'image', 'pending', '{"prompt":"legacy"}', 0, 0, '2026-05-21T00:00:00+00:00', '2026-05-21T00:00:00+00:00'),
        )

    SQLiteDatabase(settings.database_path).initialize()

    with sqlite3.connect(settings.database_path) as connection:
        asset_row = connection.execute('SELECT 1 FROM assets WHERE id = ?', (invalid_asset_id,)).fetchone()
        task_row = connection.execute('SELECT 1 FROM generation_tasks WHERE id = ?', (invalid_task_id,)).fetchone()

    assert asset_row is None
    assert task_row is None


def test_admin_users_include_credit_balance(tmp_path):
    admin_client, settings = _client(tmp_path)
    user_client, _ = _client(tmp_path)
    _register(admin_client, 'admin')
    _promote(settings, 'admin')
    user_id = _register(user_client, 'ada')
    from src.services.billing_repository import BillingRepository

    BillingRepository(SQLiteDatabase(settings.database_path)).get_or_create_account(user_id, 300)

    response = admin_client.get('/api/admin/users')

    assert response.status_code == 200
    users = {item['username']: item for item in response.json()['users']}
    assert users['ada']['credit_balance'] == 300
    assert users['admin']['role'] == 'admin'


def test_admin_tasks_include_failed_errors_and_charge_fields(tmp_path):
    admin_client, settings = _client(tmp_path)
    user_client, _ = _client(tmp_path)
    _register(admin_client, 'admin')
    _promote(settings, 'admin')
    user_id = _register(user_client, 'ada')
    project_id = user_client.post('/api/projects', json={'name': 'Ops project'}).json()['id']
    repository = ProjectRepository(SQLiteDatabase(settings.database_path))
    task = repository.create_task(user_id, project_id, TaskKind.image, {'prompt': 'test'}, cost_estimate=10, charged_credits=10)
    repository.set_task_failed(task.task_id, 'provider timeout')

    response = admin_client.get('/api/admin/tasks?status=failed')

    assert response.status_code == 200
    tasks = response.json()['tasks']
    assert tasks[0]['task_id'] == task.task_id
    assert tasks[0]['error'] == 'provider timeout'
    assert tasks[0]['charged_credits'] == 10
