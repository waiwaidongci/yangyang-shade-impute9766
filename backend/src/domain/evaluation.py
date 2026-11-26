"""Hide one field per held-out reading and score matched baseline cells."""

from random import Random
from statistics import mean

from .neighbors import predict
from .settings import FIELDS


def evaluate(rows, references, options):
    if len(rows) < len(FIELDS):
        raise ValueError('至少需要 3 条完整的独立留出读数')
    shuffled = sorted(rows, key=lambda row: row['reading_id'])
    Random(options['mask_seed']).shuffle(shuffled)
    details = []
    keys = tuple(FIELDS)
    for i, original in enumerate(shuffled):
        target = keys[i % len(keys)]
        masked = {**original, target: None}
        candidate = predict(masked, target, references, options['neighbors'], options['min_anchors'])
        reference = references.get(masked['shade_class'])
        baseline = reference.medians[target] if candidate.value is not None and reference is not None else None
        details.append({'reading_id': original['reading_id'], 'batch_id': original['batch_id'],
                        'field': target, 'actual': original[target], 'predicted': candidate.value,
                        'baseline': baseline, 'reason': candidate.reason})
    scores = []
    for key in keys:
        attempts = [row for row in details if row['field'] == key]
        paired = [row for row in attempts if row['predicted'] is not None]
        scores.append({'field': key, 'attempted': len(attempts), 'compared': len(paired),
                       'knn_mae': mean(abs(row['actual'] - row['predicted']) for row in paired) if paired else None,
                       'median_mae': mean(abs(row['actual'] - row['baseline']) for row in paired) if paired else None})
    return details, scores
