from fastapi.responses import Response

from src.services.reviews import review_info
from src.services.runs import delivery_state, export_table, get_run, run_info
from src.utils.csv_files import write_rows


def report_detail(session, run_id, actor):
    run, review = get_run(session, run_id, actor)
    delivery = delivery_state(session, run) if run.result else {}
    return {**run_info(run, review, delivery), 'result': run.result, 'error': run.error,
            'review': review_info(review) if review else None}


def report_csv(session, run_id, key, actor, shade_class=None):
    table, blocked = export_table(session, run_id, key, actor, shade_class)
    headers = {'Content-Disposition': f'attachment; filename="run-{run_id}-{table["key"]}.csv"'}
    if blocked:
        headers['X-Withheld-Shade-Classes'] = ','.join(blocked)
    return Response(write_rows(table['columns'], table['rows']), media_type='text/csv', headers=headers)
