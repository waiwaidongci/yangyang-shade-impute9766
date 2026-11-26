"""Run the nursery sensor imputation workflow on one validated dataset."""

from .evaluation import evaluate
from .fixtures import demo_rows
from .neighbors import fit_reference
from .records import normalize_rows
from .reports import assemble, handover
from .settings import SPEC, parse_options
from .withdrawals import retained

__all__ = ['SPEC', 'analyze', 'demo_rows', 'normalize_rows']


def analyze(rows, settings, withdrawn=None):
    """Compute on the retained readings and report the withdrawals that shaped it."""
    options = parse_options(settings)
    rows = normalize_rows(rows)
    withdrawn = {shade: sorted(batches) for shade, batches in (withdrawn or {}).items() if batches}
    dropped = {batch for batches in withdrawn.values() for batch in batches}
    rows = retained(rows, dropped)
    training = [row for row in rows if row['partition'] == 'train']
    holdout = [row for row in rows if row['partition'] == 'holdout']
    pending = [row for row in rows if row['partition'] == 'pending']
    known = {row['shade_class'] for row in rows if row['partition'] == 'train'} | set(withdrawn)
    references = fit_reference(training, options['neighbors'], withdrawn, known)
    details, scores = evaluate(holdout, references, options)
    cells = handover(pending, references, options)
    return assemble(cells, details, scores, references, withdrawn)
