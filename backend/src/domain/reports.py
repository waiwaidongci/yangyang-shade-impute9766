"""Generate per-cell handover items, preparation statistics, and tabular evidence."""

from .neighbors import predict
from .settings import FIELDS


def make_table(key, title, columns, rows):
    data = [{name: round(value, 6) if isinstance(value, float) else value
             for name, value in row.items()} for row in rows]
    return {'key': key, 'title': title, 'columns': columns, 'rows': data}


def handover(rows, references, options):
    cells = []
    for row in rows:
        for field in FIELDS:
            if row[field] is not None:
                continue
            guess = predict(row, field, references, options['neighbors'], options['min_anchors'])
            cells.append({'reading_id': row['reading_id'], 'batch_id': row['batch_id'], 'field': field,
                          'shade_class': row['shade_class'], 'proposed_value': guess.value,
                          'donors': guess.donors, 'nearest_distance': guess.nearest, 'reason': guess.reason})
    return cells


def assemble(cells, details, scores, references):
    ready = sum(row['proposed_value'] is not None for row in cells)
    compared = sum(row['compared'] for row in scores)
    frozen = [{'shade_class': shade, 'field': field, 'training_rows': len(ref.rows),
               'training_scale': ref.scales[field], 'training_median': ref.medians[field]}
              for shade, ref in sorted(references.items()) for field in FIELDS]
    return {
        'summary': f'{len(details)} 个留出读数单元完成遮挡，其中 {compared} 个可进行同口径对比。'
                   f'{len(cells)} 个待补单元中，{ready} 个有建议值，{len(cells)-ready} 个需人工补测。',
        'metrics': {'留出遮挡单元': len(details), '有效配对覆盖率': round(compared / len(details), 6),
                    '可建议单元': ready, '待人工补测单元': len(cells) - ready},
        'warnings': ['遮挡回测评估单字段随机缺测，设备断连造成的多列缺测可能没有足够近邻。'],
        'tables': [
            make_table('missing_cells', '缺测建议交班', ['reading_id', 'batch_id', 'field', 'shade_class',
                       'proposed_value', 'donors', 'nearest_distance', 'reason'], cells),
            make_table('holdout_mae', '分字段遮挡误差', ['field', 'attempted', 'compared', 'knn_mae', 'median_mae'], scores),
            make_table('masked_holdout', '留出遮挡明细', ['reading_id', 'batch_id', 'field', 'actual',
                       'predicted', 'baseline', 'reason'], details),
            make_table('frozen_reference', '训练尺度与基准', ['shade_class', 'field', 'training_rows',
                       'training_scale', 'training_median'], frozen),
        ],
    }
