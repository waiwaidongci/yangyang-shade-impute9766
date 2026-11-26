"""Run the nursery sensor imputation workflow on one validated dataset."""

from .evaluation import evaluate
from .fixtures import demo_rows
from .neighbors import fit_reference
from .records import normalize_rows
from .reports import assemble, handover
from .settings import SPEC, parse_options

__all__ = ['SPEC', 'analyze', 'demo_rows', 'normalize_rows']


def analyze(rows, settings):
    options = parse_options(settings)
    rows = normalize_rows(rows)
    training = [row for row in rows if row['partition'] == 'train']
    holdout = [row for row in rows if row['partition'] == 'holdout']
    pending = [row for row in rows if row['partition'] == 'pending']
    references = fit_reference(training, options['neighbors'])
    details, scores = evaluate(holdout, references, options)
    cells = handover(pending, references, options)
    return assemble(cells, details, scores, references)
