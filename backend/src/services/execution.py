import json
import logging

from sqlalchemy import select, update

from src.config.database import Session
from src.constants.workflow import RunStatus
from src.domain.project import analyze
from src.models.dataset import Dataset
from src.models.run import Run
from src.services.audit import record
from src.services.withdrawals import current_state


def recover_jobs():
    with Session.begin() as session:
        session.execute(update(Run).where(Run.status == RunStatus.RUNNING).values(status=RunStatus.QUEUED))


def claim():
    with Session.begin() as session:
        run = session.scalar(select(Run).where(Run.status == RunStatus.QUEUED)
                             .order_by(Run.id).limit(1).with_for_update(skip_locked=True))
        if run is None:
            return None
        run.status = RunStatus.RUNNING
        dataset = session.get(Dataset, run.dataset_id)
        record(session, 'run.started', run.id)
        return run.id, dataset.id, dataset.rows, run.settings, current_state(session, dataset)


def compute_latest(dataset_id, rows, settings, applied):
    """Compute and keep recomputing while newer withdrawals land, so a late
    withdrawal is always reflected in the result even mid-recalculation."""
    for _ in range(5):
        result = analyze(rows, settings, applied)
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        with Session.begin() as session:
            current = current_state(session, session.get(Dataset, dataset_id))
        if current == applied:
            return result, applied
        applied = current
    raise ValueError('撤回登记仍在变动，请待台账稳定后重新提交插补')


def store(run_id, dataset_id, result, error_message):
    """Persist the outcome only while the withdrawal ledger still matches the
    result. A withdrawal that lands during this final write forces a retry."""
    with Session.begin() as session:
        run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        current = current_state(session, session.get(Dataset, dataset_id))
        applied = (result or {}).get('withdrawals', {})
        if error_message is None and applied != current:
            return False
        run.status = RunStatus.FAILED if error_message is not None else RunStatus.COMPLETED
        run.result = result
        run.error = error_message
        record(session, 'run.' + run.status, run.id)
        return True


def execute(job):
    run_id, dataset_id, rows, settings, applied = job
    for _ in range(3):
        try:
            result, applied = compute_latest(dataset_id, rows, settings, applied)
        except ValueError as error:
            result, error_message = None, str(error)
        except Exception:
            logging.getLogger(__name__).exception('计算运行 %s 失败', run_id)
            result, error_message = None, '计算遇到内部错误，请检查台账后重试。'
        else:
            error_message = None
        if store(run_id, dataset_id, result, error_message):
            return
    with Session.begin() as session:
        run = session.get(Run, run_id)
        run.status = RunStatus.FAILED
        run.result = None
        run.error = '撤回登记变动频繁，本次结果未落地，请稍后重新提交插补'
        record(session, 'run.' + run.status, run.id)
