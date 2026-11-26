from fastapi import APIRouter

from src.controllers.dependencies import Db, Writer
from src.schemas.withdrawals import WithdrawalCreate, WithdrawalInfo
from src.services import withdrawals

router = APIRouter(prefix='/datasets')


@router.get('/{dataset_id}/withdrawals', response_model=list[WithdrawalInfo])
def list_withdrawals(dataset_id: int, session: Db, actor: Writer):
    return withdrawals.list_withdrawals(session, dataset_id)


@router.post('/{dataset_id}/withdrawals', response_model=WithdrawalInfo, status_code=201)
def register(dataset_id: int, payload: WithdrawalCreate, session: Db, actor: Writer):
    return withdrawals.withdraw(session, dataset_id, payload, actor)
