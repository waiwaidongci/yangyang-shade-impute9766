"""Track withdrawn training batches and per-shade-class recomputation state.

A withdrawal always removes a whole batch. Every shade class that had training
readings in that batch must be recomputed -- even when none of those rows were
selected as neighbours, because the frozen scales and medians change.
"""


def affected_classes(rows, batch_ids):
    wanted = set(batch_ids)
    return sorted({row['shade_class'] for row in rows if row['batch_id'] in wanted})


def state_for(rows, batch_ids):
    """Map each shade class with withdrawn training readings to the withdrawn batches."""
    wanted = set(batch_ids)
    state = {}
    for row in rows:
        if row['partition'] == 'train' and row['batch_id'] in wanted:
            state.setdefault(row['shade_class'], set()).add(row['batch_id'])
    return {key: sorted(value) for key, value in sorted(state.items())}


def retained(rows, batch_ids):
    wanted = set(batch_ids)
    return [row for row in rows if row['batch_id'] not in wanted]


def status(applied, current):
    """Per-class delivery status.

    A class resumes only when the run applied exactly the withdrawals that are
    currently registered for that class. A run that excluded only an earlier
    batch therefore stays blocked even when it finishes later.
    """
    statuses = {}
    for key in sorted(set(applied or {}) | set(current or {})):
        used = sorted(set((applied or {}).get(key, [])))
        now = sorted(set((current or {}).get(key, [])))
        missing = [batch for batch in now if batch not in used]
        restored = [batch for batch in used if batch not in now]
        if not missing and not restored:
            continue
        if missing:
            reason = ('该档旧建议已停发：训练批 ' + '、'.join(missing)
                      + ' 尚未纳入本次计算，等待重新计算')
        else:
            reason = '该档计算依据的训练批已恢复，等待按当前台账重新计算'
        statuses[key] = {'applied_withdrawals': used, 'current_withdrawals': now,
                         'deliverable': False, 'reason': reason}
    return statuses
