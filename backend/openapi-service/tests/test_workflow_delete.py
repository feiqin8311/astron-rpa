from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_user_id_with_fallback, get_workflow_service
from app.main import app
from app.schemas import ResCode
from app.services.workflow import WorkflowService


@pytest.mark.asyncio
async def test_delete_workflow_endpoint():
    mock_service = AsyncMock(spec=WorkflowService)
    mock_service.delete_workflow.return_value = True

    async def override_user():
        return "test-user-123"

    async def override_service():
        return mock_service

    app.dependency_overrides[get_user_id_with_fallback] = override_user
    app.dependency_overrides[get_workflow_service] = override_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/workflows/wf-test-001")
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == ResCode.SUCCESS.value
            assert data["data"] is True
            mock_service.delete_workflow.assert_awaited_once_with("wf-test-001", "test-user-123")
    finally:
        app.dependency_overrides.pop(get_user_id_with_fallback, None)
        app.dependency_overrides.pop(get_workflow_service, None)
