"""Deterministic readings from simulated nursery benches and two shade meshes."""

from random import Random


def demo_rows():
    rng = Random(261129)
    rows = []
    groups = [('train', 8, 12), ('holdout', 3, 12), ('pending', 2, 9)]
    for part, batches, count in groups:
        for i in range(batches):
            batch = f'{part[:2].upper()}-{i + 1:02d}'
            for j in range(count):
                mesh = 'mesh30' if j % 2 == 0 else 'mesh60'
                day_phase = (j // 2) / 5 + rng.uniform(-0.035, 0.035)
                shift = 1 if mesh == 'mesh30' else 0
                row = {'reading_id': f'{batch}-{j + 1:02d}', 'batch_id': batch,
                       'partition': part, 'shade_class': mesh,
                       'temp_c': round(16 + 12 * day_phase + 2 * shift + rng.gauss(0, 0.4), 2),
                       'rh_pct': round(81 - 30 * day_phase - 3 * shift + rng.gauss(0, 0.7), 2),
                       'par': round(120 + (455 + 340 * shift) * day_phase + rng.gauss(0, 9), 2)}
                if part == 'pending':
                    row[('temp_c', 'rh_pct', 'par')[j % 3]] = None
                    if j == 5:
                        row['temp_c'] = None
                    if j == 7:
                        row['shade_class'] = 'mesh80'
                rows.append(row)
    return rows
