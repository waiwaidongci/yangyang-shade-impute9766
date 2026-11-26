"""Register whole-batch training withdrawals and derive per-class state."""

from fastapi import HTTPException
from sqlalchemy import select

from src.domain.records import identifier
from src.domain.withdrawals import affected_classes, state_for
from src.models.withdrawal import Withdrawal
from src.services.audit import record
from src.services.catalog import get_dataset
from src.utils.time import utc_stamp


def withdrawn_batches(session, dataset_id):
    return sorted(session.scalars(
        select(Withdrawal.batch_id).where(Withdrawal.dataset_id == dataset_id)))


def current_state(session, dataset):
    return state_for(dataset.rows, withdrawn_batches(session, dataset.id))


def withdrawal_info(dataset, item):
    return {'id': item.id, 'dataset_id': item.dataset_id, 'batch_id': item.batch_id,
            'reason': item.reason, 'created_at': item.created_at,
            'affected_classes': affected_classes(dataset.rows, [item.batch_id])}


def list_withdrawals(session, dataset_id):
    dataset = get_dataset(session, dataset_id)
    items = session.scalars(select(Withdrawal).where(Withdrawal.dataset_id == dataset_id)
                            .order_by(Withdrawal.id))
    return [withdrawal_info(dataset, item) for item in items]


def withdraw(session, dataset_id, payload, actor):
    dataset = get_dataset(session, dataset_id)
    batch_id = identifier(payload.batch_id, 'batch_id')
    batch_rows = [row for row in dataset.rows if row['batch_id'] == batch_id]
    if not batch_rows:
        raise ValueError(f'训练批 {batch_id} 不在该台账中')
    if any(row['partition'] != 'train' for row in batch_rows):
        raise ValueError(f'批 {batch_id} 不是训练批，只能整批撤回训练读数')
    existing = session.scalar(select(Withdrawal).where(Withdrawal.dataset_id == dataset_id,
                                                       Withdrawal.batch_id == batch_id))
    if existing is not None:
        raise HTTPException(409, f'训练批 {batch_id} 已撤回，无需重复登记')
    item = Withdrawal(dataset_id=dataset_id, batch_id=batch_id, reason=payload.reason.strip(),
                      created_by=actor.id, created_at=utc_stamp())
    session.add(item)
    record(session, 'withdrawal.registered', dataset_id, actor.id)
    session.commit()
    return withdrawal_info(dataset, item)
