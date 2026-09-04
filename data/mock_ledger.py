from datetime import datetime
from zoneinfo import ZoneInfo
from app.schemas import LedgerEntry, SettlementStatus

IST = ZoneInfo("Asia/Kolkata")


def get_mock_ledger() -> list[LedgerEntry]:
    return [
        LedgerEntry(invoice_id="INV-7001", amount_settled=0.0, status=SettlementStatus.PENDING),
        LedgerEntry(invoice_id="INV-7002", amount_settled=24000.0,
                    settlement_date=datetime(2026, 9, 1, tzinfo=IST), status=SettlementStatus.PARTIAL),
        LedgerEntry(invoice_id="INV-7003", amount_settled=0.0, status=SettlementStatus.PENDING),
        # Customer will claim already paid — ledger disagrees. This is the intentional contradiction case.
        LedgerEntry(invoice_id="INV-7004", amount_settled=0.0, status=SettlementStatus.PENDING),
        LedgerEntry(invoice_id="INV-7005", amount_settled=0.0, status=SettlementStatus.PENDING),
        
        LedgerEntry(invoice_id="INV-9001", amount_settled=0.0, status=SettlementStatus.PENDING),
    ]