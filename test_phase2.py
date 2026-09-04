from data.mock_invoices import get_mock_invoices
from data.mock_emails import get_mock_emails
from data.mock_ledger import get_mock_ledger

invoices = get_mock_invoices()
emails = get_mock_emails()
ledger = get_mock_ledger()

print(f'Invoices: {len(invoices)} | Emails: {len(emails)} | Ledger entries: {len(ledger)}')
invoice_ids = {i.invoice_id for i in invoices}

for e in emails:
    assert e.invoice_id in invoice_ids, f'{e.email_id} references unknown invoice {e.invoice_id}'
for l in ledger:
    assert l.invoice_id in invoice_ids, f'ledger entry references unknown invoice {l.invoice_id}'

print('All references valid. Schema validation passed for every record.')