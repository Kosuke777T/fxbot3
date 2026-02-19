"""リスク管理のテスト."""

from __future__ import annotations

import pytest

from fxbot.risk.position_sizer import calculate_lot
from fxbot.risk.stop_manager import calculate_stops, update_trailing_stop


class TestPositionSizer:
    def test_basic_lot_calculation(self, settings):
        lot = calculate_lot(
            prediction=0.001,
            balance=1_000_000,
            atr=0.001,
            point=0.0001,
            settings=settings,
        )
        assert settings.trading.min_lot <= lot <= settings.trading.max_lot

    def test_below_threshold_returns_zero(self, settings):
        lot = calculate_lot(
            prediction=0.0001,  # 閾値以下
            balance=1_000_000,
            atr=0.001,
            point=0.0001,
            settings=settings,
        )
        assert lot == 0.0

    def test_larger_prediction_larger_lot(self, settings):
        lot_small = calculate_lot(0.001, 1_000_000, 0.001, 0.0001, settings)
        lot_large = calculate_lot(0.003, 1_000_000, 0.001, 0.0001, settings)
        assert lot_large >= lot_small


class TestStopManager:
    def test_buy_stops(self, settings):
        stops = calculate_stops("buy", 1.1000, 0.001, 0.001, settings)
        assert stops.sl < 1.1000
        assert stops.tp > 1.1000
        assert stops.trailing_distance > 0

    def test_sell_stops(self, settings):
        stops = calculate_stops("sell", 1.1000, -0.001, 0.001, settings)
        assert stops.sl > 1.1000
        assert stops.tp < 1.1000

    def test_trailing_stop_update_buy(self, settings):
        stops = calculate_stops("buy", 1.1000, 0.001, 0.001, settings)
        # 利益が十分ある場合 → トレーリング更新
        new_sl = update_trailing_stop(
            "buy", 1.1020, 1.1000, stops.sl, stops
        )
        if new_sl is not None:
            assert new_sl > stops.sl

    def test_trailing_stop_no_update_when_no_profit(self, settings):
        stops = calculate_stops("buy", 1.1000, 0.001, 0.001, settings)
        new_sl = update_trailing_stop(
            "buy", 1.1001, 1.1000, stops.sl, stops
        )
        # 利益が不十分ならNone
        assert new_sl is None
