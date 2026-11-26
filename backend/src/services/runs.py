import math

from fastapi import HTTPException
from sqlalchemy import select

from src.constants.workflow import Decision, Role, RunStatus
from src.domain.project import SPEC
from src.domain.withdrawals import status
from src.models.dataset import Dataset
from src.models.review import Review
from src.models.run import Run
from src.services.audit import record
from src.services.catalog import get_dataset
from src.services.queue import notify_worker
from src.services.withdrawals import current_state
from src.utils.time import utc_stamp


def applied_state(run):
    return (run.result or {}).get('withdrawals', {})


def delivery_state(session, run):
    if not run.result:
        return {}
    dataset = session.get(Dataset, run.dataset_id)
    applied = applied_state(run)
    current = current_state(session, dataset)
    blocked = status(applied, current)
    state = {}
    for shade in sorted({row['shade_class'] for row in dataset.rows if row['partition'] == 'pending'}):
        state[shade] = blocked.get(shade) or {
            'applied_withdrawals': applied.get(shade, []),
            'current_withdrawals': current.get(shade, []),
            'deliverable': True, 'reason': None}
    state.update({shade: item for shade, item in blocked.items() if shade not in state})
    return state


def run_info(run, review, delivery=None):
    fields = ('id', 'label', 'dataset_id', 'created_at', 'status', 'settings')
    delivery = delivery or {}
    return {**{key: getattr(run, key) for key in fields}, 'decision': review.decision if review else None,
            'withdrawals': {shade: item['current_withdrawals'] for shade, item in delivery.items()
                            if item['current_withdrawals']},
            'delivery': delivery,
            'deliverable': all(item['deliverable'] for item in delivery.values()) if delivery else None}


def list_runs(session, actor):
    statement = select(Run, Review).outerjoin(Review, Run.id == Review.run_id).order_by(Run.id.desc()).limit(100)
    if actor.role == Role.VIEWER:
        statement = statement.where(Review.decision == Decision.APPROVED)
    return [run_info(run, review, delivery_state(session, run) if run.result else {})
            for run, review in session.execute(statement)]


def get_run(session, run_id, actor):
    run = session.get(Run, run_id)
    review = session.get(Review, run_id)
    if run is None or (actor.role == Role.VIEWER and (not review or review.decision != Decision.APPROVED)):
        raise LookupError('找不到可查看的运行')
    return run, review


def validate_settings(settings):
    parameters = {item['key']: item for item in SPEC['settings']}
    if settings.keys() - parameters.keys():
        raise ValueError('存在本项目未定义的运行参数')
    checked = {}
    for key, parameter in parameters.items():
        value = settings.get(key, parameter['default'])
        if not math.isfinite(value) or not parameter['min'] <= value <= parameter['max']:
            raise ValueError(f"{parameter['label']}超出范围")
        if parameter['step'] == 1 and value != int(value):
            raise ValueError(f"{parameter['label']}必须是整数")
        checked[key] = int(value) if parameter['step'] == 1 else value
    return checked


def create_run(session, payload, actor):
    get_dataset(session, payload.dataset_id)
    run = Run(label=payload.label, dataset_id=payload.dataset_id, created_by=actor.id,
              created_at=utc_stamp(), status=RunStatus.QUEUED, settings=validate_settings(payload.settings))
    session.add(run)
    session.flush()
    record(session, 'run.queued', run.id, actor.id)
    session.commit()
    notify_worker()
    return run_info(run, None, {})


def export_table(session, run_id, key, actor, shade_class=None):
    run, review = get_run(session, run_id, actor)
    if review is None or review.decision != Decision.APPROVED:
        raise HTTPException(409, '复核通过后可下载正式 CSV')
    table = next((item for item in run.result['tables'] if item['key'] == key), None)
    if table is None:
        raise LookupError('找不到结果表')
    delivery = delivery_state(session, run)
    if not delivery:
        return table, []
    blocked = sorted(shade for shade, state in delivery.items() if not state['deliverable'])
    if shade_class is not None:
        state = delivery.get(shade_class)
        if state is not None and not state['deliverable']:
            raise HTTPException(409, state['reason'])
        if 'shade_class' not in table['columns']:
            raise HTTPException(409, '该表按字段汇总，无法只导出单档；请待该档重新计算完成后下载')
        if not any(row.get('shade_class') == shade_class for row in table['rows']):
            raise LookupError(f'结果表中没有遮阳网档位 {shade_class}')
        rows = [row for row in table['rows'] if row.get('shade_class') == shade_class]
        return {**table, 'rows': rows}, blocked
    if 'shade_class' in table['columns']:
        # Unaffected classes keep downloading the shift sheet normally.
        rows = [row for row in table['rows'] if row.get('shade_class') not in blocked]
        if not rows:
            raise HTTPException(409, '该档旧建议已停发：' + (delivery[blocked[0]]['reason'] if blocked
                                                        else '暂无可下载档位'))
        return {**table, 'rows': rows}, blocked
    if blocked:
        raise HTTPException(409, '该表涉及全部档位，已停发的档位需等重新计算完成后再下载')
    return table, blocked
