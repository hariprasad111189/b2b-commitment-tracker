from datetime import datetime
from zoneinfo import ZoneInfo
from app.schemas import InvoiceRecord

IST = ZoneInfo("Asia/Kolkata")


def get_mock_invoices() -> list[InvoiceRecord]:
    return [
        InvoiceRecord(invoice_id="INV-7001", client_name="Meridian Logistics Pvt Ltd", amount_due=125000.00,
                      currency="INR", due_date=datetime(2026, 9, 12, tzinfo=IST), issued_date=datetime(2026, 8, 12, tzinfo=IST)),
        InvoiceRecord(invoice_id="INV-7002", client_name="Brightline Consulting", amount_due=48000.00,
                      currency="INR", due_date=datetime(2026, 9, 15, tzinfo=IST), issued_date=datetime(2026, 8, 15, tzinfo=IST)),
        InvoiceRecord(invoice_id="INV-7003", client_name="Aster Healthcare Systems", amount_due=310000.00,
                      currency="INR", due_date=datetime(2026, 9, 5, tzinfo=IST), issued_date=datetime(2026, 8, 5, tzinfo=IST)),
        InvoiceRecord(invoice_id="INV-7004", client_name="Northwind Manufacturing", amount_due=150000.00,
                      currency="INR", due_date=datetime(2026, 9, 18, tzinfo=IST), issued_date=datetime(2026, 8, 18, tzinfo=IST)),
        InvoiceRecord(invoice_id="INV-7005", client_name="Solace Interior Studio", amount_due=92500.00,
                      currency="INR", due_date=datetime(2026, 9, 8, tzinfo=IST), issued_date=datetime(2026, 8, 8, tzinfo=IST)),
        InvoiceRecord(invoice_id="INV-9001", client_name="Test Live Client", amount_due=50000.00,
                        currency="INR", due_date=datetime(2026, 9, 20, tzinfo=IST), issued_date=datetime(2026, 8, 20, tzinfo=IST)),
    ]
    
   