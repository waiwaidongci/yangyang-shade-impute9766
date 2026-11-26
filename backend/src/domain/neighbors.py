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
    required: int
    withdrawn: tuple = ()

    @property
    def usable(self):
        """A class needs at least ``required`` retained rows to solve a neighbourhood."""
        return len(self.rows) >= self.required


@dataclass
class Estimate:
    value: float | None
    donors: int
    nearest: float | None
    reason: str


def fit_reference(rows, k, withdrawn=None, known_classes=()):
    """Freeze per-class scales, medians and donors over the retained training rows.

    ``known_classes`` covers classes whose every training batch was withdrawn, so the
    handover sheet can still report an actionable manual re-measurement reason.
    """
    withdrawn = withdrawn or {}
    groups = defaultdict(list)
    for row in rows:
        groups[row['shade_class']].append(row)
    references = {}
    for key in sorted(set(groups) | set(known_classes)):
        members = groups.get(key, [])
        if members:
            columns = {field: [row[field] for row in members] for field in FIELDS}
            scales = {field: pstdev(values) for field, values in columns.items()}
            medians = {field: median(values) for field, values in columns.items()}
        else:
            scales = {field: None for field in FIELDS}
            medians = {field: None for field in FIELDS}
        references[key] = Reference(members, scales, medians, k, tuple(sorted(set(withdrawn.get(key, ())))))
    return references


def predict(row, target, references, k, min_anchors):
    reference = references.get(row['shade_class'])
    if reference is None:
        return Estimate(None, 0, None, '同档训练读数不足：该档没有训练批，已改派人工补测')
    if not reference.usable:
        context = f'撤回训练批 {"、".join(reference.withdrawn)} 后' if reference.withdrawn else ''
        return Estimate(None, 0, None,
                        f'同档训练读数不足：{context}可用训练读数 {len(reference.rows)} 条，'
                        f'至少需要 {reference.required} 条，已改派人工补测')
    anchors = [field for field in FIELDS if field != target and row[field] is not None
               and reference.scales[field] > 0]
    if len(anchors) < min_anchors:
        return Estimate(None, 0, None, '有效已测字段不足，已改派人工补测')
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
