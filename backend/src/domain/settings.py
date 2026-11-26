"""CSV measurement fields, split names, and operator settings."""

FIELDS = {'temp_c': (-10, 65), 'rh_pct': (0, 100), 'par': (0, 3000)}
SPLITS = ('train', 'holdout', 'pending')
COLUMNS = ['reading_id', 'batch_id', 'partition', 'shade_class', *FIELDS]
PARAMETERS = [
    {'key': 'neighbors', 'label': '邻居数', 'min': 1, 'max': 25, 'default': 5, 'step': 1},
    {'key': 'min_anchors', 'label': '最低已测字段数', 'min': 1, 'max': 2, 'default': 2, 'step': 1},
    {'key': 'mask_seed', 'label': '遮挡种子', 'min': 0, 'max': 99999, 'default': 2611, 'step': 1},
]
SPEC = {
    'title': '苗圃遮阳台传感器缺测补记',
    'dataset_name': '河桥苗圃遮阳台 11 月测次合集',
    'columns': COLUMNS,
    'settings': PARAMETERS,
    'description': '按遮阳网档位仅使用冻结训练批，比较 KNN 插补与同档中位数。',
    'partitions': list(SPLITS),
    'units': {'temp_c': '°C', 'rh_pct': '%', 'par': 'µmol/m²/s'},
}


def parse_options(values):
    settings = {}
    if set(values) - {param['key'] for param in PARAMETERS}:
        raise ValueError('出现未定义的插补参数')
    for param in PARAMETERS:
        key = param['key']
        value = values.get(key, param['default'])
        if type(value) not in (int, float) or not param['min'] <= value <= param['max'] or int(value) != value:
            raise ValueError(f'{key} 必须为范围内的整数')
        settings[key] = int(value)
    return settings
