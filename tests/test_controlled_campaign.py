"""Admission, completion-order halts and draining use actual controller callbacks."""
import asyncio
import importlib.util

import pytest

from aeread.shared_runner.run.halt import CellOutcome
from aeread.shared_runner.task.spend import AttemptSpend


def api():
    assert importlib.util.find_spec('aeread.shared_runner.run.controlled_campaign'), 'controlled campaign entry missing'
    from aeread.shared_runner.run import controlled_campaign
    return controlled_campaign


def spend(cost=0, lower=False):
    return AttemptSpend(cost, 'lower_bound' if lower else 'exact', 0, 0, 0, 1, int(lower))


def test_account_fault_drains_inflight_before_summary_and_never_dispatches_queue():
    m = api()
    async def run():
        b_started = asyncio.Event()
        calls, persisted = [], []
        async def execute(cell):
            calls.append(cell.cell_key)
            if cell.cell_key == 'A':
                await b_started.wait()
                return m.CellResult('attempted_failure', {'receipt_sha256': 'a'}, spend(.01), CellOutcome(True, 'account_fault'))
            b_started.set()
            await asyncio.sleep(.01)
            return m.CellResult('attempted_failure', {'receipt_sha256': 'b'}, spend(.03, True), CellOutcome(True, 'timeout'))
        async def persist(cell, result):
            persisted.append(cell.cell_key)
        try:
            result = await m.run_controlled_cells([m.PlannedCell(k, 'first' if k < 'C' else 'zero') for k in 'ABCD'], execute, controls=m.CampaignControls(1, .1, 2, 3), persist=persist)
        except asyncio.CancelledError:
            assert False, 'controller cancelled in-flight B before its charged result was persisted'
        assert calls == ['A', 'B'] and persisted == ['A', 'B']
        assert result.spend.cost_usd == .04 and result.spend.cost_accounting == 'lower_bound'
        assert result.spend.unsettled_call_count == 1
        assert result.halt['condition'] == 'halted_on_account_fault'
        assert result.halt['in_flight_at_trigger'] == ['B']
        assert result.halt['not_started_keys'] == ['C', 'D']
        assert [c.cell_key for c in result.not_attempted] == ['C', 'D']
    asyncio.run(run())


def test_reserves_are_not_charges_and_persistence_precedes_next_admission():
    m = api()
    async def run():
        order = []
        async def execute(cell):
            order.append('execute' + cell.cell_key)
            return m.CellResult('completed', {'receipt_sha256': 'r'}, spend(.03), CellOutcome(False))
        def persist(cell, result):
            order.append('persist' + cell.cell_key)
        result = await m.run_controlled_cells([m.PlannedCell(k, k) for k in 'ABC'], execute, controls=m.CampaignControls(.08, .05, 1, 3), persist=persist)
        assert order == ['executeA', 'persistA', 'executeB', 'persistB']
        assert result.spend.cost_usd == .06
        assert result.halt['condition'] == 'campaign_cost_reserve_reached'
        assert [c.cell_key for c in result.not_attempted] == ['C']
    asyncio.run(run())


def test_streak_resets_on_success_in_completion_order():
    m = api()
    async def run():
        async def execute(cell):
            failed = cell.cell_key != 'B'
            return m.CellResult('attempted_failure' if failed else 'completed', {'receipt_sha256': 'r'}, spend(), CellOutcome(failed, 'transport' if failed else None))
        result = await m.run_controlled_cells([m.PlannedCell(k, k) for k in 'ABCDE'], execute, controls=m.CampaignControls(1, .1, 1, 2), persist=lambda *_: None)
        assert [c.cell_key for c, _ in result.results] == list('ABCD')
        assert result.halt['after_cell'] == 'D'
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['callback', 'persist', 'cancel'])
def test_unexpected_error_and_cancellation_drain_active_callbacks(failure):
    m = api()
    async def run():
        began, release = asyncio.Event(), asyncio.Event()
        completed, calls = [], []
        async def execute(cell):
            calls.append(cell.cell_key)
            if cell.cell_key == 'A':
                await began.wait()
                if failure == 'callback':
                    release.set()
                    raise RuntimeError('callback broke')
                return m.CellResult('completed', {'receipt_sha256': 'a'}, spend(), CellOutcome(False))
            began.set()
            if failure == 'cancel':
                await asyncio.sleep(.02)
            else:
                await release.wait()
            completed.append('B')
            return m.CellResult('completed', {'receipt_sha256': 'b'}, spend(.2), CellOutcome(False))
        def persist(cell, result):
            if cell.cell_key == 'A' and failure == 'persist':
                release.set()
                raise OSError('disk broke')
        task = asyncio.create_task(m.run_controlled_cells([m.PlannedCell(k, k) for k in 'ABC'], execute, controls=m.CampaignControls(2, .1, 2, 3), persist=persist))
        if failure == 'cancel':
            await began.wait()
            task.cancel()
        with pytest.raises({'callback': RuntimeError, 'persist': OSError, 'cancel': asyncio.CancelledError}[failure]):
            await task
        assert completed == ['B'] and calls == ['A', 'B']
    asyncio.run(run())


def test_duplicate_plans_and_invalid_control_rejected_before_execution():
    m = api()
    for args in [(True, .1, 1, 2), (1, float('nan'), 1, 2), (1, .1, 0, 2)]:
        with pytest.raises(ValueError):
            m.CampaignControls(*args)
    with pytest.raises(ValueError, match='unique'):
        asyncio.run(m.run_controlled_cells([m.PlannedCell('A', 'x')]*2, lambda _: pytest.fail(), controls=m.CampaignControls(1,.1,1,2), persist=lambda *_: None))


def test_already_finished_fault_is_observed_before_replacement_dispatch():
    m = api()
    async def run():
        calls = []
        async def execute(cell):
            calls.append(cell.cell_key)
            failed = cell.cell_key == 'B'
            return m.CellResult('attempted_failure' if failed else 'completed', {'receipt_sha256': 'r'}, spend(), CellOutcome(failed, 'account_fault' if failed else None))
        result = await m.run_controlled_cells([m.PlannedCell(k, k) for k in 'ABCD'], execute, controls=m.CampaignControls(1, .1, 2, 3), persist=lambda *_: None)
        assert calls == ['A', 'B']
        assert result.halt['after_cell'] == 'B'
    asyncio.run(run())


def test_malformed_callback_results_propagate_without_dispatching_queue():
    m = api()
    async def run():
        async def execute(cell):
            return {'status': 'completed', 'receipt_sha256': 'invented'}
        with pytest.raises(TypeError, match='CellResult'):
            await m.run_controlled_cells([m.PlannedCell('A','arm')], execute, controls=m.CampaignControls(1,.1,1,3), persist=lambda *_: pytest.fail('malformed result persisted'))
    asyncio.run(run())
