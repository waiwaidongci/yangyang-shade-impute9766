"""Use frozen same-mesh training donors with standardized observed coordinates."""

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from statistics import median, pstdev

from .settings import FIELDS


@dataclass
class Reference:
    rows: list
    scales: dict
    medians: dict


@dataclass
class Estimate:
    value: float | None
    donors: int
    nearest: float | None
    reason: str


def fit_reference(rows, k):
    groups = defaultdict(list)
    for row in rows:
        groups[row['shade_class']].append(row)
    if not groups:
        raise ValueError('缺少训练批')
    references = {}
    for key, members in groups.items():
        columns = {field: [row[field] for row in members] for field in FIELDS}
        if len(members) >= k:
            references[key] = Reference(members, {field: pstdev(values) for field, values in columns.items()},
                                        {field: median(values) for field, values in columns.items()})
    if not references:
        raise ValueError('没有遮阳网档位达到所选邻居数')
    return references


def predict(row, target, references, k, min_anchors):
    reference = references.get(row['shade_class'])
    if reference is None:
        return Estimate(None, 0, None, '同档训练读数不足')
    anchors = [field for field in FIELDS if field != target and row[field] is not None
               and reference.scales[field] > 0]
    if len(anchors) < min_anchors:
        return Estimate(None, 0, None, '有效已测字段不足')
    distances = []
    for donor in reference.rows:
        squared = [(row[field] - donor[field]) ** 2 / reference.scales[field] ** 2 for field in anchors]
        distances.append((sqrt(sum(squared) / len(squared)), donor['reading_id'], donor[target]))
    distances.sort()
    if distances[0][0] == 0:
        chosen = [neighbor for neighbor in distances if neighbor[0] == 0]
        estimate = sum(neighbor[2] for neighbor in chosen) / len(chosen)
    else:
        chosen = distances[:k]
        # Relative inverse distances avoid overflow for very close donors.
        shortest = distances[0][0]
        weights = [shortest / distance for distance, _, _ in chosen]
        estimate = sum(weight * donor[2] for weight, donor in zip(weights, chosen)) / sum(weights)
    return Estimate(estimate, len(chosen), chosen[0][0], '')
