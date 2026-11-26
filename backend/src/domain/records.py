"""Validate physical limits and keep complete reference and holdout batches disjoint."""

import math
import re

from .settings import COLUMNS, FIELDS, SPLITS


def identifier(value, context):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}', value):
        raise ValueError(f'{context} 必须为 1–40 位字母、数字或编号符号')
    return value


def measurement(raw, bounds, context):
    if raw is None or raw == '':
        return None
    try:
        if isinstance(raw, bool):
            raise ValueError
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{context} 必须是数值或留空') from error
    if not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
        raise ValueError(f'{context} 超出仪器量程 {bounds}')
    return 0.0 if value == 0 else value


def normalize_rows(rows):
    accepted = []
    ids = set()
    batches = {}
    for number, raw in enumerate(rows, 1):
        if set(raw) != set(COLUMNS):
            raise ValueError(f'第 {number} 条读数的字段与规范不一致')
        reading = identifier(raw['reading_id'], f'第 {number} 行 reading_id')
        batch = identifier(raw['batch_id'], f'{reading} batch_id')
        shade = identifier(raw['shade_class'], f'{reading} shade_class')
        split = raw['partition']
        if split not in SPLITS or batches.setdefault(batch, split) != split:
            raise ValueError(f'{reading} 分区错误或同一批跨分区')
        if reading in ids:
            raise ValueError(f'读数编号重复 {reading}')
        ids.add(reading)
        features = {key: measurement(raw[key], bounds, f'{reading} {key}') for key, bounds in FIELDS.items()}
        if split != 'pending' and any(value is None for value in features.values()):
            raise ValueError(f'{reading} 的训练与留出读数必须齐全')
        accepted.append({'reading_id': reading, 'batch_id': batch, 'partition': split,
                         'shade_class': shade, **features})
    if not accepted:
        raise ValueError('测次表没有数据')
    return accepted
