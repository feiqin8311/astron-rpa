from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.config import Settings
from app.dependencies import get_user_id_from_header
from app.dependencies.points import PointChecker, PointsContext
from app.services.point import PointTransactionType


@pytest.mark.asyncio
async def test_point_checker_billing_disabled():
    # When ENABLE_BILLING is False, check should pass and deduct_points should be a no-op
    with patch("app.dependencies.points.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ENABLE_BILLING=False)

        checker = PointChecker(points_cost=100, transaction_type=PointTransactionType.AICHAT_COST)
        context = await checker(current_user_id="test-user", userpoints_service=None)

        assert isinstance(context, PointsContext)
        assert context.billing_enabled is False
        assert context.user_id == "test-user"

        # Calling deduct_points must succeed without calling any service
        deducted = await context.deduct_points()
        assert deducted is True


@pytest.mark.asyncio
async def test_point_checker_billing_enabled_sufficient():
    # When ENABLE_BILLING is True, points should be checked and deducted
    with patch("app.dependencies.points.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ENABLE_BILLING=True)

        mock_service = MagicMock()
        mock_service.grant_monthly_points = AsyncMock()
        mock_service.get_cached_points = AsyncMock(return_value=500)
        mock_service.deduct_points = AsyncMock()

        checker = PointChecker(points_cost=100, transaction_type=PointTransactionType.AICHAT_COST)
        context = await checker(current_user_id="test-user", userpoints_service=mock_service)

        assert context.billing_enabled is True
        mock_service.grant_monthly_points.assert_awaited_once_with("test-user")
        mock_service.get_cached_points.assert_awaited_once_with("test-user")

        await context.deduct_points()
        mock_service.deduct_points.assert_awaited_once_with(
            user_id="test-user", amount=100, transaction_type=PointTransactionType.AICHAT_COST
        )


def test_user_id_fallback_when_billing_disabled():
    with patch("app.dependencies.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ENABLE_BILLING=False)

        # When headers are omitted, fall back to "local-user" in open-source mode
        user_id = get_user_id_from_header(x_user_id=None, user_id=None)
        assert user_id == "local-user"
